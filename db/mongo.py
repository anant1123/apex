"""
db/mongo.py — MongoDB data layer for A.P.E.X. Web.

Collections:
  users          { name, email, avatar_url, created_at }
  otp_codes      { email, code, expires_at, attempts }  (TTL-indexed — auto-deletes on expiry)
  notes          { user_id, title, original_text, summary_text, created_at }
  quiz_attempts  { user_id, note_id, note_title, score, total, timestamp,
                   questions: [ {question, correct_answer, user_answer, is_correct} ] }
  conversations  { user_id, title, note_id, note_context, created_at, updated_at,
                   messages: [ {role, content, timestamp} ] }

Everything except user creation is scoped to a `user_id` (ObjectId) so
one person's notes/quizzes/chats never show up for another person.
Login is passwordless: a 6-digit code is emailed to the user (see
services/email_sender.py) and verified against `otp_codes`; the first
successful verification for a new email auto-creates the user record.
"""

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, DESCENDING
from pymongo.errors import DuplicateKeyError

from config import MONGO_URI, MONGO_DB_NAME

_client = None
_db = None


def get_db():
    """Lazy singleton — one MongoClient per process (safe for Flask's threaded dev server
    and for gunicorn workers, since each worker process gets its own client on first use).
    tz_aware=True so datetimes read back from Mongo are UTC-aware, matching _now() below —
    otherwise comparing them (e.g. OTP expiry) raises a naive-vs-aware TypeError."""
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, tz_aware=True)
        _db = _client[MONGO_DB_NAME]
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    db.users.create_index("email", unique=True)
    db.otp_codes.create_index("email")
    db.otp_codes.create_index("expires_at", expireAfterSeconds=0)  # Mongo TTL auto-cleanup
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

def get_or_create_user_by_email(email, default_name):
    """Used by the OTP login flow: returns the existing user, or creates one
    on the first successful verification for a brand-new email."""
    db = get_db()
    email = email.strip().lower()
    doc = db.users.find_one({"email": email})
    if doc:
        doc["_id"] = str(doc["_id"])
        return doc

    new_doc = {
        "name": default_name.strip() or email.split("@")[0].capitalize(),
        "email": email,
        "avatar_url": "",
        "created_at": _now(),
    }
    try:
        result = db.users.insert_one(new_doc)
    except DuplicateKeyError:
        # Race: two verifications for the same brand-new email at once — just re-read.
        doc = db.users.find_one({"email": email})
        doc["_id"] = str(doc["_id"])
        return doc
    new_doc["_id"] = str(result.inserted_id)
    return new_doc


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


# ── OTP login codes ───────────────────────────────────────────────────────

def create_otp(email, code, expiry_minutes):
    """Overwrites any previous code for this email (upsert) and resets attempts.
    The `expires_at` TTL index (see _ensure_indexes) cleans these up automatically."""
    db = get_db()
    email = email.strip().lower()
    expires_at = _now() + timedelta(minutes=expiry_minutes)
    db.otp_codes.update_one(
        {"email": email},
        {"$set": {"code": code, "expires_at": expires_at, "attempts": 0}},
        upsert=True,
    )


def verify_and_consume_otp(email, code, max_attempts):
    """Returns 'ok', 'wrong', 'expired', or 'too_many_attempts'.
    On 'ok', the code is deleted so it can't be reused (single-use)."""
    db = get_db()
    email = email.strip().lower()
    doc = db.otp_codes.find_one({"email": email})

    if not doc or doc["expires_at"] < _now():
        return "expired"
    if doc.get("attempts", 0) >= max_attempts:
        return "too_many_attempts"
    if doc["code"] != code.strip():
        db.otp_codes.update_one({"email": email}, {"$inc": {"attempts": 1}})
        return "wrong"

    db.otp_codes.delete_one({"email": email})
    return "ok"


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


def list_notes_brief(user_id):
    """Just id/title/created_at, for the "attach a note" picker in the Tutor UI
    (fetching a small list is cheap; full note bodies stay lazy-loaded on demand)."""
    db = get_db()
    cursor = db.notes.find(
        {"user_id": _oid(user_id)}, {"title": 1, "created_at": 1}
    ).sort("created_at", DESCENDING).limit(50)
    return [{"id": str(n["_id"]), "title": n.get("title") or "Untitled Note"} for n in cursor]


# ── Conversations (chat sessions, resumable) ─────────────────────────────

def create_conversation(user_id, title="New chat", note_id=None, note_context=None):
    """note_id/note_context (optional): when the user starts a chat from a saved
    note ("Discuss this in Tutor"), that note's text is attached here once, at
    creation time, and reused for every message in the conversation — see
    services/chat_engine.py."""
    db = get_db()
    now = _now()
    doc = {
        "user_id": _oid(user_id),
        "title": title[:80] or "New chat",
        "note_id": _oid(note_id) if note_id else None,
        "note_context": note_context or None,
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
        if doc.get("note_id"):
            doc["note_id"] = str(doc["note_id"])
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
