import subprocess
import shlex
import ollama
import logging
from pathlib import Path
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

WORKSPACE_DIR = str(Path.home() / "FRIDAY" / "workspace")
Path(WORKSPACE_DIR).mkdir(parents=True, exist_ok=True)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    filename=str(Path.home() / "FRIDAY" / "friday.log"),
    level=logging.INFO,
    format="%(asctime)s | %(message)s"
)

def log(command: str, classification: str, result: str):
    logging.info(f"CMD: {command} | CLASS: {classification} | RESULT: {result[:100]}")

# =========================================================
# SHELL METACHARACTERS
# =========================================================

SHELL_METACHARACTERS = [
    "&&", "||", ";", "|", ">", ">>",
    "<", "`", "$(", "\n"
]

# =========================================================
# SENSITIVE PATHS
# =========================================================

SENSITIVE_PATHS = [
    ".ssh", ".aws", ".gnupg", ".env",
    "Keychains", ".zsh_history", ".bash_history",
    ".netrc", ".git-credentials"
]

# =========================================================
# COMMAND SETS
# =========================================================

SAFE_COMMANDS = {
    "ls", "pwd", "cat", "echo",
    "git", "which", "whoami", "date",
}

RISKY_COMMANDS = {
    "mkdir", "touch", "mv", "cp",
    "open", "python3", "node",
}

BLOCKED_COMMANDS = {
    "rm", "sudo", "mkfs", "dd", "shutdown",
    "reboot", "chmod", "chown", "kill", "pkill",
    "curl", "wget", "bash", "sh", "zsh", "fish",
    "npm", "pip", "osascript", "diskutil",
    "launchctl", "find",
}

DANGEROUS_PATTERNS = [
    "rm -rf", ":(){:|:&};:",
    "/dev/sda", "/dev/disk",
    "mkfs", "dd if=",
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

# =========================================================
# CLASSIFIER
# =========================================================

def classify_command(command: str) -> str:
    parts = parse_command(command)

    if not parts:
        return "INVALID"

    executable = parts[0]

    # hard blocks first
    if has_shell_metacharacters(command):
        return "DANGEROUS"

    if contains_dangerous_pattern(command):
        return "DANGEROUS"

    if contains_sensitive_path(command):
        return "DANGEROUS"

    if executable in BLOCKED_COMMANDS:
        return "DANGEROUS"

    if executable in SAFE_COMMANDS:
        return "SAFE"

    if executable in RISKY_COMMANDS:
        return "RISKY"

    # unknown commands — default RISKY, never auto-execute
    return "RISKY"

# =========================================================
# EXECUTION
# =========================================================

def execute(command: str) -> str:
    try:
        result = subprocess.run(
            shlex.split(command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=WORKSPACE_DIR,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        if output:
            return output
        if error:
            return error
        return "Command executed successfully."
    except subprocess.TimeoutExpired:
        return "Command timed out after 10 seconds."
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

    # SAFE — execute
    result = execute(command)
    log(command, verdict, result)
    return result

# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":
    while True:
        cmd = input("FRIDAY > ")
        if cmd.lower() in {"exit", "quit"}:
            break
        print(run(cmd))