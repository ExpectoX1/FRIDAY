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
_READ_TOP_N = 2
_PER_ARTICLE_CHARS = 1200


def _is_newsy(query: str) -> bool:
    q = query.lower()
    return any(h in q for h in _NEWS_HINTS)


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
    than summarizing search-result blurbs."""
    try:
        response = client.search(
            query=query,
            search_depth="advanced",          # better, more relevant results
            topic="news" if _is_newsy(query) else "general",
            days=7 if _is_newsy(query) else None,
            max_results=5,
            include_answer=True,              # Tavily's own quick summary
        )

        answer = response.get("answer")
        results = response.get("results", [])

        # Open and read the top couple of articles (full text, not snippets).
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
