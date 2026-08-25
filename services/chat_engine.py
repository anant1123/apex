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

Web search: the model gets a `web_search` tool (see services/web_search.py,
DuckDuckGo-backed, no API key). If it decides a question needs current
info, it calls the tool first, then answers grounded in real results —
if the search fails or the package isn't available it just falls back
to answering from its own knowledge, so this never breaks the chat.
"""

from groq import Groq
from config import GROQ_API_KEY, GROQ_CHAT_MODEL
from services.web_search import web_search, format_results_for_prompt, WEB_SEARCH_TOOL_SCHEMA

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
    "writes to you entirely in Hindi (Devanagari script) or Hinglish. "
    "You have a web_search tool. Use it when the student asks about something current, recent, or "
    "time-sensitive (news, latest versions, prices, live facts) that your own knowledge may not "
    "cover. Don't mention the tool by name to the user — just answer naturally, citing sources by "
    "name when you used them."
)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set — add it to your .env file or Render env vars.")
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _maybe_run_tool_call(messages):
    """
    One non-streaming call with tools enabled, purely to let the model decide
    whether it needs to search the web. Returns (messages, tool_was_used).
    If the model calls web_search, this executes the search, appends the
    tool result to `messages`, and returns the updated list so the caller
    can do the real (streaming) generation grounded in fresh results.
    """
    client = _get_client()
    try:
        decision = client.chat.completions.create(
            model=GROQ_CHAT_MODEL,
            messages=messages,
            tools=[WEB_SEARCH_TOOL_SCHEMA],
            tool_choice="auto",
            temperature=0.3,
            max_tokens=400,
        )
    except Exception:
        # Tool-calling not supported / network hiccup — just skip search entirely.
        return messages, False

    msg = decision.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)
    if not tool_calls:
        return messages, False

    import json as _json
    call = tool_calls[0]
    try:
        args = _json.loads(call.function.arguments or "{}")
    except ValueError:
        args = {}
    query = args.get("query", "").strip()
    if not query:
        return messages, False

    results = web_search(query)
    tool_result_text = format_results_for_prompt(results) or "No results found."

    messages = messages + [
        {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": "web_search", "arguments": call.function.arguments},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call.id,
            "content": tool_result_text,
        },
    ]
    return messages, True


def stream_reply(message_history, note_context=None):
    """
    message_history: list of {"role": "user"|"assistant", "content": str},
    WITHOUT the system prompt (that's added here).

    note_context: optional text (a saved note's summary or original text) the
    student is currently "discussing" — see app.py's /api/chat/stream, which
    attaches this once when a conversation is created via "Discuss this note
    in Tutor" or the chat page's note picker. When present, it's injected as
    a second system message so the tutor can answer questions grounded in
    that specific material instead of only its general knowledge.

    Yields text chunks as they stream in from Groq — the Flask route
    wraps this generator in a Server-Sent-Events response so the browser
    gets the same typewriter effect the desktop app had.
    """
    client = _get_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if note_context:
        messages.append({
            "role": "system",
            "content": (
                "The student is currently studying the notes below. When they ask a "
                "question, check whether it's about this material first and answer "
                "grounded in it — quote or paraphrase the relevant part rather than "
                "guessing. They may also ask unrelated questions; answer those normally."
                "\n\n--- STUDENT'S NOTES ---\n" + note_context
            ),
        })

    messages += message_history
    messages, _used_search = _maybe_run_tool_call(messages)

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
