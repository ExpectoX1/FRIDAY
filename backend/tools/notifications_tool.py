"""Read macOS Notification Center — the safe, app-agnostic way to surface
incoming messages (WhatsApp, Instagram, …) without touching any app's API.

Why this approach: Instagram/WhatsApp have no clean, ToS-safe local API. But
every app that notifies you writes to the local Notification Center SQLite
(group.com.apple.usernoted/db2/db). Reading THAT is local, breaks no ToS, and
risks no account — we just see what already popped up on your Mac.

Each row's `data` column is a binary plist:
  {app: <bundle>, req: {titl: <title/sender>, subt: <subtitle/site>,
                        body: <preview>, iden: <id>}, date: <apple epoch>}
Web-push (Chrome/Safari) carries the originating site in `subt`/`iden`, so
matching across bundle+subt+iden+title catches both native apps and web pushes.

Requires Full Disk Access for the process running FRIDAY. Leaf module (no
proactive/registry imports) so the monitor can import it without a cycle.
"""
from __future__ import annotations

import os
import plistlib
import sqlite3

_DB = os.path.expanduser("~/Library/Group Containers/group.com.apple.usernoted/db2/db")

# Sensible default "messaging" sources when the user doesn't name any.
DEFAULT_SOURCES = ["whatsapp", "instagram", "messenger", "telegram", "signal", "imessage"]


def available() -> bool:
    return os.path.exists(_DB)


def _connect():
    return sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)


def _as_text(v) -> str:
    """Coerce a notification field to plain text. Some fields come back as lists
    (e.g. a multi-part body) or non-strings, so we can't assume str."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return " ".join(_as_text(x) for x in v if x is not None).strip()
    return str(v).strip()


def _extract(decoded: dict, bundle: str) -> dict:
    """Pull the fields we care about out of a decoded notification plist."""
    req = decoded.get("req") or {}
    return {
        "bundle": _as_text(bundle or decoded.get("app")),
        "title": _as_text(req.get("titl")),
        "subtitle": _as_text(req.get("subt")),
        "body": _as_text(req.get("body")),
        "iden": _as_text(req.get("iden")),
    }


def _parse_sources(sources: str | list | None) -> list[str]:
    if isinstance(sources, list):
        items = sources
    else:
        items = [s for s in (sources or "").replace(",", " ").split()]
    items = [s.strip().lower() for s in items if s.strip()]
    return items or list(DEFAULT_SOURCES)


def matches(n: dict, sources: list[str]) -> bool:
    hay = " ".join([n.get("bundle", ""), n.get("subtitle", ""),
                    n.get("iden", ""), n.get("title", "")]).lower()
    return any(s in hay for s in sources)


def source_label(n: dict, sources: list[str]) -> str:
    """Which watched source this notification came from, nicely cased."""
    hay = " ".join([n.get("bundle", ""), n.get("subtitle", ""),
                    n.get("iden", ""), n.get("title", "")]).lower()
    for s in sources:
        if s in hay:
            return {"whatsapp": "WhatsApp", "instagram": "Instagram",
                    "imessage": "iMessage"}.get(s, s.capitalize())
    return "new"


def current_max_rec_id() -> int:
    if not available():
        return 0
    try:
        con = _connect()
        row = con.execute("SELECT MAX(CAST(rec_id AS INTEGER)) FROM record").fetchone()
        con.close()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def fetch_new(after_rec_id: int, limit: int = 40) -> tuple[int, list[dict]]:
    """(max_rec_id_seen, new notifications with rec_id > after_rec_id), oldest
    first. Best-effort: returns (after_rec_id, []) on any failure (no Full Disk
    Access, schema change, decode error)."""
    if not available():
        return after_rec_id, []
    try:
        con = _connect()
    except Exception:
        return after_rec_id, []
    out, max_id = [], after_rec_id
    try:
        cur = con.execute(
            "SELECT CAST(r.rec_id AS INTEGER) AS rid, a.identifier, r.data "
            "FROM record r LEFT JOIN app a ON a.app_id = r.app_id "
            "WHERE CAST(r.rec_id AS INTEGER) > ? AND r.data IS NOT NULL "
            "ORDER BY rid LIMIT ?",
            (after_rec_id, limit),
        )
        for rid, bundle, blob in cur:
            max_id = max(max_id, int(rid))
            try:
                decoded = plistlib.loads(bytes(blob))
            except Exception:
                continue
            n = _extract(decoded, bundle or "")
            n["rec_id"] = int(rid)
            if n["title"] or n["body"]:
                out.append(n)
    except Exception:
        return after_rec_id, []
    finally:
        con.close()
    return max_id, out


def _recent_matching(sources: list[str], scan: int = 80, take: int = 5) -> list[dict]:
    """Most recent notifications matching `sources`, newest first."""
    if not available():
        return []
    try:
        con = _connect()
        cur = con.execute(
            "SELECT a.identifier, r.data FROM record r "
            "LEFT JOIN app a ON a.app_id = r.app_id "
            "WHERE r.data IS NOT NULL ORDER BY CAST(r.rec_id AS INTEGER) DESC LIMIT ?",
            (scan,),
        )
        hits = []
        for bundle, blob in cur:
            try:
                n = _extract(plistlib.loads(bytes(blob)), bundle or "")
            except Exception:
                continue
            if (n["title"] or n["body"]) and matches(n, sources):
                hits.append(n)
            if len(hits) >= take:
                break
        con.close()
        return hits
    except Exception:
        return []


def check_messages(sources: str = "") -> str:
    """Reactive read: recent messages/notifications from the given sources
    ('whatsapp', 'instagram', or empty for the messaging defaults)."""
    if not available():
        return "I can't see your notifications, Sir — I need Full Disk Access for that."
    src = _parse_sources(sources)
    hits = _recent_matching(src)
    if not hits:
        return f"No recent {' or '.join(src[:3])} messages, Sir."
    lines = []
    for n in hits:
        who = n["title"] or source_label(n, src)
        lines.append(f"from {who}, {n['body']}" if n["body"] else f"from {who}")
    return "Recent messages, Sir: " + ". ".join(lines) + "."
