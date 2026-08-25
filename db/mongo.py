"""
db/mongo.py — MongoDB data layer for A.P.E.X. Web.

Collections:
  users          { name, email, password_hash, avatar_url, created_at }
  notes          { user_id, title, original_text, summary_text, created_at }
  quiz_attempts  { user_id, note_id, note_title, score, total, timestamp,
                   questions: [ {question, correct_answer, user_answer, is_correct} ] }
  conversations  { user_id, title, created_at, updated_at,
                   messages: [ {role, content, timestamp} ] }

Everything except user creation is scoped to a `user_id` (ObjectId) so
one person's notes/quizzes/chats never show up for another person.
Old pre-login documents (no user_id) are left untouched in the database —
they just won't show up for anyone, since every query below filters by
user_id.
"""

from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, DESCENDING
from pymongo.errors import DuplicateKeyError

from config import MONGO_URI, MONGO_DB_NAME

_client = None
_db = None


def get_db():
    """Lazy singleton — one MongoClient per process (safe for Flask's threaded dev server
    and for gunicorn workers, since each worker process gets its own client on first use)."""
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
        _db = _client[MONGO_DB_NAME]
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    db.users.create_index("email", unique=True)
    db.notes.create_index([("user_id", 1), ("created_at", DESCENDING)])
    db.quiz_attempts.create_index([("user_id", 1), ("timestamp", DESCENDING)])
    db.quiz_attempts.create_index("note_id")
    db.conversations.create_index([("user_id", 1), ("updated_at", DESCENDING)])


def _now():
    return datetime.now(timezone.utc)


def _oid(id_str):
    """Safely cast a string to ObjectId; returns None if it isn't a valid id."""
    if isinstance(id_str, ObjectId):
        return id_str
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None


# ── Users / Auth ──────────────────────────────────────────────────────────

def create_user(name, email, password_hash, avatar_url=""):
    """Raises ValueError if the email is already registered."""
    db = get_db()
    doc = {
        "name": name.strip(),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "avatar_url": avatar_url,
        "created_at": _now(),
    }
    try:
        result = db.users.insert_one(doc)
    except DuplicateKeyError:
        raise ValueError("An account with that email already exists.")
    return str(result.inserted_id)


def get_user_by_email(email):
    db = get_db()
    doc = db.users.find_one({"email": email.strip().lower()})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_user_by_id(user_id):
    db = get_db()
    oid = _oid(user_id)
    if not oid:
        return None
    doc = db.users.find_one({"_id": oid})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def update_user_profile(user_id, name=None, avatar_url=None):
    db = get_db()
    oid = _oid(user_id)
    if not oid:
        return False
    updates = {}
    if name is not None and name.strip():
        updates["name"] = name.strip()
    if avatar_url is not None:
        updates["avatar_url"] = avatar_url.strip()
    if not updates:
        return False
    db.users.update_one({"_id": oid}, {"$set": updates})
    return True


def update_user_password(user_id, new_password_hash):
    db = get_db()
    oid = _oid(user_id)
    if not oid:
        return False
    db.users.update_one({"_id": oid}, {"$set": {"password_hash": new_password_hash}})
    return True


def get_user_stats(user_id):
    """Small profile-page stat block: quizzes taken + avg score for this user."""
    stats = get_progress_statistics(user_id)
    note_count = get_db().notes.count_documents({"user_id": _oid(user_id)})
    return {
        "total_quizzes": stats["total_quizzes"],
        "avg_score_pct": stats["avg_score_pct"],
        "total_notes": note_count,
    }


# ── Notes (raw text + AI summary) ────────────────────────────────────────

def save_note(user_id, original_text, summary_text, title="Untitled Note"):
    db = get_db()
    doc = {
        "user_id": _oid(user_id),
        "title": title,
        "original_text": original_text,
        "summary_text": summary_text,
        "created_at": _now(),
    }
    result = db.notes.insert_one(doc)
    return str(result.inserted_id)


