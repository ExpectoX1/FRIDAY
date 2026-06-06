import subprocess
import random

OPEN_RESPONSES = [
    "On it Sir.",
    "Done.",
    "Already on it Boss.",
    "Opening now.",
    "Consider it done Sir.",
]

ALREADY_OPEN_RESPONSES = [
    "Already running Sir, brought it up.",
    "It's already open Boss.",
    "Already up, brought it to focus.",
]

CLOSE_RESPONSES = [
    "Done Sir.",
    "Closed.",
    "Gone Boss.",
    "Consider it closed Sir.",
]

NOT_RUNNING_RESPONSES = [
    "Doesn't seem to be running Sir.",
    "Not open Boss.",
    "Nothing to close Sir.",
]


def open_app(name: str) -> str:
    try:
        check = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True)
        subprocess.run(["open", "-a", name])
        if check.returncode == 0:
            return random.choice(ALREADY_OPEN_RESPONSES)
        return random.choice(OPEN_RESPONSES)
    except Exception as e:
        return f"Failed to open {name}: {e}"


def close_app(name: str) -> str:
    try:
        result = subprocess.run(["pkill", "-x", name], capture_output=True, text=True)
        if result.returncode == 0:
            return random.choice(CLOSE_RESPONSES)
        return random.choice(NOT_RUNNING_RESPONSES)
    except Exception as e:
        return f"Failed to close {name}: {e}"
