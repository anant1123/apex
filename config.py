"""
config.py — Centralized configuration for A.P.E.X. Web.

Everything here is read from environment variables so the same code
runs locally (.env file) and on Render (dashboard env vars) without
any code changes. NEVER hardcode API keys or connection strings here.
"""

import os
from dotenv import load_dotenv

# Loads a local .env file if present (harmless no-op on Render, where
# env vars are injected directly by the platform).
load_dotenv()


def _require(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    if not value:
        print(f"[config] WARNING: {name} is not set. Set it in your .env file "
              f"or in Render's Environment tab.")
    return value


# --- Groq (LLM API — powers both the Chat Tutor and the Summarizer) ---
GROQ_API_KEY = _require("GROQ_API_KEY")

# Official current model IDs — verify at https://console.groq.com/docs/models
# if either of these ever 404s with a "model does not exist" error (Groq
# deprecates models with ~1 month notice — qwen/qwen3-32b was retired
# June 17, 2026, which is why this isn't set to that anymore).
GROQ_CHAT_MODEL = os.environ.get("GROQ_CHAT_MODEL", "openai/gpt-oss-20b")
GROQ_SUMMARY_MODEL = os.environ.get("GROQ_SUMMARY_MODEL", "openai/gpt-oss-20b")

# --- MongoDB ---
MONGO_URI = _require("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "apex_db")

# --- Flask ---
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me-in-production")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
SESSION_LIFETIME_DAYS = int(os.environ.get("SESSION_LIFETIME_DAYS", "30"))

# --- Email OTP login (SMTP) ---
# Gmail: use smtp.gmail.com:587 with a 16-character App Password (not your
# normal password) — needs 2-Step Verification turned on first, then
# generate one at myaccount.google.com/apppasswords. Any other SMTP
# provider (Brevo, Resend's SMTP endpoint, your college's mail server) works
# the same way, just change these four values.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "A.P.E.X.")
OTP_EXPIRY_MINUTES = int(os.environ.get("OTP_EXPIRY_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))

# --- App behaviour ---
MAX_CHAT_HISTORY_TURNS = 12   # how many past turns are sent back to Groq for context
