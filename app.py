"""
app.py — A.P.E.X. Web (Flask entry point).

Routes:
    /                 -> redirects to /notes (or /login if signed out)
    /login, /register, /logout  -> auth
    /profile          -> view/edit account, quick stats
    /notes            -> Notes/Summarizer view      (paste/upload -> summary -> quiz)
    /chat             -> AI Tutor view               (streaming chat, resumable conversations)
    /progress         -> Progress Dashboard view      (stats, mastery, weak areas)
    /history          -> list of saved conversations, click one to resume it in /chat

    POST /api/upload            -> extract text from an uploaded PDF/DOCX/TXT
    POST /api/summarize         -> summarize text, save as a Note, return note_id + summary
    POST /api/quiz              -> generate an MCQ quiz from text (not persisted yet)
    POST /api/quiz/submit       -> persist a completed quiz attempt (Progress Dashboard data)
    POST /api/chat/stream       -> SSE stream of the tutor's reply, token by token
    POST /api/chat/new          -> start a fresh conversation, returns its id
    GET  /api/conversations/<id>        -> fetch a conversation's full message history (resume)
    POST /api/conversations/<id>/delete -> delete a conversation

Every page and every /api/* route below (other than auth + /healthz) requires
a logged-in user, and every database read/write is scoped to that user's
own data — see services/auth.py and db/mongo.py.
"""

import json
import traceback
from datetime import timedelta

from flask import Flask, render_template, request, jsonify, session, Response, redirect, url_for

import config
from services import document_import, summarizer, quiz_generator, chat_engine, auth
from db import mongo

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=config.SESSION_LIFETIME_DAYS)


