"""Read-only Gmail access over IMAP — the foundation for both on-demand reads
and the proactive important-mail monitor.

IMAP (not the Gmail API / an MCP server) on purpose: reading mail needs only an
app password the user drops in backend/.env, no OAuth project and no third-party
server in the middle, so it stays self-contained and private (mail flows
straight to FRIDAY's local brain). Gmail's IMAP supports the X-GM-RAW extension,
so we query with Gmail's own search syntax (is:starred, is:important, from:…,
newer_than:1d) — which is exactly what lets the user define "important to me".

Leaf module: no proactive/registry imports, so proactive/mail_monitor.py can
import the fetcher without an import cycle (mirrors tools/web.py for monitors).

"""
from __future__ import annotations

import email
import imaplib
import os
import re
from email.header import decode_header

from dotenv import load_dotenv

load_dotenv()

_IMAP_HOST = "imap.gmail.com"
_DEFAULT_LIMIT = 8


def _creds() -> tuple[str, str] | None:
    user = os.getenv("GMAIL_USER")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    return (user, pw) if user and pw else None


# ── natural language → Gmail search ──────────────────────────────────────────
# Pure + deterministic so it can be unit-tested without a network or account.
def _to_gmail_query(text: str) -> tuple[str, str]:
    """Translate a spoken request into a (gmail_search, spoken_label). Combines
    any recognised facets; falls back to unread mail when nothing matches."""
    t = (text or "").lower().strip()
    parts, labels = [], []

    if "starred" in t or "flagged" in t:
        parts.append("is:starred"); labels.append("starred")
    if "important" in t:
        parts.append("is:important"); labels.append("important")
    if "unread" in t or "new " in t or t in ("", "any", "mail", "email", "emails"):
        parts.append("is:unread"); labels.append("unread")

    m = re.search(r"from ([a-z0-9.@_\- ]+?)(?: today| this week| about|$)", t)
    if m:
        sender = m.group(1).strip().replace(" ", "")
        if sender:
            parts.append(f"from:{sender}"); labels.append(f"from {m.group(1).strip()}")

    if "today" in t:
        parts.append("newer_than:1d"); labels.append("today")
    elif "this week" in t or "week" in t:
        parts.append("newer_than:7d"); labels.append("this week")

    if not parts:  # nothing recognised → most useful default
        parts.append("is:unread"); labels.append("unread")

    # Dedup while preserving order.
    seen, query_parts = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p); query_parts.append(p)

    # Unbounded "is:unread" is useless on a real inbox (it can be tens of
    # thousands). When that's the ONLY facet — no sender, no date, no
    # star/importance to narrow it — bound it to recent mail so "check my email"
    # means "what's new", not "recite my entire backlog".
    if query_parts == ["is:unread"]:
        query_parts.append("newer_than:3d")
        labels = ["recent unread"]

    return " ".join(query_parts), " ".join(dict.fromkeys(labels))


def _decode(value: str) -> str:
    """Decode a possibly MIME-encoded header (=?UTF-8?...?=) to plain text."""
    if not value:
        return ""
    out = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(enc or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _sender_name(from_header: str) -> str:
    """'Priya Sharma <priya@x.com>' → 'Priya Sharma'; bare address → local part."""
    name = re.sub(r"\s*<[^>]+>\s*", "", from_header).strip().strip('"')
    if name:
        return name
    m = re.search(r"([^@<\s]+)@", from_header)
    return m.group(1) if m else (from_header or "someone")


def _fetch(gmail_query: str, limit: int) -> tuple[int, list[dict]]:
    """Run a Gmail X-GM-RAW search read-only. Returns (total_matches, mails),
    where mails is the newest `limit` as dicts {id (Message-ID), sender,
    subject}. total_matches is the true count (search returns all ids for free),
    so a summary can say "23 unread" while only reading the latest few. Raises on
    failure."""
    creds = _creds()
    if creds is None:
        raise RuntimeError("no-credentials")
    user, pw = creds

    imap = imaplib.IMAP4_SSL(_IMAP_HOST)
    try:
        imap.login(user, pw)
        imap.select("INBOX", readonly=True)
        typ, data = imap.uid("SEARCH", "X-GM-RAW", f'"{gmail_query}"')
        if typ != "OK" or not data or not data[0]:
            return 0, []
        all_uids = data[0].split()
        total = len(all_uids)
        uids = all_uids[-limit:]  # newest are last
        out = []
        for uid in reversed(uids):
            typ, msg_data = imap.uid(
                "FETCH", uid,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])",
            )
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            out.append({
                "id": (msg.get("Message-ID") or _decode(msg.get("Subject", ""))).strip(),
                "sender": _sender_name(_decode(msg.get("From", ""))),
                "subject": _decode(msg.get("Subject", "")) or "(no subject)",
            })
        return total, out
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def fetch_matching_emails(gmail_query: str, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Monitor-facing fetcher: matching messages, or [] on any error (a flaky
    poll must never crash the scheduler)."""
    try:
        _total, mails = _fetch(gmail_query, limit)
        return mails
    except Exception:
        return []


def _format_emails(total: int, emails: list[dict], label: str) -> str:
    label = label or "unread"
    if total == 0 or not emails:
        return f"No {label} emails, Sir."
    noun = "email" if total == 1 else "emails"
    shown = emails[:5]
    lines = [f"from {e['sender']}, {e['subject']}" for e in shown]
    lead = (f"You have {total} {label} {noun}, Sir. "
            + ("Here are the latest. " if total > len(shown) else ""))
    return lead + ". ".join(lines) + "."


def read_email(filter: str = "") -> str:
    """Read the user's Gmail for a filter ('unread', 'from priya', 'important
    today', 'starred') and return a spoken-ready summary. Read-only."""
    if _creds() is None:
        return ("I don't have your Gmail credentials yet, Sir. Add GMAIL_USER and "
                "GMAIL_APP_PASSWORD to the backend .env, using a Google app password.")
    gmail_query, label = _to_gmail_query(filter)
    try:
        total, emails = _fetch(gmail_query, _DEFAULT_LIMIT)
    except Exception as e:
        return f"I couldn't reach your inbox, Sir: {e}"
    return _format_emails(total, emails, label)
