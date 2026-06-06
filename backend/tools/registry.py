from typing import TypedDict, Callable, Optional

from tools.shell import run_shell
from tools.files import read_file, write_file
from tools.apps import open_app, close_app
from tools.datetime_tool import get_date_time


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
        "function": None,
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
}


def get_tools_prompt() -> str:
    s = "You have access to the following tools:\n"
    for name, tool in TOOLS.items():
        args = ", ".join(tool["args"])
        s += f"- {name}({args}): {tool['description']}\n"
    return s


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name, None)
