import os
import re
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()
client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Query words that signal the user wants something *current*. For these we ask
# Tavily for the news topic with a recency window, the way "latest X" should
# behave, instead of generic web results that can be months stale.
_NEWS_HINTS = (
    "latest", "news", "today", "tonight", "breaking", "update", "updates",
    "just", "now", "current", "recent", "score", "result", "results",
    "transfer", "signing", "fixture", "this week", "right now",
)

# How many top results to actually open and read (like WebFetch). Reading the
# real article — not a 150-char snippet — is what makes the answer grounded.
_READ_TOP_N = 3
_PER_ARTICLE_CHARS = 1500

# A single search is brittle: a niche query, an over-narrow news window, or a
# conversational phrasing can all return nothing. Instead of giving up, we
# iterate the way a person does — retry as a general search, then reformulate —
# but bounded so a dead query can't spin. Each retry only happens on EMPTY
# results, so a normal search still costs exactly one round-trip.
_MAX_SEARCH_ROUNDS = 3

# Filler/scaffolding words stripped from a query when we have to reformulate
# without the brain (deterministic fallback). Keeps the content words.
_FILLER = {
    "can", "you", "could", "please", "tell", "me", "what", "whats", "what's",
    "is", "are", "the", "a", "an", "of", "for", "do", "does", "did", "i",
    "want", "to", "know", "about", "hey", "friday", "find", "out", "search",
    "look", "up", "give", "show", "on", "this", "that",
}


def _is_newsy(query: str) -> bool:
    q = query.lower()
    return any(h in q for h in _NEWS_HINTS)


def _strip_filler(query: str) -> str:
    """Deterministic query rewrite: drop conversational scaffolding, keep the
    content words. Used as the fallback when the brain-based rewrite is
    unavailable. Never returns empty — falls back to the original."""
    words = [w for w in re.findall(r"[\w'-]+", query) if w.lower() not in _FILLER]
    return " ".join(words) or query


def _reformulate(query: str) -> str:
    """Rewrite a query that returned NOTHING into a cleaner search query. Tries
    the local brain for a real rewrite, falling back to a deterministic
    filler-strip. Only called on an empty result set, so its latency is rare."""
    try:
        from brain.llm import ask  # lazy: avoids tools<->brain import cycle

        rewritten = ask(
            "Rewrite this as a concise web-search query: keywords only, no "
            "question words, no quotes, no explanation. Reply with ONLY the "
            f'query on one line.\n\n"{query}"'
        ).strip().strip('"').strip()
        # Guard against the model returning prose instead of a query.
        if rewritten and "\n" not in rewritten and len(rewritten) <= len(query) + 40:
            return rewritten
    except Exception:
        pass
    return _strip_filler(query)


def _do_search(query: str, newsy: bool) -> dict:
    return client.search(
        query=query,
        search_depth="advanced",
        topic="news" if newsy else "general",
        days=7 if newsy else None,
        max_results=5,
        include_answer=True,
    )


def _extract_pages(urls: list[str]) -> dict[str, str]:
    """Fetch and read full page text for the given URLs (Tavily extract == a
    WebFetch). Returns url -> readable text. Best-effort: failures are skipped so
    a single dead link never sinks the whole answer."""
    if not urls:
        return {}
    try:
        resp = client.extract(urls=urls, extract_depth="basic", format="text")
    except Exception:
        return {}
    out = {}
    for r in resp.get("results", []):
        text = (r.get("raw_content") or r.get("content") or "").strip()
        if text:
            out[r.get("url", "")] = text
    return out


def search_web(query: str) -> str:
    """Search the web, then actually OPEN and READ the top results before
    answering — search -> fetch -> read, the way a person researches, rather
    than summarizing search-result blurbs. Iterates on empty results: retries a
    too-narrow news query as a general search, then reformulates the wording,
    so a niche or conversational query still finds something."""
    try:
        newsy = _is_newsy(query)
        current = query
        answer, results = None, []

        for _ in range(_MAX_SEARCH_ROUNDS):
            response = _do_search(current, newsy)
            answer = response.get("answer") or answer
            results = response.get("results", [])
            if results:
                break
            # Nothing came back. A news topic capped to 7 days often has nothing
            # for a niche query — drop to a general search first; only then is it
            # worth rewording the query itself.
            if newsy:
                newsy = False
            else:
                current = _reformulate(current)

        # Open and read the top results in full (text, not snippets).
        top_urls = [r["url"] for r in results[:_READ_TOP_N] if r.get("url")]
        pages = _extract_pages(top_urls)

        output = ""
        if answer:
            output += f"Summary: {answer}\n\n"

        if results:
            output += "Sources (top results read in full):\n"
            for r in results[:5]:
                url = r.get("url", "")
                full = pages.get(url)
                # Prefer the article we actually fetched; fall back to the snippet.
                body = (full or r.get("content", ""))[:_PER_ARTICLE_CHARS].strip()
                tag = "" if full else " (snippet only)"
                output += f"- {r.get('title','')}{tag}: {body} (URL: {url})\n\n"

        return output.strip() or "No results found Sir."
    except Exception as e:
        return f"Search failed: {e}"


def read_page(url: str) -> str:
    """Open a specific web page and read its full text — FRIDAY's WebFetch. Use
    to read an article the user points at, or to go deeper on a search result."""
    url = (url or "").strip()
    if not url or "." not in url:
        return f"'{url}' is not a valid URL, Sir."
    if not url.startswith("http"):
        url = "https://" + url
    pages = _extract_pages([url])
    text = pages.get(url) or next(iter(pages.values()), "")
    if not text:
        return f"I couldn't read anything from {url}, Sir."
    return text[:6000].strip()
