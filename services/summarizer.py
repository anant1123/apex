"""
services/summarizer.py — AI text summarization via the Groq API.

Replaces the original local distilBART-CNN model. Rather than hosting a
second, separate summarization model, this reuses the same Groq chat
model as the tutor (see chat_engine.py) with a purpose-built prompt —
one API key, one dependency, simpler to host for free.
"""

from groq import Groq
from config import GROQ_API_KEY, GROQ_SUMMARY_MODEL

_client = None


def _get_client():
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set — add it to your .env file or Render env vars.")
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def summarize_text(text, target_length=150):
    """
    Summarize `text` to roughly `target_length` tokens worth of content.
    `target_length` keeps the same meaning as the original slider
    (Brief/Normal/Detailed map to small/medium/large token budgets),
    so calling code elsewhere doesn't need to change.
    """
    if len(text.split()) < 30:
        return text.strip()

    client = _get_client()
    approx_words = max(40, int(target_length * 0.75))

    response = client.chat.completions.create(
        model=GROQ_SUMMARY_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise academic summarizer. Compress the user's study notes "
                    "into a clear, factual summary. Preserve key terms, names, numbers, and "
                    "concepts a student would need for a quiz. Do not add commentary, a preamble, "
                    "or a title — output only the summary paragraph itself."
                ),
            },
            {
                "role": "user",
                "content": f"Summarize the following notes in about {approx_words} words:\n\n{text}",
            },
        ],
        temperature=0.3,
        max_tokens=min(target_length + 150, 1024),
    )
    return response.choices[0].message.content.strip()