# ── Auth pages ───────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register_page():
    if session.get("user_id"):
        return redirect(url_for("notes_page"))

    if request.method == "GET":
        return render_template("register.html")

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm_password") or ""

    if not name or not email or not password:
        return render_template("register.html", error="Please fill in every field.", name=name, email=email)
    if len(password) < 6:
        return render_template("register.html", error="Password must be at least 6 characters.", name=name, email=email)
    if password != confirm:
        return render_template("register.html", error="Passwords don't match.", name=name, email=email)

    try:
        user_id = mongo.create_user(name, email, auth.hash_password(password))
    except ValueError as e:
        return render_template("register.html", error=str(e), name=name, email=email)
    except Exception:
        traceback.print_exc()
        return render_template("register.html", error="Something went wrong — please try again.", name=name, email=email)

    auth.log_in_user({"_id": user_id, "name": name})
    return redirect(url_for("notes_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user_id"):
        return redirect(url_for("notes_page"))

    if request.method == "GET":
        return render_template("login.html")

    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    user = mongo.get_user_by_email(email)
    if not user or not auth.verify_password(user["password_hash"], password):
        return render_template("login.html", error="Incorrect email or password.", email=email)

    auth.log_in_user(user)
    next_url = request.args.get("next")
    return redirect(next_url if next_url and next_url.startswith("/") else url_for("notes_page"))


@app.route("/logout", methods=["POST", "GET"])
def logout():
    auth.log_out_user()
    return redirect(url_for("login_page"))


# ── Profile ──────────────────────────────────────────────────────────────

@app.route("/profile", methods=["GET", "POST"])
@auth.login_required
def profile_page():
    user = auth.current_user()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            name = (request.form.get("name") or "").strip()
            avatar_url = (request.form.get("avatar_url") or "").strip()
            if name:
                mongo.update_user_profile(user["_id"], name=name, avatar_url=avatar_url)
                session["user_name"] = name
                user = auth.current_user()
                info = "Profile updated."
            else:
                info = None
            try:
                stats = mongo.get_user_stats(user["_id"])
            except Exception:
                stats = {"total_quizzes": 0, "avg_score_pct": 0, "total_notes": 0}
            return render_template("profile.html", user=user, stats=stats, info=info)

        if action == "change_password":
            current_pw = request.form.get("current_password") or ""
            new_pw = request.form.get("new_password") or ""
            confirm_pw = request.form.get("confirm_new_password") or ""
            try:
                stats = mongo.get_user_stats(user["_id"])
            except Exception:
                stats = {"total_quizzes": 0, "avg_score_pct": 0, "total_notes": 0}

            if not auth.verify_password(user["password_hash"], current_pw):
                return render_template("profile.html", user=user, stats=stats, error="Current password is incorrect.")
            if len(new_pw) < 6:
                return render_template("profile.html", user=user, stats=stats, error="New password must be at least 6 characters.")
            if new_pw != confirm_pw:
                return render_template("profile.html", user=user, stats=stats, error="New passwords don't match.")

            mongo.update_user_password(user["_id"], auth.hash_password(new_pw))
            return render_template("profile.html", user=user, stats=stats, info="Password changed.")

    try:
        stats = mongo.get_user_stats(user["_id"])
    except Exception:
        traceback.print_exc()
        stats = {"total_quizzes": 0, "avg_score_pct": 0, "total_notes": 0}

    return render_template("profile.html", user=user, stats=stats)


# ── Page routes ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("notes_page") if session.get("user_id") else url_for("login_page"))


@app.route("/notes")
@auth.login_required
def notes_page():
    return render_template("notes.html", active="notes")


@app.route("/chat")
@auth.login_required
def chat_page():
    conversation_id = request.args.get("conversation_id", "")
    return render_template("chat.html", active="chat", conversation_id=conversation_id)


@app.route("/progress")
@auth.login_required
def progress_page():
    user = auth.current_user()
    try:
        stats = mongo.get_progress_statistics(user["_id"])
        topics = mongo.get_topic_performance(user["_id"])
        weak_areas = mongo.get_weak_areas(user["_id"])
    except Exception:
        # Database hiccup or nothing saved yet — degrade to an empty dashboard
        # instead of a 500 page.
        traceback.print_exc()
        stats = {"total_quizzes": 0, "avg_score_pct": 0}
        topics, weak_areas = [], []
    return render_template(
        "progress.html", active="progress",
        stats=stats, topics=topics, weak_areas=weak_areas,
    )


@app.route("/history")
@auth.login_required
def history_page():
    user = auth.current_user()
    try:
        conversations = mongo.list_conversations(user["_id"])
    except Exception:
        traceback.print_exc()
        conversations = []
    return render_template("history.html", active="history", conversations=conversations)


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ── Notes / Summarizer API ───────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
@auth.login_required
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
        return jsonify({"error": "Failed to read that file. Try a different file, or paste the text directly."}), 500


@app.route("/api/summarize", methods=["POST"])
@auth.login_required
def api_summarize():
    user = auth.current_user()
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    title = (data.get("title") or "Untitled Note").strip()
    target_length = int(data.get("target_length", 150))

    if not text:
        return jsonify({"error": "Paste or upload some notes first."}), 400

    try:
        summary = summarizer.summarize_text(text, target_length=target_length)
        note_id = mongo.save_note(user["_id"], original_text=text, summary_text=summary, title=title)
        return jsonify({"note_id": note_id, "summary": summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Summarization failed: {e}"}), 500


@app.route("/api/quiz", methods=["POST"])
@auth.login_required
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
@auth.login_required
def api_quiz_submit():
    user = auth.current_user()
    data = request.get_json(force=True) or {}
    note_id = data.get("note_id")
    note_title = data.get("note_title", "Untitled Note")
    questions = data.get("questions", [])

    if not questions:
        return jsonify({"error": "No quiz results to save."}), 400

    score = sum(1 for q in questions if q.get("is_correct"))
    total = len(questions)

    try:
        saved_note_id = mongo.save_quiz_attempt(user["_id"], note_id, note_title, score, total, questions)
        return jsonify({"note_id": saved_note_id, "score": score, "total": total})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Failed to save quiz attempt."}), 500


# ── Chat API (streaming, per-conversation) ────────────────────────────────

@app.route("/api/chat/stream", methods=["POST"])
@auth.login_required
def api_chat_stream():
    user = auth.current_user()
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    conversation_id = data.get("conversation_id")
    if not user_text:
        return jsonify({"error": "Empty message."}), 400

    try:
        if conversation_id:
            convo = mongo.get_conversation(user["_id"], conversation_id)
        else:
            convo = None

        if not convo:
            title = user_text[:60] + ("…" if len(user_text) > 60 else "")
            conversation_id = mongo.create_conversation(user["_id"], title=title)
            convo = {"messages": []}

        history = [{"role": m["role"], "content": m["content"]} for m in convo.get("messages", [])]
        history.append({"role": "user", "content": user_text})
        mongo.add_message_to_conversation(user["_id"], conversation_id, "user", user_text)
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Couldn't reach the database — please try again."}), 500

    def event_stream():
        full_reply = ""
        try:
            yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"
            for chunk_text in chat_engine.stream_reply(history[-config.MAX_CHAT_HISTORY_TURNS:]):
                full_reply += chunk_text
                yield f"data: {json.dumps({'chunk': chunk_text})}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        try:
            mongo.add_message_to_conversation(user["_id"], conversation_id, "assistant", full_reply)
        except Exception:
            traceback.print_exc()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/api/chat/new", methods=["POST"])
@auth.login_required
def api_chat_new():
    user = auth.current_user()
    try:
        conversation_id = mongo.create_conversation(user["_id"])
        return jsonify({"conversation_id": conversation_id})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Couldn't start a new conversation."}), 500


@app.route("/api/conversations/<conversation_id>", methods=["GET"])
@auth.login_required
def api_conversation_get(conversation_id):
    user = auth.current_user()
    try:
        convo = mongo.get_conversation(user["_id"], conversation_id)
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Couldn't load that conversation."}), 500
    if not convo:
        return jsonify({"error": "Conversation not found."}), 404
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in convo.get("messages", [])
    ]
    return jsonify({"conversation_id": convo["_id"], "title": convo.get("title", "New chat"), "messages": messages})


@app.route("/api/conversations/<conversation_id>/delete", methods=["POST"])
@auth.login_required
def api_conversation_delete(conversation_id):
    user = auth.current_user()
    try:
        ok = mongo.delete_conversation(user["_id"], conversation_id)
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Couldn't delete that conversation."}), 500
    return jsonify({"ok": ok})


if __name__ == "__main__":
    # Local dev only — Render runs this via gunicorn (see Procfile), not this block.
    app.run(host="0.0.0.0", port=5000, debug=True)
