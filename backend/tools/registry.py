from typing import TypedDict, Callable, Optional

from tools.web import search_web, read_page
from tools.shell import run_shell
from tools.files import read_file, write_file
from tools.apps import open_app, close_app
from tools.datetime_tool import get_date_time
from tools.media import play_media
from tools.mac_core import get_running_apps, take_screenshot
from tools.vision import look_at_screen
from tools.reminders import set_reminder, set_timer, list_reminders, cancel_reminder
from tools.monitor import set_monitor
from tools.projects import find_project, read_project_file
from memory.retrieve import search_memory


class Tool(TypedDict):
    description: str
    args: list[str]
    function: Optional[Callable]


def _navigate_browser(url: str) -> dict:
    """Wrapper that ensures URL has protocol prefix."""
    import subprocess

    # Reject descriptions/placeholders — the model sometimes passes prose like
    # "Sky Sports article about X" instead of a real URL, which would open a
    # garbage page. A real URL has no spaces and contains a dot.
    candidate = (url or "").strip()
    if not candidate or " " in candidate or "." not in candidate:
        return {
            "status": "error",
            "message": (
                f"'{url}' is not a valid URL. Pass a real URL "
                "(e.g. https://www.skysports.com/football/news), not a description."
            ),
        }
    url = candidate

    if not url.startswith("http"):
        url = "https://" + url
    try:
        script = f"""
        tell application "Google Chrome"
            make new window
            set URL of active tab of front window to "{url}"
        end tell
        """
        subprocess.run(["osascript", "-e", script], check=True)
        return {"status": "success", "message": f"Navigated to {url} in a new window"}
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
        "description": "Search the web for current information, news, facts. Reads the top articles in full before answering.",
        "args": ["query"],
        "function": search_web,
    },
    "read_page": {
        "description": "Open a specific web page or article by URL and read its full contents. Use when the user gives or refers to a link, or wants you to read/go deeper on a particular article.",
        "args": ["url"],
        "function": read_page,
    },
    "read_file": {
        "description": "Read the contents of a file at the given absolute path.",
        "args": ["path"],
        "function": read_file,
    },
    "find_project": {
        "description": "Resolve a project the user named (e.g. 'teenyurl', possibly misheard like 'teeny url') to its REAL folder path under ~/Projects. ALWAYS call this first when the user references one of their projects, before reading files or running git — it returns the actual path so you never guess it.",
        "args": ["project"],
        "function": find_project,
    },
    "read_project_file": {
        "description": "Read a file from one of the user's projects in ONE step (resolves the project name AND reads the file). Use this for 'what does <project>'s <file> do', 'review the code in <project>', 'explain <project>/main.py'. Pass the project name and the file (e.g. 'main.py'); leave file empty to read the project's main entry file. Returns the contents — then answer from them.",
        "args": ["project", "filename"],
        "function": read_project_file,
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
        "description": "Takes a screenshot of the current screen and saves it to a file. Use only when the user explicitly wants a screenshot saved, NOT to look at the screen.",
        "args": [],
        "function": take_screenshot,
    },
    "look_at_screen": {
        "description": "Look at the user's screen and answer a question about it. Use whenever the user asks what is on their screen, to check or describe what's displayed, whether something looks right/arranged, or to read on-screen text. Pass the user's question.",
        "args": ["question"],
        "function": look_at_screen,
    },
    "set_reminder": {
        "description": "Set a reminder to tell the user something at a later time. Use for 'remind me to X in N minutes', 'remind me to X at 5pm', 'remind me every day at 8 to X'. Pass what to remind about as 'message' and the time as 'when'.",
        "args": ["message", "when"],
        "function": set_reminder,
    },
    "set_timer": {
        "description": "Set a countdown timer that alerts the user when it elapses. Use for 'set a timer for 5 minutes' or 'timer for 10 minutes for the pasta'. Pass the length as 'duration' and an optional 'label'.",
        "args": ["duration", "label"],
        "function": set_timer,
    },
    "list_reminders": {
        "description": "List all of the user's currently pending reminders and timers. Use for 'what reminders do I have', 'list my timers'.",
        "args": [],
        "function": list_reminders,
    },
    "cancel_reminder": {
        "description": "Cancel a pending reminder, timer, or monitor. Use for 'cancel my timer', 'stop watching X', 'cancel the reminder about X'. Pass a name, number, or leave 'which' empty if there's only one.",
        "args": ["which"],
        "function": cancel_reminder,
    },
    "set_monitor": {
        "description": "Watch the web for a topic and proactively alert the user when something new and important appears. Use for topics/people/news: 'monitor Fabrizio for Barcelona news', 'keep an eye on bitcoin', 'tell me when X happens', 'watch Fabrizio's tweets'. Pass what to watch as 'query' and an optional check 'interval' like 'every 30 minutes'.",
        "args": ["query", "interval"],
        "function": set_monitor,
    },
}


def get_tools_prompt() -> str:
    s = "You have access to the following tools:\n"
    for name, tool in TOOLS.items():
        args = ", ".join(tool["args"])
        s += f"- {name}({args}): {tool['description']}\n"
    return s


# Per-argument hints for the native tool schema. All args are strings; this
# only overrides description/enum where it helps the model pick correctly.
# Args not listed here default to {"type": "string", "description": <arg name>}.
ARG_DETAILS: dict[str, dict] = {
    "command": {"type": "string", "description": "The shell command to run."},
    "name": {"type": "string", "description": "The full app name, e.g. 'Google Chrome'."},
    "path": {"type": "string", "description": "Absolute file path."},
    "content": {"type": "string", "description": "Content to write to the file."},
    "query": {"type": "string", "description": "The search query."},
    "question": {
        "type": "string",
        "description": "The user's question about what is on the screen.",
    },
    "url": {"type": "string", "description": "The URL to navigate to."},
    "title": {"type": "string", "description": "Title of the song, show, or movie."},
    "service": {
        "type": "string",
        "description": "Streaming service to use.",
        "enum": ["Spotify", "Netflix"],
    },
    "message": {"type": "string", "description": "What to remind the user about, e.g. 'call mom'."},
    "when": {"type": "string", "description": "When to fire: 'in 10 minutes', 'at 5:30pm', 'tomorrow at 9am', 'every day at 8'."},
    "duration": {"type": "string", "description": "Timer length, e.g. '5 minutes' or '90 seconds'."},
    "label": {"type": "string", "description": "Optional name for the timer (may be empty)."},
    "which": {"type": "string", "description": "Which reminder/timer/monitor to cancel: a name, a number, or empty if only one."},
    "interval": {"type": "string", "description": "How often to check, e.g. 'every 30 minutes' or '1 hour'. Empty defaults to 30 minutes."},
    "project": {"type": "string", "description": "The project name the user mentioned (may be misheard, e.g. 'teeny url')."},
    "filename": {"type": "string", "description": "File to read, e.g. 'main.py'. Empty reads the project's main entry file."},
}

_TOOLS_SPEC_CACHE: Optional[list[dict]] = None


def get_tools_spec() -> list[dict]:
    """Build the native Ollama tool schema from TOOLS. Cached — TOOLS is static."""
    global _TOOLS_SPEC_CACHE
    if _TOOLS_SPEC_CACHE is not None:
        return _TOOLS_SPEC_CACHE

    spec = []
    for name, tool in TOOLS.items():
        properties = {
            arg: ARG_DETAILS.get(arg, {"type": "string", "description": arg})
            for arg in tool["args"]
        }
        spec.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(tool["args"]),
                    },
                },
            }
        )

    _TOOLS_SPEC_CACHE = spec
    return spec


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name, None)
