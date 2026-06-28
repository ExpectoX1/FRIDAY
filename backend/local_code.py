"""Deterministic local-code review/explanation path for FRIDAY.

The general agent is good at broad tool use, but local code review needs a few
hard guarantees: resolve the real project on disk, read real source files, then
answer from those contents only. This module handles that path before the agent
loop gets a chance to guess from folder names, memory, or web search.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECTS_DIR = Path.home() / "Projects"
MAX_FILES = 4
MAX_CHARS_PER_FILE = 8000
MAX_TOTAL_CHARS = 18000

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".go", ".rs", ".java",
    ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php",
}
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules", "dist", "build"}

_SESSION_PROJECT: Optional[Path] = None
_SESSION_FILES: list[Path] = []

LOCAL_CODE_ROUTER = os.getenv("FRIDAY_LOCAL_CODE_ROUTER", "1") == "1"
ASSISTANT_WAKE_WORDS = {"friday"}
GENERIC_LOCATION_TERMS = (
    "download folder", "downloads folder", "download directory", "downloads directory",
    "desktop folder", "desktop directory", "documents folder", "documents directory",
    "home folder", "home directory",
)


@dataclass
class CodeReviewRequest:
    project: Path
    files: list[Path]
    question: str
    mode: str  # explain | review


@dataclass
class CodeReviewResult:
    project: Path
    files: list[Path]
    answer: str


@dataclass
class LocalCodeIntent:
    is_local_code: bool
    project_hint: str = ""
    file_hint: str = ""
    task: str = "explain"  # explain | review
    use_session_project: bool = False


def _words(text: str) -> list[str]:
    cleaned = text.lower()
    replacements = {
        "u.r.": "url",
        "u r": "url",
        "urr": "url",
        "earl": "url",
        "oral": "url",
        "you are": "url",
        "p y": "py",
        "p by": "py",
        "pie": "py",
        "read me": "readme",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return re.findall(r"[a-z0-9]+", cleaned)


def _compact(text: str) -> str:
    return "".join(_words(text))


def _is_mutation_request(text: str) -> bool:
    lower = text.lower()
    mutation_terms = (
        "write ", "create ", "make ", "add ", "edit ", "change ", "modify ",
        "delete ", "remove ", "fix ", "implement ", "generate ", "refactor ",
        "run the test", "run tests", "test file", "testing of",
    )
    return any(term in lower for term in mutation_terms)


def _is_abstract_idea_request(text: str) -> bool:
    lower = text.lower()
    idea_terms = ("project idea", "app idea", "startup idea", "product idea")
    return any(term in lower for term in idea_terms)


def _is_generic_folder_request(text: str) -> bool:
    lower = text.lower()
    if any(term in lower for term in GENERIC_LOCATION_TERMS):
        return True
    list_terms = ("list", "list out", "show me", "what is in", "what's in", "whatever is in")
    generic_folder_terms = ("folder", "directory", "downloads", "download", "desktop", "documents")
    return any(term in lower for term in list_terms) and any(term in lower for term in generic_folder_terms)


def _session_followup_intent(text: str) -> bool:
    lower = text.lower()
    followup_terms = ("this code", "it", "that file", "main file")
    intent_terms = (
        "review", "audit", "feedback", "what does", "what do", "explain",
        "check", "look at", "look into", "written well", "is it written",
        "opinion", "recommendation", "suggestion", "thoughts on",
        "think about", "look clean", "looks clean", "written nicely",
    )
    return bool(_SESSION_PROJECT and any(term in lower for term in followup_terms)
                and any(term in lower for term in intent_terms))


def _is_local_code_intent(text: str) -> bool:
    lower = text.lower()
    if (_is_mutation_request(text) or _is_generic_folder_request(text)
            or _is_abstract_idea_request(text)):
        return False

    code_terms = (
        "code", "project", "repo", "repository", "app", "codebase",
        "main dot", "main.py", "database", "read me", "readme",
    )
    intent_terms = (
        "review", "audit", "feedback", "what does", "what do", "explain",
        "check", "look at", "look into", "find", "find out", "locate",
        "written well", "is it written", "code base", "codebase",
        "main dot", "opinion", "recommendation", "suggestion",
        "thoughts on", "think about", "look clean", "looks clean",
        "written nicely",
    )
    if any(term in lower for term in code_terms) and any(term in lower for term in intent_terms):
        return True
    return _session_followup_intent(text)


def _task_from_text(text: str) -> str:
    lower = text.lower()
    review_terms = (
        "review", "audit", "feedback", "written", "better", "opinion",
        "recommendation", "suggestion", "think about", "thoughts on",
        "look clean", "looks clean", "written nicely",
    )
    return "review" if any(term in lower for term in review_terms) else "explain"


def _extract_project_hint(text: str) -> str:
    """Pull out the likely spoken project name when the user introduces it.

    The resolver still checks the real ~/Projects folders. This just keeps the
    matching focused, especially for sentences like "one of my projects called
    teeny URL" where matching against the whole sentence is noisier.
    """
    patterns = (
        r"(?:project|repo|repository|folder|directory|app)\s+(?:called|named)\s+(.+)$",
        r"(?:called|named)\s+(.+)$",
        r"(?:project|repo|repository|folder|directory|app)\s+(?:is|it's|its)\s+(.+)$",
        r"(?:find(?: out)?|locate|review|audit|check(?: out)?|explain|open)\s+(?:the\s+)?(.+?)\s+(?:project|repo|repository|folder|directory|app)\b",
        r"(?:the|my)\s+(.+?)\s+(?:project|repo|repository|folder|directory|app)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        hint = re.split(r"\b(?:and|then|where|which|that|to|for|in that)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
        return hint.strip(" .,'\"")
    return ""


def _heuristic_intent(text: str) -> Optional[LocalCodeIntent]:
    if (_is_mutation_request(text) or _is_generic_folder_request(text)
            or _is_abstract_idea_request(text)):
        return None
    if not _is_local_code_intent(text):
        return None
    return LocalCodeIntent(
        is_local_code=True,
        project_hint=_extract_project_hint(text),
        file_hint=_spoken_filename(text) or "",
        task=_task_from_text(text),
        use_session_project=_session_followup_intent(text),
    )


def _looks_code_adjacent(text: str) -> bool:
    if (_is_mutation_request(text) or _is_generic_folder_request(text)
            or _is_abstract_idea_request(text)):
        return False
    lower = text.lower()
    signals = (
        "project", "repo", "repository", "code", "codebase",
        "main dot", "main.py", "readme", "read me",
        "audit", "review",
    )
    followups = ("this", "it", "that", "main")
    return any(s in lower for s in signals) or bool(_SESSION_PROJECT and any(s in lower for s in followups))


def _router_intent(text: str) -> Optional[LocalCodeIntent]:
    """Structured fallback for natural phrasing the cheap checks miss.

    This is deliberately narrow: it only runs for code-adjacent utterances, and
    even a positive result still has to resolve to a real local project before
    FRIDAY handles the turn.
    """
    if (_is_mutation_request(text) or _is_generic_folder_request(text)
            or _is_abstract_idea_request(text)
            or not LOCAL_CODE_ROUTER or not _looks_code_adjacent(text)):
        return None

    try:
        import ollama
        from brain.llm import KEEP_ALIVE, ROUTER_MODEL

        response = ollama.chat(
            model=ROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify whether the user is asking to review or explain "
                        "local code on this Mac. Return local_code only when they "
                        "want an existing project, repo, folder, directory, file, "
                        "or codebase inspected. Do not classify abstract project "
                        "ideas, web searches, git tasks, or general chat as local_code."
                    ),
                },
                {"role": "user", "content": text},
            ],
            format={
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "enum": ["local_code", "other"]},
                    "project_hint": {"type": "string"},
                    "file_hint": {"type": "string"},
                    "task": {"type": "string", "enum": ["explain", "review"]},
                },
                "required": ["intent", "project_hint", "file_hint", "task"],
            },
            keep_alive=KEEP_ALIVE,
            think=False,
        )
        data = json.loads(response.message.content.strip())
    except Exception:
        return None

    if data.get("intent") != "local_code":
        return None
    if (_is_mutation_request(text) or _is_generic_folder_request(text)
            or _is_abstract_idea_request(text)):
        return None
    return LocalCodeIntent(
        is_local_code=True,
        project_hint=str(data.get("project_hint") or "").strip(),
        file_hint=str(data.get("file_hint") or "").strip(),
        task=data.get("task") if data.get("task") in {"explain", "review"} else _task_from_text(text),
        use_session_project=_session_followup_intent(text),
    )


def _project_dirs() -> list[Path]:
    try:
        return sorted([p for p in PROJECTS_DIR.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
    except Exception:
        return []


def _best_project(text: str, hint: str = "", allow_session: bool = False) -> Optional[Path]:
    global _SESSION_PROJECT
    projects = _project_dirs()
    if not projects:
        return None

    match_text = hint.strip() or text
    text_compact = _compact(match_text)
    tokens = [t for t in _words(match_text) if t not in ASSISTANT_WAKE_WORDS]
    token_compacts = ["".join(tokens[i:i + size])
                      for size in range(1, min(4, len(tokens)) + 1)
                      for i in range(0, len(tokens) - size + 1)]
    best: tuple[float, Path] | None = None
    for project in projects:
        name = _compact(project.name)
        if not name:
            continue
        if name in text_compact:
            score = 1.0
        else:
            score = difflib.SequenceMatcher(None, name, text_compact).ratio()
            for phrase in token_compacts:
                score = max(score, difflib.SequenceMatcher(None, name, phrase).ratio())
        if best is None or score > best[0]:
            best = (score, project)

    if best and best[0] >= 0.72:
        _SESSION_PROJECT = best[1]
        return best[1]
    if allow_session and _SESSION_PROJECT and _SESSION_PROJECT.exists():
        return _SESSION_PROJECT
    return None


def _spoken_filename(text: str) -> Optional[str]:
    compact = _compact(text)
    if "maindotpy" in compact or "mainpy" in compact:
        return "main.py"
    if "databasedotpy" in compact or "databasepy" in compact:
        return "database.py"
    if "cachedotpy" in compact or "cachepy" in compact or "cashpy" in compact:
        return "cache.py"
    if "readmemd" in compact or "readmedotmd" in compact:
        return "README.md"

    match = re.search(r"\b([a-zA-Z0-9_-]+)\.(py|js|ts|tsx|jsx|swift|go|rs|java|md)\b", text)
    if match:
        return match.group(0)
    return None


def _source_files(project: Path) -> list[Path]:
    files: list[Path] = []
    try:
        for item in sorted(project.iterdir(), key=lambda p: p.name.lower()):
            if item.name in SKIP_DIRS or item.name.startswith("."):
                continue
            if item.is_file() and item.suffix.lower() in CODE_EXTENSIONS:
                files.append(item)
    except Exception:
        return []

    files.sort(key=lambda p: (0 if p.name == "main.py" else 1, p.name.lower()))
    return files


def _resolve_files(project: Path, text: str, hint: str = "") -> list[Path]:
    global _SESSION_FILES
    wanted = _spoken_filename(f"{hint} {text}".strip())
    if wanted:
        direct = project / wanted
        if direct.exists() and direct.is_file():
            _SESSION_FILES = [direct]
            return [direct]
        candidates = _source_files(project) + [project / "README.md"]
        close = difflib.get_close_matches(wanted.lower(), [p.name.lower() for p in candidates], n=1, cutoff=0.72)
        if close:
            chosen = next(p for p in candidates if p.name.lower() == close[0])
            _SESSION_FILES = [chosen]
            return [chosen]

    if _SESSION_FILES and any(term in text.lower() for term in ("this code", "that file", "main file", "it")):
        existing = [p for p in _SESSION_FILES if p.exists()]
        if existing:
            return existing

    selected = _source_files(project)[:MAX_FILES]
    if not selected:
        readme = project / "README.md"
        selected = [readme] if readme.exists() else []
    _SESSION_FILES = selected
    return selected


def _read_files(files: list[Path]) -> list[tuple[Path, str]]:
    remaining = MAX_TOTAL_CHARS
    out: list[tuple[Path, str]] = []
    for path in files:
        if remaining <= 0:
            break
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        limit = min(MAX_CHARS_PER_FILE, remaining)
        if len(text) > limit:
            text = text[:limit] + "\n... [truncated]"
        remaining -= len(text)
        out.append((path, text))
    return out


def prepare_code_review(text: str) -> Optional[CodeReviewRequest]:
    intent = _heuristic_intent(text) or _router_intent(text)
    if intent is None or not intent.is_local_code:
        return None

    project = _best_project(text, intent.project_hint, allow_session=intent.use_session_project)
    if project is None:
        return None

    files = _resolve_files(project, text, intent.file_hint)
    code_files = [p for p in files if p.suffix.lower() in CODE_EXTENSIONS]
    if code_files:
        files = code_files

    if not files:
        return CodeReviewRequest(project=project, files=[], question=text, mode=intent.task)

    return CodeReviewRequest(project=project, files=files, question=text, mode=intent.task)


def answer_code_review(request: CodeReviewRequest) -> CodeReviewResult:
    read = _read_files(request.files)
    if not read:
        answer = f"I found the project {request.project.name}, but I couldn't read any relevant code files."
        return CodeReviewResult(project=request.project, files=[], answer=answer)

    file_blocks = []
    for path, content in read:
        file_blocks.append(f"FILE: {path}\n{content}")

    if request.mode == "review":
        task = (
            "Explain what this local code actually does, then give 2 or 3 concrete "
            "code-quality suggestions grounded in the code. Do not mention web "
            "search, repositories, git status, or memory."
        )
    else:
        task = (
            "Explain what this local code actually does in plain spoken English. "
            "Mention the real endpoints/functions/logic you see. Do not guess from "
            "the project name, and do not mention web search, repositories, git "
            "status, or memory."
        )

    prompt = (
        "You are FRIDAY, a voice-first local coding assistant. Reply in concise, "
        "natural spoken English. No markdown headings, no bullets, no code fences.\n\n"
        f"User asked: {request.question}\n\n"
        f"Project: {request.project}\n\n"
        f"{task}\n\n"
        "Local files actually read:\n\n"
        + "\n\n---\n\n".join(file_blocks)
    )

    try:
        import ollama
        from brain.llm import MODEL, KEEP_ALIVE

        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE,
            think=False,
        )
        answer = (response.message.content or "").strip()
    except Exception as exc:
        answer = f"I read {', '.join(p.name for p, _ in read)}, but the local model failed while summarizing it: {exc}"

    return CodeReviewResult(project=request.project, files=[p for p, _ in read], answer=answer)
