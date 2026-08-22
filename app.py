"""
app.py — A.P.E.X. Web (Flask entry point).

Maps the original desktop app's 5 views onto 5 routes, backed by a
small JSON + Server-Sent-Events API that the page JS (static/js/*.js)
calls into:

    /                 -> redirects to /notes
    /notes            -> Notes/Summarizer view      (paste/upload -> summary -> quiz)
    /chat             -> AI Tutor view               (streaming chat)
    /progress         -> Progress Dashboard view      (stats, mastery, weak areas)
    /history          -> Chat History view

    POST /api/upload         -> extract text from an uploaded PDF/DOCX/TXT
    POST /api/summarize      -> summarize text, save as a Note, return note_id + summary
    POST /api/quiz           -> generate an MCQ quiz from text (not persisted yet)
    POST /api/quiz/submit    -> persist a completed quiz attempt (Progress Dashboard data)
    POST /api/chat/stream    -> SSE stream of the tutor's reply, token by token
    POST /api/chat/reset     -> clear the current browser session's chat context
"""

import json
import traceback

from flask import Flask, render_template, request, jsonify, session, Response

import config
from services import document_import, summarizer, quiz_generator, chat_engine
from db import mongo

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


# ── Page routes ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("notes.html", active="notes")


@app.route("/notes")
def notes_page():
    return render_template("notes.html", active="notes")


@app.route("/chat")
def chat_page():
    return render_template("chat.html", active="chat")


@app.route("/progress")
def progress_page():
    stats = mongo.get_progress_statistics()
    topics = mongo.get_topic_performance()
    weak_areas = mongo.get_weak_areas()
    return render_template(
        "progress.html", active="progress",
        stats=stats, topics=topics, weak_areas=weak_areas,
    )


@app.route("/history")
def history_page():
    messages = mongo.get_chat_history()
    sessions = {}
    for m in messages:
        sessions.setdefault(m["session_date"], []).append(m)
    ordered_dates = sorted(sessions.keys(), reverse=True)
    return render_template(
        "history.html", active="history",
        ordered_dates=ordered_dates, sessions=sessions,
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ── Notes / Summarizer API ───────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    try:
        text = document_import.extract_text(request.files["file"])
        if not text:
            return jsonify({"error": "Couldn't find any text in that file."}), 400
        return jsonify({"text": text})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Failed to read that file."}), 500


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    title = (data.get("title") or "Untitled Note").strip()
    target_length = int(data.get("target_length", 150))

    if not text:
        return jsonify({"error": "Paste or upload some notes first."}), 400

    try:
        summary = summarizer.summarize_text(text, target_length=target_length)
        note_id = mongo.save_note(original_text=text, summary_text=summary, title=title)
        return jsonify({"note_id": note_id, "summary": summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Summarization failed: {e}"}), 500


@app.route("/api/quiz", methods=["POST"])
def api_quiz():
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    max_questions = int(data.get("max_questions", 10))

    if not text:
        return jsonify({"error": "No text to generate a quiz from."}), 400

    try:
        questions = quiz_generator.generate_quiz(text, max_questions=max_questions)
        if not questions:
            return jsonify({"error": "Couldn't extract enough quality sentences for a quiz. Try longer notes."}), 400
        return jsonify({"questions": questions})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Quiz generation failed."}), 500


@app.route("/api/quiz/submit", methods=["POST"])
def api_quiz_submit():
    data = request.get_json(force=True) or {}
    note_id = data.get("note_id")
    note_title = data.get("note_title", "Untitled Note")
    questions = data.get("questions", [])

    if not questions:
        return jsonify({"error": "No quiz results to save."}), 400

    score = sum(1 for q in questions if q.get("is_correct"))
    total = len(questions)

    try:
        saved_note_id = mongo.save_quiz_attempt(note_id, note_title, score, total, questions)
        return jsonify({"note_id": saved_note_id, "score": score, "total": total})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Failed to save quiz attempt."}), 500


# ── Chat API (streaming) ──────────────────────────────────────────────────

@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    if not user_text:
        return jsonify({"error": "Empty message."}), 400

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": user_text})
    mongo.save_chat_message("You", user_text)

    def event_stream():
        full_reply = ""
        try:
            for chunk_text in chat_engine.stream_reply(history[-config.MAX_CHAT_HISTORY_TURNS:]):
                full_reply += chunk_text
                yield f"data: {json.dumps({'chunk': chunk_text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        history.append({"role": "assistant", "content": full_reply})
        session["chat_history"] = history[-config.MAX_CHAT_HISTORY_TURNS:]
        mongo.save_chat_message("A.P.E.X.", full_reply)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    session.pop("chat_history", None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Local dev only — Render runs this via gunicorn (see Procfile), not this block.
    app.run(host="0.0.0.0", port=5000, debug=True)
