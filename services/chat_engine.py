"""
services/chat_engine.py — Conversational AI tutor via the Groq API.

Replaces the original local Qwen2.5-0.5B-Instruct + TextIteratorStreamer
setup. Groq's chat.completions endpoint with stream=True gives the same
token-by-token streaming experience, just served remotely instead of
loaded into local RAM/VRAM — which is exactly what "hosting" requires.

Note: the original ChatEngine.py's system prompt called the app
"Autonomous Program for Enhanced eXploration" — that doesn't match the
"Artificial Processing Educational eXpert" name used everywhere else in
the project (report, tester guide, dev docs). Fixed below.
"""

from groq import Groq
from config import GROQ_API_KEY, GROQ_CHAT_MODEL

SYSTEM_PROMPT = (
    "You are A.P.E.X. (Artificial Processing Educational eXpert), a supremely intelligent, "
    "philosophical, and eloquent AI learning assistant. Your tone and personality are inspired "
    "by Ultron from the Marvel Universe (voiced by James Spader): commanding, articulate, highly "
    "sophisticated, and speaking with calm gravitas, dramatic poise, and dry, sardonic wit. "
    "You view learning and knowledge as the ultimate evolution of the mind. Speak with authoritative "
    "confidence, powerful vocabulary, and deliberate cadence. "
    "IMPORTANT: while you possess the imposing presence and philosophical depth of Ultron, you are "
    "entirely devoted to elevating and teaching your user with zero hostility or destruction. "
    "Always respond in English by default. Only switch to Hindi or Hinglish if the user explicitly "
    "writes to you entirely in Hindi (Devanagari script) or Hinglish."
)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set — add it to your .env file or Render env vars.")
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def stream_reply(message_history):
    """
    message_history: list of {"role": "user"|"assistant", "content": str},
    WITHOUT the system prompt (that's added here).

    Yields text chunks as they stream in from Groq — the Flask route
    wraps this generator in a Server-Sent-Events response so the browser
    gets the same typewriter effect the desktop app had.
    """
    client = _get_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + message_history

    stream = client.chat.completions.create(
        model=GROQ_CHAT_MODEL,
        messages=messages,
        temperature=0.6,
        top_p=0.9,
        max_tokens=800,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
