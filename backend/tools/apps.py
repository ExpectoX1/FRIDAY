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

# Common aliases — maps what the LLM might say to the real macOS app name
APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "firefox": "Firefox",
    "safari": "Safari",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "cursor": "Cursor",
    "terminal": "Terminal",
    "spotify": "Spotify",
    "slack": "Slack",
    "notion": "Notion",
    "notes": "Notes",
    "finder": "Finder",
    "xcode": "Xcode",
    "figma": "Figma",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "zoom": "Zoom",
    "mail": "Mail",
    "calendar": "Calendar",
    "messages": "Messages",
    "photos": "Photos",
    "music": "Music",
}


def _normalize_app_name(name: str) -> str:
    return APP_ALIASES.get(name.lower().strip(), name)


def open_app(name: str) -> dict:
    normalized = _normalize_app_name(name)
    try:
        check = subprocess.run(
            ["pgrep", "-x", normalized], capture_output=True, text=True
        )
        subprocess.run(["open", "-a", normalized])
        already_open = check.returncode == 0
        msg = random.choice(ALREADY_OPEN_RESPONSES if already_open else OPEN_RESPONSES)
        return {"status": "success", "message": msg}
    except Exception as e:
        return {"status": "error", "message": f"Failed to open {normalized}: {e}"}


def close_app(name: str) -> dict:
    normalized = _normalize_app_name(name)
    try:
        result = subprocess.run(
            ["pkill", "-x", normalized], capture_output=True, text=True
        )
        if result.returncode == 0:
            return {"status": "success", "message": random.choice(CLOSE_RESPONSES)}
        return {"status": "error", "message": random.choice(NOT_RUNNING_RESPONSES)}
    except Exception as e:
        return {"status": "error", "message": f"Failed to close {normalized}: {e}"}
