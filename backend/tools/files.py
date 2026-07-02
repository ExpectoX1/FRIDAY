from pathlib import Path

# Locations write_file must never touch. run_shell is gated the same way
# (sandbox.executor.SENSITIVE_PATHS), but write_file needs its own gate: a
# write can BE the payload (~/.zshrc, a LaunchAgent plist that runs at login)
# even though executing a script later is confirmation-gated. Matching is by
# exact path component / filename — never substring — so e.g. a project file
# named "environment.py" is not caught by ".env".

# Directory components that mark a path as protected wherever they appear.
_PROTECTED_DIRS = {
    ".ssh", ".aws", ".gnupg", "Keychains", "LaunchAgents", "LaunchDaemons",
}

# Exact filenames that are protected (shell startup files, credentials).
_PROTECTED_FILES = {
    ".env", ".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile",
    ".profile", ".netrc", ".git-credentials", ".zsh_history", ".bash_history",
}

# Absolute prefixes for system locations no assistant write should land in.
_PROTECTED_PREFIXES = (
    "/etc/", "/System/", "/usr/", "/bin/", "/sbin/", "/Library/", "/private/etc/",
)


def _is_protected_write(path: str) -> bool:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except Exception:
        pass  # judge the unresolved path if resolution fails
    if any(part in _PROTECTED_DIRS for part in p.parts):
        return True
    if p.name in _PROTECTED_FILES or p.name.startswith(".env."):
        return True
    return str(p).startswith(_PROTECTED_PREFIXES)


def read_file(path: str) -> str:
    try:
        file_path = Path(path).expanduser()
        if not file_path.exists():
            return f"File not found: {path}"
        return file_path.read_text()
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    if _is_protected_write(path):
        # "Blocked:" prefix so the agent's _tool_failed treats this as a real
        # failure and course-corrects instead of claiming the goal is done.
        return (
            f"Blocked: {path} is a protected location (credentials, shell "
            "startup files, launch agents, or system paths). I won't write "
            "there — the user must change that file themselves."
        )
    try:
        file_path = Path(path).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"