def get_note(user_id, note_id):
    db = get_db()
    oid = _oid(note_id)
    if not oid:
        return None
    doc = db.notes.find_one({"_id": oid, "user_id": _oid(user_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ── Conversations (chat sessions, resumable) ─────────────────────────────

def create_conversation(user_id, title="New chat"):
    db = get_db()
    now = _now()
    doc = {
        "user_id": _oid(user_id),
        "title": title[:80] or "New chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    result = db.conversations.insert_one(doc)
    return str(result.inserted_id)


def add_message_to_conversation(user_id, conversation_id, role, content):
    """Appends a message. If the conversation doesn't exist (or doesn't belong to
    this user), returns None instead of writing anywhere — callers should create
    a fresh conversation first if this happens."""
    db = get_db()
    oid = _oid(conversation_id)
    if not oid:
        return None
    now = _now()
    result = db.conversations.update_one(
        {"_id": oid, "user_id": _oid(user_id)},
        {
            "$push": {"messages": {"role": role, "content": content, "timestamp": now}},
            "$set": {"updated_at": now},
        },
    )
    return conversation_id if result.matched_count else None


def get_conversation(user_id, conversation_id):
    db = get_db()
    oid = _oid(conversation_id)
    if not oid:
        return None
    doc = db.conversations.find_one({"_id": oid, "user_id": _oid(user_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def list_conversations(user_id):
    """Newest-first, with a short preview of the last message for the History list."""
    db = get_db()
    cursor = db.conversations.find(
        {"user_id": _oid(user_id)}
    ).sort("updated_at", DESCENDING)

    results = []
    for c in cursor:
        last = c["messages"][-1] if c.get("messages") else None
        preview = (last["content"][:120] + "…") if last and len(last["content"]) > 120 else (last["content"] if last else "")
        results.append({
            "id": str(c["_id"]),
            "title": c.get("title") or "New chat",
            "updated_at": c["updated_at"],
            "message_count": len(c.get("messages", [])),
            "preview": preview,
        })
    return results


def delete_conversation(user_id, conversation_id):
    db = get_db()
    oid = _oid(conversation_id)
    if not oid:
        return False
    result = db.conversations.delete_one({"_id": oid, "user_id": _oid(user_id)})
    return result.deleted_count > 0


def rename_conversation(user_id, conversation_id, title):
    db = get_db()
    oid = _oid(conversation_id)
    if not oid or not title.strip():
        return False
    result = db.conversations.update_one(
        {"_id": oid, "user_id": _oid(user_id)},
        {"$set": {"title": title.strip()[:80]}},
    )
    return result.matched_count > 0


# ── Quiz attempts + Progress analytics ───────────────────────────────────

def save_quiz_attempt(user_id, note_id, note_title, score, total, questions_data):
    db = get_db()
    uid = _oid(user_id)
    oid = _oid(note_id) if note_id else None

    if oid is None:
        existing = db.notes.find_one({"user_id": uid, "title": note_title}, sort=[("created_at", DESCENDING)])
        if existing:
            oid = existing["_id"]
        else:
            oid = ObjectId(save_note(
                user_id=user_id,
                original_text=f"Practice quiz topic: {note_title}",
                summary_text=f"Quiz study notes and progress tracking for {note_title}.",
                title=note_title,
            ))

    db.quiz_attempts.insert_one({
        "user_id": uid,
        "note_id": oid,
        "note_title": note_title,
        "score": score,
        "total": total,
        "timestamp": _now(),
        "questions": questions_data,
    })
    return str(oid)


def get_progress_statistics(user_id):
    db = get_db()
    pipeline = [
        {"$match": {"user_id": _oid(user_id)}},
        {"$group": {
            "_id": None,
            "total_score": {"$sum": "$score"},
            "total_questions": {"$sum": "$total"},
            "total_quizzes": {"$sum": 1},
        }}
    ]
    rows = list(db.quiz_attempts.aggregate(pipeline))
    if not rows or not rows[0]["total_questions"]:
        return {"total_quizzes": 0, "avg_score_pct": 0}
    r = rows[0]
    return {
        "total_quizzes": r["total_quizzes"],
        "avg_score_pct": int((r["total_score"] / r["total_questions"]) * 100),
    }


def get_topic_performance(user_id):
    """Latest attempt per note/topic, newest first."""
    db = get_db()
    pipeline = [
        {"$match": {"user_id": _oid(user_id)}},
        {"$sort": {"timestamp": DESCENDING}},
        {"$group": {
            "_id": "$note_id",
            "note_title": {"$first": "$note_title"},
            "score": {"$first": "$score"},
            "total": {"$first": "$total"},
        }},
        {"$sort": {"_id": -1}},
    ]
    results = []
    for r in db.quiz_attempts.aggregate(pipeline):
        total = r.get("total") or 0
        pct = int((r["score"] / total) * 100) if total else 0
        results.append({
            "note_id": str(r["_id"]) if r["_id"] else None,
            "title": r["note_title"] or "Untitled Topic",
            "score": r["score"],
            "total": total,
            "score_pct": pct,
        })
    return results


def get_weak_areas(user_id, limit=15):
    """Most recent incorrectly-answered questions across all attempts, deduplicated by question text."""
    db = get_db()
    cursor = db.quiz_attempts.find(
        {"user_id": _oid(user_id)}, {"note_title": 1, "note_id": 1, "questions": 1}
    ).sort("timestamp", DESCENDING).limit(50)

    seen, results = set(), []
    for attempt in cursor:
        for q in attempt.get("questions", []):
            if q.get("is_correct"):
                continue
            key = q.get("question")
            if not key or key in seen:
                continue
            seen.add(key)
            results.append({
                "note_id": str(attempt["note_id"]) if attempt.get("note_id") else None,
                "title": attempt.get("note_title") or "Untitled Topic",
                "question": q.get("question", ""),
                "correct_answer": q.get("correct_answer", ""),
                "user_answer": q.get("user_answer", ""),
            })
            if len(results) >= limit:
                return results
    return results


def get_topic_history(user_id, note_id):
    db = get_db()
    oid = _oid(note_id)
    if not oid:
        return {"attempts": [], "missed_questions": []}

    cursor = db.quiz_attempts.find({"user_id": _oid(user_id), "note_id": oid}).sort("timestamp", DESCENDING)
    attempts, missed, seen = [], [], set()
    for a in cursor:
        total = a.get("total") or 0
        pct = int((a["score"] / total) * 100) if total else 0
        attempts.append({
            "score": a["score"],
            "total": total,
            "pct": pct,
            "created_at": a["timestamp"].strftime("%Y-%m-%d %H:%M"),
        })
        for q in a.get("questions", []):
            if not q.get("is_correct") and q.get("question") not in seen and len(missed) < 20:
                seen.add(q.get("question"))
                missed.append({
                    "question": q.get("question", ""),
                    "correct_answer": q.get("correct_answer", ""),
                    "user_answer": q.get("user_answer", ""),
                })
    return {"attempts": attempts, "missed_questions": missed}
