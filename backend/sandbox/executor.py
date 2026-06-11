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

# Git subcommands that are always safe — read-only operations
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
}

# Git subcommands that need confirmation — write operations
RISKY_GIT_SUBCOMMANDS = {
    "add",
    "commit",
    "push",
    "pull",
    "merge",
    "rebase",
    "reset",
    "checkout",
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

    # If -C flag specified, git handles path itself
    if "git -C" in command:
        return WORKSPACE_DIR

    # ls ~/Projects should run from home
    if "ls" in command and "Projects" in command:
        return str(Path.home())

    # All other git commands run from ~/Projects
    if command.strip().startswith("git"):
        return str(projects_dir)

    # Commands mentioning a specific project — run from that project
    if projects_dir.exists():
        for project in projects_dir.iterdir():
            if project.is_dir() and project.name.lower() in command.lower():
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

    # Hard blocks first
    if has_shell_metacharacters(command):
        return "DANGEROUS"

    if contains_dangerous_pattern(command):
        return "DANGEROUS"

    if contains_sensitive_path(command):
        return "DANGEROUS"

    if executable in BLOCKED_COMMANDS:
        return "DANGEROUS"

    # Git gets special handling — subcommand aware
    if executable == "git":
        # Find the git subcommand — skip flags and -C path args
        subcommand = None
        i = 1
        while i < len(parts):
            if parts[i] == "-C" and i + 1 < len(parts):
                i += 2  # skip -C and its path argument
                continue
            if not parts[i].startswith("-"):
                subcommand = parts[i]
                break
            i += 1

        if subcommand in SAFE_GIT_SUBCOMMANDS:
            return "SAFE"
        if subcommand in RISKY_GIT_SUBCOMMANDS:
            return "RISKY"
        return "RISKY"  # unknown git subcommand — ask

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
    # Expand ~ in each token individually
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
