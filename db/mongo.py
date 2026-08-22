"""
db/mongo.py — MongoDB data layer for A.P.E.X. Web.

Replaces the old SQLite App.py. Instead of 5 relational tables joined
at read time, this uses Mongo's document model: a quiz attempt embeds
its own per-question results directly, since they are always read and
written together. This removes 2 of the original 5 tables/collections
without losing any feature (Progress Dashboard, Weak Areas, History all
still work — see the functions below).

Collections:
  notes          { title, original_text, summary_text, created_at }
  quiz_attempts  { note_id, note_title, score, total, timestamp,
                   questions: [ {question, correct_answer, user_answer, is_correct} ] }
  chats          { role, message, timestamp, session_date }
"""

from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, DESCENDING

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
    db.quiz_attempts.create_index([("timestamp", DESCENDING)])
    db.quiz_attempts.create_index("note_id")
    db.chats.create_index([("session_date", DESCENDING), ("_id", DESCENDING)])
    db.notes.create_index([("created_at", DESCENDING)])


def _now():
    return datetime.now(timezone.utc)


def _oid(id_str):
    """Safely cast a string to ObjectId; returns None if it isn't a valid id
    (e.g. the client passed nothing because the note was never saved)."""
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None


# ── Notes (raw text + AI summary) ────────────────────────────────────────

def save_note(original_text, summary_text, title="Untitled Note"):
    db = get_db()
    doc = {
        "title": title,
        "original_text": original_text,
        "summary_text": summary_text,
        "created_at": _now(),
    }
    result = db.notes.insert_one(doc)
    return str(result.inserted_id)


def get_note(note_id):
    db = get_db()
    oid = _oid(note_id)
    if not oid:
        return None
    doc = db.notes.find_one({"_id": oid})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ── Chat messages ─────────────────────────────────────────────────────────

def save_chat_message(role, message):
    db = get_db()
    now = datetime.now()
    db.chats.insert_one({
        "role": role,
        "message": message,
        "timestamp": now.strftime("%H:%M:%S"),
        "session_date": now.strftime("%Y-%m-%d"),
    })


def get_chat_history():
    """Returns messages oldest-first, same contract as the old App.get_chat_history()."""
    db = get_db()
    cursor = db.chats.find({}, {"_id": 0}).sort("_id", 1)
    return list(cursor)


# ── Quiz attempts + Progress analytics ───────────────────────────────────

def save_quiz_attempt(note_id, note_title, score, total, questions_data):
    """
    questions_data: [{"question", "correct_answer", "user_answer", "is_correct"}]
    If note_id is falsy (quiz wasn't linked to a saved note — e.g. a quick
    practice quiz), a lightweight Note stub is created so it still shows up
    in Progress/Topic history, mirroring the original SQLite behaviour.
    """
    db = get_db()
    oid = _oid(note_id) if note_id else None

    if oid is None:
        existing = db.notes.find_one({"title": note_title}, sort=[("created_at", DESCENDING)])
        if existing:
            oid = existing["_id"]
        else:
            oid = ObjectId(save_note(
                original_text=f"Practice quiz topic: {note_title}",
                summary_text=f"Quiz study notes and progress tracking for {note_title}.",
                title=note_title,
            ))

    db.quiz_attempts.insert_one({
        "note_id": oid,
        "note_title": note_title,
        "score": score,
        "total": total,
        "timestamp": _now(),
        "questions": questions_data,
    })
    return str(oid)


def get_progress_statistics():
    db = get_db()
    pipeline = [
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


def get_topic_performance():
    """Latest attempt per note/topic, newest first."""
    db = get_db()
    pipeline = [
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
        pct = int((r["score"] / r["total"]) * 100) if r["total"] else 0
        results.append({
            "note_id": str(r["_id"]) if r["_id"] else None,
            "title": r["note_title"] or "Untitled Topic",
            "score": r["score"],
            "total": r["total"],
            "score_pct": pct,
        })
    return results


def get_weak_areas(limit=15):
    """Most recent incorrectly-answered questions across all attempts, deduplicated by question text."""
    db = get_db()
    cursor = db.quiz_attempts.find({}, {"note_title": 1, "note_id": 1, "questions": 1}).sort("timestamp", DESCENDING).limit(50)

    seen, results = set(), []
    for attempt in cursor:
        for q in attempt.get("questions", []):
            if q.get("is_correct"):
                continue
            key = q["question"]
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "note_id": str(attempt["note_id"]) if attempt.get("note_id") else None,
                "title": attempt.get("note_title") or "Untitled Topic",
                "question": q["question"],
                "correct_answer": q["correct_answer"],
                "user_answer": q["user_answer"],
            })
            if len(results) >= limit:
                return results
    return results


def get_topic_history(note_id):
    db = get_db()
    oid = _oid(note_id)
    if not oid:
        return {"attempts": [], "missed_questions": []}

    cursor = db.quiz_attempts.find({"note_id": oid}).sort("timestamp", DESCENDING)
    attempts, missed, seen = [], [], set()
    for a in cursor:
        pct = int((a["score"] / a["total"]) * 100) if a["total"] else 0
        attempts.append({
            "score": a["score"],
            "total": a["total"],
            "pct": pct,
            "created_at": a["timestamp"].strftime("%Y-%m-%d %H:%M"),
        })
        for q in a.get("questions", []):
            if not q.get("is_correct") and q["question"] not in seen and len(missed) < 20:
                seen.add(q["question"])
                missed.append({
                    "question": q["question"],
                    "correct_answer": q["correct_answer"],
                    "user_answer": q["user_answer"],
                })
    return {"attempts": attempts, "missed_questions": missed}
