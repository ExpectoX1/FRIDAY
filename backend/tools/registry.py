from typing import TypedDict, Callable, Optional

from tools.web import search_web
from tools.shell import run_shell
from tools.files import read_file, write_file
from tools.apps import open_app, close_app
from tools.datetime_tool import get_date_time
from tools.media import play_media
from tools.mac_core import get_running_apps, take_screenshot
from memory.retrieve import search_memory


class Tool(TypedDict):
    description: str
    args: list[str]
    function: Optional[Callable]


def _navigate_browser(url: str) -> dict:
    """Wrapper that ensures URL has protocol prefix."""
    import subprocess

    if not url.startswith("http"):
        url = "https://" + url
    try:
        script = f'tell application "Google Chrome" to set URL of active tab of front window to "{url}"'
        subprocess.run(["osascript", "-e", script], check=True)
        return {"status": "success", "message": f"Navigated to {url}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


TOOLS: dict[str, Tool] = {
    "open_app": {
        "description": "Open or focus any app on this Mac. Use the full app name e.g. 'Google Chrome' not 'Chrome'. If unsure of the exact name, call get_running_apps first.",
        "args": ["name"],
        "function": open_app,
    },
    "close_app": {
        "description": "Close any app on this Mac by its full name.",
        "args": ["name"],
        "function": close_app,
    },
    "run_shell": {
        "description": "Run a terminal shell command. Use for file operations, git commands, system info. NOT for opening apps, NOT for browser navigation.",
        "args": ["command"],
        "function": run_shell,
    },
    "search_web": {
        "description": "Search the web for current information, news, facts.",
        "args": ["query"],
        "function": search_web,
    },
    "read_file": {
        "description": "Read the contents of a file at the given absolute path.",
        "args": ["path"],
        "function": read_file,
    },
    "write_file": {
        "description": "Write content to a file at the given absolute path.",
        "args": ["path", "content"],
        "function": write_file,
    },
    "get_date_time": {
        "description": "Returns the current date and time.",
        "args": [],
        "function": get_date_time,
    },
    "search_memory": {
        "description": "Search FRIDAY's long-term memory for facts about the user — people, places, projects, preferences, plans. Always use this before answering personal questions.",
        "args": ["query"],
        "function": search_memory,
    },
    "play_media": {
        "description": "Play a movie, show, song, or album in Netflix or Spotify. Use for 'watch X on Netflix' or 'play X on Spotify'.",
        "args": ["title", "service"],
        "function": play_media,
    },
    "navigate_browser": {
        "description": "Navigate Google Chrome to a URL. Use for 'go to X', 'open website X', 'navigate to X'. Always use this instead of run_shell for browser navigation.",
        "args": ["url"],
        "function": _navigate_browser,
    },
    "get_running_apps": {
        "description": "Returns all currently running apps on this Mac. Use this to find the exact app name before calling open_app or close_app.",
        "args": [],
        "function": get_running_apps,
    },
    "take_screenshot": {
        "description": "Takes a screenshot of the current screen and saves it. Use for visual verification or when you need to see what is on screen.",
        "args": [],
        "function": take_screenshot,
    },
}


def get_tools_prompt() -> str:
    s = "You have access to the following tools:\n"
    for name, tool in TOOLS.items():
        args = ", ".join(tool["args"])
        s += f"- {name}({args}): {tool['description']}\n"
    return s


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name, None)
