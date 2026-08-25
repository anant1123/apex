"""
services/web_search.py — Lightweight live web search for the AI tutor.

Uses the `ddgs` package (DuckDuckGo Search) — no API key, no billing,
just a plain HTTP scrape wrapper, so it works out of the box on a free
Render dyno. This gives the tutor a way to answer "what's the latest
version of X" / "current news about Y" style questions instead of only
relying on the LLM's training data.

If the package or the network call fails for any reason (offline dev
box, DuckDuckGo rate-limit, etc.) this degrades gracefully — the tutor
just answers from its own knowledge instead of crashing the chat.
"""

def web_search(query, max_results=4):
    """Returns a short list of {title, snippet, url} dicts, or [] on failure."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

    return [
        {
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "url": r.get("href", ""),
        }
        for r in results
    ]


def format_results_for_prompt(results):
    """Turns search results into a compact block the LLM can cite from."""
    if not results:
        return ""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\n{r['snippet']}\nSource: {r['url']}")
    return "\n\n".join(lines)


# Tool schema in the OpenAI/Groq function-calling format.
WEB_SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the live web for current information — recent events, "
            "up-to-date facts, prices, versions, news, or anything that may "
            "have changed since your training data. Use this whenever the "
            "student asks about something current or time-sensitive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A short, specific web search query.",
                }
            },
            "required": ["query"],
        },
    },
}
