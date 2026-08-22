# A.P.E.X. Web

Artificial Processing Educational eXpert — restructured from a Windows
desktop app (Tkinter/CustomTkinter, local models, SQLite) into a hostable
Flask web app (Groq API, MongoDB).

## What changed from the original desktop version

| Original | Web version | Why |
|---|---|---|
| `GUI.py` + `SplashScreen.py` + `MacTitleBar.py` (CustomTkinter) | `templates/*.html` + `static/` (Flask + vanilla JS) | Tkinter renders to a native OS window, not a browser — it cannot be hosted on Render/Streamlit as-is. |
| Local Qwen2.5-0.5B-Instruct (`ChatEngine.py`, ~1GB+ RAM) | Groq API, `qwen/qwen3-32b` (`services/chat_engine.py`) | No GPU/RAM to host a local model on a free web dyno — a hosted LLM API does the job, and is actually a stronger model. |
| Local distilBART-CNN (`Summarizer.py`) | Same Groq model via a summarization prompt (`services/summarizer.py`) | One API instead of two separate models — simpler to host, no meaningful quality loss for study notes. |
| `ModelManager.py` (RAM/GPU orchestration) | *(removed)* | Only needed for juggling local models in limited RAM — irrelevant once inference is remote. |
| `UpdateEngine.py` (GitHub self-updater) | *(removed)* | Self-updating `.exe` installers don't apply to a web app — you just redeploy. |
| `VoiceEngine.py` (mic STT + pyttsx3/SAPI TTS) | *(removed for now)* | pyttsx3/SAPI is Windows-only and won't run on Render's Linux containers; mic-based STT would need browser `MediaRecorder` + a hosted STT API. Flagged in "Not yet ported" below — same "designed, shipped later" treatment the original project gave `WebSearchEngine.py`. |
| `App.py` (SQLite CRUD) | `db/mongo.py` (MongoDB) | Per your ask — 5 SQLite tables became 3 Mongo collections (`quiz_attempts` now embeds its own per-question results instead of a separate `QuestionAttempts` table/collection, since they're always read/written together). |
| `QuizGenerator.py` (spaCy NER/POS) | `services/quiz_generator.py` | **Unchanged logic** — it's rule-based, not an AI model, so it just runs server-side as-is. |
| `CrashGuard.py` (Tkinter exception hooks) | Flask try/except + JSON error responses | Different runtime, same intent: never show the user a raw stack trace. |

### Not yet ported
Voice input/output — would need the browser's `MediaRecorder` API on the
frontend plus a hosted STT service (Groq also serves Whisper, so this is a
reasonable next step, not a redesign).

## Project layout

```
app.py                    Flask routes (the new "GUI.py")
config.py                 env-based settings (API keys, Mongo URI)
db/mongo.py                MongoDB data layer (the new "App.py")
services/
  chat_engine.py            Groq streaming chat (the new "ChatEngine.py")
  summarizer.py              Groq summarization (the new "Summarizer.py")
  quiz_generator.py          spaCy MCQ generator (ported as-is)
  document_import.py         PDF/DOCX/TXT text extraction
templates/                 Jinja2 pages (notes, chat, progress, history)
static/css/style.css        Design system (dark glassmorphism, carried over
                             from the original app's color palette)
static/js/                  notes.js, chat.js — frontend interactivity
```

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

cp .env.example .env   # then fill in GROQ_API_KEY and MONGO_URI
python app.py          # http://localhost:5000
```

## Getting the two API keys / connection strings you need

1. **Groq** — [console.groq.com](https://console.groq.com) → sign up (no card) → **API Keys** → create key. Paste into `GROQ_API_KEY`.
2. **MongoDB Atlas** — [cloud.mongodb.com](https://cloud.mongodb.com) → create a free **M0** cluster → **Database Access**: add a user/password → **Network Access**: allow `0.0.0.0/0` (or Render's IPs) → **Connect → Drivers** → copy the `mongodb+srv://...` string into `MONGO_URI`.

## Deploying to Render

1. Push this folder to a GitHub repo.
2. Render → **New → Blueprint** → point at the repo (it will read `render.yaml` automatically), **or** New → Web Service manually with:
   - Build command: `pip install -r requirements.txt && python -m spacy download en_core_web_sm`
   - Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
3. Under **Environment**, set `GROQ_API_KEY` and `MONGO_URI` (these are marked `sync: false` in `render.yaml` on purpose — secrets aren't committed to git).
4. Deploy. Visit `/healthz` to confirm it's up.

## A note on the Groq model name

`qwen/qwen3-32b` is current as of this writing. If it ever fails with a
"model decommissioned" error, check the live list at
[console.groq.com/docs/models](https://console.groq.com/docs/models) and
update `GROQ_CHAT_MODEL` / `GROQ_SUMMARY_MODEL` in your env vars — no code
change needed.
