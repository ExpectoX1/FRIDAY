"""Deterministic project-path resolution.

The agent kept fumbling project paths from speech — guessing
`/Users/siddharth/Projects/teenyURL` (wrong user, wrong case) instead of the real
`/Users/siddharthkumar/Projects/teenyurl`, then declaring the project missing.
find_project takes the brittle path-guessing out of the model's hands: it lists
the real ~/Projects folders and matches the (possibly misheard) name against
them, so the agent only has to decide WHAT to do, never invent WHERE it lives.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

PROJECTS_DIR = Path.home() / "Projects"


def _norm(s: str) -> str:
    """Collapse to comparable form: lowercase, drop spaces/hyphens/underscores
    ('teeny url', 'Teeny-URL', 'teeny_url' all -> 'teenyurl')."""
    return re.sub(r"[\s_\-]+", "", (s or "").strip().lower())


def find_project(project: str) -> dict:
    """Resolve a spoken/typed project name to its REAL folder under ~/Projects.

    Returns {status, path, name, message}. Use this before reading files or
    running git on a project — never guess the path."""
    if not PROJECTS_DIR.is_dir():
        return {"status": "error", "message": "I can't find a ~/Projects folder, Sir."}

    folders = [p for p in PROJECTS_DIR.iterdir()
               if p.is_dir() and not p.name.startswith(".")]
    if not folders:
        return {"status": "error", "message": "Your Projects folder is empty, Sir."}

    names = [p.name for p in folders]
    by_norm = {_norm(p.name): p for p in folders}
    want = _norm(project)

    # 1. exact (normalized) match
    if want in by_norm:
        p = by_norm[want]
        return {"status": "success", "path": str(p), "name": p.name,
                "message": f"Found project {p.name} at {p}."}

    # 2. substring either direction (handles "the teeny url one")
    for norm_name, p in by_norm.items():
        if want and (want in norm_name or norm_name in want):
            return {"status": "success", "path": str(p), "name": p.name,
                    "message": f"Found project {p.name} at {p}."}

    # 3. fuzzy match (handles STT garbling: "teeny oral" -> "teenyurl")
    close = difflib.get_close_matches(want, list(by_norm.keys()), n=1, cutoff=0.6)
    if close:
        p = by_norm[close[0]]
        return {"status": "success", "path": str(p), "name": p.name,
                "message": f"Found project {p.name} at {p}."}

    return {"status": "error",
            "message": f"No project matching '{project}' in ~/Projects. "
                       f"Available projects: {', '.join(sorted(names))}."}


_SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules", "dist", "build"}
_ENTRY_PREFERENCE = ("main.py", "app.py", "index.js", "main.js", "index.ts", "main.go", "README.md")
_MAX_FILE_CHARS = 18000


def _normalize_filename(name: str) -> str:
    # STT speaks "main dot p y" / "main dot py" for "main.py".
    name = re.sub(r"\s+dot\s+", ".", name.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", "", name)


def _find_file(base: Path, filename: str) -> Path | None:
    """Locate a file inside a project tree (exact, then fuzzy), skipping junk dirs."""
    files = [p for p in base.rglob("*")
             if p.is_file() and not any(d in p.parts for d in _SKIP_DIRS)]
    if not filename:
        for pref in _ENTRY_PREFERENCE:
            for p in files:
                if p.name.lower() == pref:
                    return p
        return None
    want = _normalize_filename(filename).lower()
    for p in files:                      # exact filename
        if p.name.lower() == want:
            return p
    close = difflib.get_close_matches(want, [p.name.lower() for p in files], n=1, cutoff=0.6)
    if close:
        return next(p for p in files if p.name.lower() == close[0])
    return None


def read_project_file(project: str, filename: str = "") -> str:
    """Resolve a project AND read one of its files in a single deterministic step
    — use this for 'what does <project>'s <file> do' / 'review <project>'s code'.
    Pass the project name and the file (e.g. 'main.py'); omit filename to read the
    project's main entry file. Returns the file's contents (with a path header) to
    reason over, or an 'Error:' line if the project or file can't be found."""
    proj = find_project(project)
    if proj["status"] != "success":
        return "Error: " + proj["message"]
    base = Path(proj["path"])
    target = _find_file(base, filename)
    if target is None:
        return f"Error: I couldn't find {filename or 'a main file'} in {proj['name']}, Sir."
    try:
        content = target.read_text(errors="replace")
    except Exception as e:
        return f"Error reading {target.name}: {e}"
    if len(content) > _MAX_FILE_CHARS:
        content = content[:_MAX_FILE_CHARS] + "\n... [truncated]"
    # Header so the model cites the real file it read.
    return f"File: {target} (project: {proj['name']})\n\n{content}"
