from typing import TypedDict, Callable, Optional

from tools.web import search_web
from tools.shell import run_shell
from tools.files import read_file, write_file
from tools.apps import open_app, close_app
from tools.datetime_tool import get_date_time
from tools.media import play_media
from memory.retrieve import search_memory


class Tool(TypedDict):
    description: str
    args: list[str]
    function: Optional[Callable]


TOOLS: dict[str, Tool] = {
    "open_app": {
        "description": "Open any app on this mac",
        "args": ["name"],
        "function": open_app,
    },
    "close_app": {
        "description": "Close any app on this mac",
        "args": ["name"],
        "function": close_app,
    },
    "run_shell": {
        "description": "Runs a safe shell command on the Mac",
        "args": ["command"],
        "function": run_shell,
    },
    "search_web": {
        "description": "Searches the web for current information",
        "args": ["query"],
        "function": search_web,
    },
    "read_file": {
        "description": "Reads the contents of a file",
        "args": ["path"],
        "function": read_file,
    },
    "write_file": {
        "description": "Writes content to a file",
        "args": ["path", "content"],
        "function": write_file,
    },
    "get_date_time": {
        "description": "Returns the current date and time",
        "args": [],
        "function": get_date_time,
    },
    "search_memory": {
        "description": "Search FRIDAY's memory for facts about the user or any entity. Use this when the user references people, places, projects or preferences.",
        "args": ["query"],
        "function": search_memory,
    },
    "play_media": {
        "description": "Play or open a movie, show, song, artist, or album in a supported media service. Use for requests like 'watch The Good Doctor on Netflix' or 'play Blinding Lights on Spotify'.",
        "args": ["title", "service"],
        "function": play_media,
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
