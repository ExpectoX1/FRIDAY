import subprocess
import shlex
import os
from pathlib import Path
from logger import log_system

# =========================================================
# CONFIG
# =========================================================

WORKSPACE_DIR = str(Path.home() / "FRIDAY" / "workspace")
Path(WORKSPACE_DIR).mkdir(parents=True, exist_ok=True)

FRIDAY_PROJECT_DIR = str(Path.home() / "Projects" / "FRIDAY")


def log(command: str, classification: str, result: str):
    log_system(
        "executor", f"CMD: {command} | CLASS: {classification} | RESULT: {result}"
    )


# =========================================================
# SHELL METACHARACTERS
# =========================================================

SHELL_METACHARACTERS = ["&&", "||", ";", "|", ">", ">>", "<", "`", "$(", "\n"]

# =========================================================
# SENSITIVE PATHS
# =========================================================

SENSITIVE_PATHS = [
    ".ssh",
    ".aws",
    ".gnupg",
    ".env",
    "Keychains",
    ".zsh_history",
    ".bash_history",
    ".netrc",
    ".git-credentials",
]

# =========================================================
# COMMAND SETS
# =========================================================

SAFE_COMMANDS = {
    "ls",
    "pwd",
    "cat",
    "echo",
    "git",
    "which",
    "whoami",
    "date",
}

# ⚡ PERFORMANCE OPTIMIZED: Local mutations are now SAFE.
# This prevents the LLM from halting execution to ask for permission on local saves.
# Only remote or destructive state mutations remain RISKY.
SAFE_GIT_SUBCOMMANDS = {
    "log",
    "status",
    "diff",
    "show",
    "branch",
    "remote",
    "fetch",
    "stash",
    "tag",
    "describe",
    "rev-parse",
    "add",  # Safe: Only staging files locally
    "commit",  # Safe: Only creating a local checkpoint
}

RISKY_GIT_SUBCOMMANDS = {
    "push",  # Risky: Modifies remote repositories
    "pull",  # Risky: Fetches and merges remote data into local HEAD
    "merge",  # Risky: Can introduce merge conflicts
    "rebase",  # Risky: Rewrites commit history
    "reset",  # Risky: Can destroy local changes
    "checkout",  # Risky: Can overwrite untracked local modifications
    "switch",
    "restore",
}

RISKY_COMMANDS = {
    "mkdir",
    "touch",
    "mv",
    "cp",
    "open",
    "python3",
    "node",
    "osascript",
}

BLOCKED_COMMANDS = {
    "rm",
    "sudo",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "chmod",
    "chown",
    "kill",
    "pkill",
    "curl",
    "wget",
    "bash",
    "sh",
    "zsh",
    "fish",
    "npm",
    "pip",
    "diskutil",
    "launchctl",
    "find",
}

DANGEROUS_PATTERNS = [
    "rm -rf",
    ":(){:|:&};:",
    "/dev/sda",
    "/dev/disk",
    "mkfs",
    "dd if=",
]


# =========================================================
# VALIDATION
# =========================================================


def has_shell_metacharacters(command: str) -> bool:
    return any(char in command for char in SHELL_METACHARACTERS)


def contains_sensitive_path(command: str) -> bool:
    return any(path in command for path in SENSITIVE_PATHS)


def contains_dangerous_pattern(command: str) -> bool:
    return any(pattern in command.lower() for pattern in DANGEROUS_PATTERNS)


def parse_command(command: str):
    try:
        return shlex.split(command)
    except Exception:
        return None


def _resolve_working_dir(command: str) -> str:
    projects_dir = Path.home() / "Projects"

    # If -C flag specified, git handles internal paths cleanly from any directory root
    if "git -C" in command:
        return WORKSPACE_DIR

    if "ls" in command and "Projects" in command:
        return str(Path.home())

    if command.strip().startswith("git"):
        return str(projects_dir)

    if projects_dir.exists():
        for project in projects_dir.iterdir():
            if not project.is_dir():
                continue
            # Only switch into a project when its PATH is referenced (e.g.
            # "Projects/FRIDAY" or the absolute path) — NOT when the bare name
            # merely appears in the command ("echo FRIDAY" must stay in the
            # workspace, not cd into ~/Projects/FRIDAY).
            if str(project) in command or f"Projects/{project.name}" in command:
                return str(project)

    return WORKSPACE_DIR


# =========================================================
# CLASSIFIER
# =========================================================


def classify_command(command: str) -> str:
    parts = parse_command(command)

    if not parts:
        return "INVALID"

    executable = parts[0]

    if has_shell_metacharacters(command):
        return "DANGEROUS"

    if contains_dangerous_pattern(command):
        return "DANGEROUS"

    if contains_sensitive_path(command):
        return "DANGEROUS"

    if executable in BLOCKED_COMMANDS:
        return "DANGEROUS"

    if executable == "git":
        subcommand = None
        i = 1
        while i < len(parts):
            if parts[i] == "-C" and i + 1 < len(parts):
                i += 2
                continue
            if not parts[i].startswith("-"):
                subcommand = parts[i]
                break
            i += 1

        if subcommand in SAFE_GIT_SUBCOMMANDS:
            return "SAFE"
        if subcommand in RISKY_GIT_SUBCOMMANDS:
            return "RISKY"
        return "RISKY"

    if executable in SAFE_COMMANDS:
        return "SAFE"

    if executable in RISKY_COMMANDS:
        return "RISKY"

    return "RISKY"


# =========================================================
# EXECUTION
# =========================================================


def execute(command: str) -> str:
    working_dir = _resolve_working_dir(command)
    parts = shlex.split(command)
    expanded_parts = [os.path.expanduser(p) for p in parts]
    try:
        result = subprocess.run(
            expanded_parts,
            shell=False,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=working_dir,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        if output:
            return output
        if error:
            return error
        return "Command executed successfully."
    except subprocess.TimeoutExpired:
        return "Command timed out after 15 seconds."
    except Exception as e:
        return f"Execution error: {str(e)}"


# =========================================================
# MAIN ENTRY
# =========================================================


def run(command: str) -> str:
    verdict = classify_command(command)
    log(command, verdict, "")

    if verdict == "INVALID":
        return "Invalid command Boss, couldn't parse that."

    if verdict == "DANGEROUS":
        log(command, verdict, "BLOCKED")
        # Provide detailed feedback for the LLM to adapt dynamically
        if has_shell_metacharacters(command):
            used = [char for char in SHELL_METACHARACTERS if char in command]
            return f"BLOCKED: Command contains restricted shell metacharacters {used}. Chaining or piping commands is not allowed in run_shell. Write a Python script to do this and execute it via python3 instead."
        if contains_dangerous_pattern(command) or contains_sensitive_path(command):
            return "BLOCKED: Command contains sensitive paths or dangerous command patterns."
        parts = parse_command(command)
        if parts and parts[0] in BLOCKED_COMMANDS:
            return f"BLOCKED: The command '{parts[0]}' is restricted for safety."
        return "I can't run that Boss. That command is hard blocked. Run it yourself if you're sure."

    if verdict == "RISKY":
        log(command, verdict, "NEEDS_CONFIRMATION")
        return f"NEEDS_CONFIRMATION: {command}"

    result = execute(command)
    log(command, verdict, result)
    return result


if __name__ == "__main__":
    while True:
        cmd = input("FRIDAY > ")
        if cmd.lower() in {"exit", "quit"}:
            break
        print(run(cmd))
