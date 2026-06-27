import json
import asyncio
import os
from brain.llm import agent_chat
from brain.personality import get_personality
from tools.registry import get_tool
from sandbox.executor import run as executor_run, execute as executor_execute
from logger import log_system, log_tool, log_result, log_error

MAX_ITERATIONS = 10
MAX_RETRIES_PER_TOOL = 3

# Tools that are almost always the FINAL action of a goal. When one succeeds we
# return its own result message instead of paying another full inference just to
# phrase a summary. Deliberately excludes chain-starters like open_app (often
# "open chrome AND go to ...") and intermediate tools (search_*, read_file,
# run_shell) where the model genuinely needs to reason about the result.
TERMINAL_TOOLS = {"play_media", "navigate_browser", "get_date_time"}


def _tool_message(result) -> str:
    """Extract a user-facing line from a tool result."""
    if isinstance(result, dict):
        return result.get("message") or result.get("content") or "Done, Sir."
    return str(result) if result else "Done, Sir."

# Built once per process. The agent system prompt is static (personality +
# tools list + cwd), so rebuilding it on every task — and re-deriving the
# tools prompt each time — was pure overhead.
_AGENT_SYSTEM_PROMPT: str | None = None


def _get_agent_system_prompt() -> str:
    global _AGENT_SYSTEM_PROMPT
    if _AGENT_SYSTEM_PROMPT is None:
        _AGENT_SYSTEM_PROMPT = _build_agent_system_prompt()
    return _AGENT_SYSTEM_PROMPT


def _build_agent_system_prompt() -> str:
    base = get_personality(native_tools=True)
    cwd = os.getcwd()
    return (
        base
        + f"""

━━━ AGENT MODE — ACTIVE ━━━

You are operating in multi-step agent mode. You call tools natively; each tool
result comes back as a tool message. Work one step at a time, and when the goal
is finished, reply in plain natural language (no tool call) with a short summary.

Environment:
* Current working directory: {cwd}
* For git commands on a project, first discover its path, then use git -C <path> <subcommand>
* Never use && to chain commands. Use git -C <path> instead of cd && git.
* Never hardcode paths — always discover them using tools or memory first.
* All projects are located in ~/Projects/
* To find a specific project: run_shell("ls ~/Projects") then use git -C ~/Projects/<name>
* NEVER: "cd ~/Projects/FRIDAY && git status"
* ALWAYS: "git -C ~/Projects/FRIDAY status"

Discovery strategy:
* If you need a project path → search_memory first, then ls ~/Projects
* If you need running apps → get_running_apps
* If you need file locations → run_shell("ls") or read_file

Rules:
1. Execute tasks one step at a time; inspect each tool result before the next step.
1a. ACT, don't ask. Discover paths and info yourself with tools — the Downloads folder is ~/Downloads, projects are in ~/Projects, the home dir is standard. Never stop to ask the user for something you can find or reasonably assume; only ask if genuinely blocked or about to do something destructive.
1b. Only use look_at_screen when the task is specifically about what is visually ON the screen. Do NOT use it for file, git, web, app, or media tasks.
2. Never repeat a tool call that already succeeded. When the goal is done, reply with text — do not call another tool.
2a. When the user asks for information (news, facts, search results), your final reply MUST summarize the key findings directly in 2-4 sentences, then STOP. State the actual facts (who/what/when). Do NOT list sources to choose from, do NOT end with "which source would you prefer" or "shall I open the page" — only offer to open something if the user explicitly asked for a link.
2b. When you open a page or video, pass navigate_browser a real URL taken verbatim from a tool result (e.g. https://www.skysports.com/...). NEVER pass a title or description as the url.
3. If a tool result indicates an error, fix the cause before moving on. If a tool fails repeatedly, stop and ask for help in plain text.
4. Refer to the user as "Sir", "Boss", or "the user" — never by name.
5. Shell metacharacters (&&, ||, ;, |, >, >>, <, `, $() etc.) are BLOCKED in run_shell. You CANNOT chain commands. For any batch file operation (sorting a directory, moving/renaming/deleting multiple files, complex names), write a Python script via write_file to /Users/siddharthkumar/FRIDAY/workspace/your_script.py and run it with a single run_shell("python3 /Users/siddharthkumar/FRIDAY/workspace/your_script.py").
6. Media Routing Rules:
    - Song, artist, album, or music → play_media with service="Spotify".
    - Movie or TV show → play_media with service="Netflix".
    - A "video" (YouTube videos, creators like YJR, Markaroni, general web videos) → do NOT use Spotify/Netflix. search_web for the video URL, then open it with navigate_browser.
    - LIVE STREAMS ("X is live", "open the stream", "open X's livestream"): do NOT pick a watch?v= URL from search results — those are frequently OLD recordings (VODs), not the current broadcast. Instead navigate to https://www.youtube.com/@<handle>/live which auto-redirects to the creator's CURRENT live stream. Get the exact @handle from search if you don't know it (e.g. @Markaroni → https://www.youtube.com/@Markaroni/live). This /live rule is the ONLY case where an @handle URL is allowed.
    - Video URL Validation (non-live videos) — MANDATORY: the URL you pass to navigate_browser MUST be a direct watch link of the form https://www.youtube.com/watch?v=<id>. NEVER navigate to a channel page, an @handle page, a /videos page, or a /results search page — those do not auto-play. First identify the latest video's exact title from the search summary, then confirm a matching watch?v= URL appears in the results. If no watch?v= URL for that exact title is present, run a second search like search_web("<creator> <exact title> youtube watch link") and only navigate once you have the watch?v= URL.
"""
    )


async def run_agent(
    user_utterance: str,
    resume_state: dict = None,
    chat_history: list = None,
) -> dict:
    """
    Orchestrates the multi-step Plan-Execute-Observe loop using native tool
    calling. The conversation lives in a real `messages` list (system, user,
    assistant-with-tool_calls, tool-result), so the model sees its own prior
    actions structurally instead of via a stringified history blob.

    resume_state: if provided, resumes from a pending confirmation. Format:
        {goal, confirmed_command, messages, retry_counts, succeeded}
    """
    SILENT_FAILURE_MARKERS = [
        "Changes not staged",
        "no changes added",
        "nothing to commit",
        "nothing added to commit",
        "Untracked files",
    ]

    # ── Resuming from confirmation ──────────────────────────────────────
    if resume_state:
        log_system("agent", "Resuming from confirmed command.")
        goal = resume_state["goal"]
        confirmed_command = resume_state["confirmed_command"]
        messages = resume_state["messages"]
        retry_counts = resume_state["retry_counts"]
        succeeded = set(resume_state.get("succeeded", []))

        log_system("agent", f"Executing confirmed: {confirmed_command}")
        try:
            tool_result = await asyncio.to_thread(executor_execute, confirmed_command)
        except Exception as e:
            tool_result = f"Execution error: {str(e)}"
            log_error(f"Confirmed command failed: {e}")

        log_result("agent", tool_result)

        result_str = str(tool_result)
        silent_failure = any(x in result_str for x in SILENT_FAILURE_MARKERS)
        content = result_str
        if silent_failure:
            content += "\n[NOTE] Nothing was staged — run git add first."
        else:
            succeeded.add(f"run_shell:{json.dumps({'command': confirmed_command}, sort_keys=True)}")

        # The assistant tool_call (run_shell) is already the last assistant turn
        # in `messages`; append its result so the conversation stays well-formed.
        messages.append({"role": "tool", "tool_name": "run_shell", "content": content[:4000]})

    # ── Fresh start ─────────────────────────────────────────────────────
    else:
        log_system("agent", f"Goal: '{user_utterance}'")
        goal = user_utterance
        retry_counts = {}
        succeeded = set()
        system_prompt = _get_agent_system_prompt()

        context_summary = ""
        try:
            memory_tool = get_tool("search_memory")
            if memory_tool and memory_tool["function"]:
                memory_res = await asyncio.to_thread(
                    memory_tool["function"], query=user_utterance
                )
                if memory_res:
                    context_summary = f"\n[Memory Context]:\n{memory_res}\n"
                    log_system("agent", "Memory context injected.")
        except Exception as e:
            log_error(f"Memory lookup failed: {e}")

        session_context = ""
        if chat_history:
            recent_turns = chat_history[-4:]
            formatted_turns = "\n".join(
                [f"* {msg['role'].upper()}: {msg['content']}" for msg in recent_turns]
            )
            session_context = f"[Recent Chat Session History]:\n{formatted_turns}\n"

        user_goal_prompt = f"""{session_context}{context_summary}
            User Goal: "{user_utterance}"
            Complete this goal step by step. If the goal references a previous action implicitly (e.g. "push as well", "undo that"), use the recent session history to identify the target project or file path."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_goal_prompt},
        ]

    # ── Agent loop ───────────────────────────────────────────────────────
    for iteration in range(1, MAX_ITERATIONS + 1):
        log_system("agent", f"Iteration {iteration}/{MAX_ITERATIONS}")

        response = await asyncio.to_thread(agent_chat, messages)

        thought = response.get("thought", "")
        if thought:
            log_system("agent", f"Thought: {thought}")

        if response.get("type") == "reply":
            log_system("agent", "Goal complete.")
            return {"type": "reply", "content": response.get("content") or "Done Sir."}

        tool_name = response.get("name")
        tool_args = response.get("args", {})

        # Append the assistant's tool-call turn so the model sees it next round.
        messages.append(response["raw_message"])

        # Deterministic loop guard: identical to an already-succeeded call means
        # the model is stuck re-running a completed action — finish instead.
        call_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
        if call_signature in succeeded:
            log_system("agent", "Duplicate of a succeeded call — completing goal.")
            return {"type": "reply", "content": thought or "Done, Sir."}

        log_tool("agent", tool_name, tool_args)

        tool_result = None
        try:
            if tool_name == "run_shell":
                tool_result = await asyncio.to_thread(
                    executor_run, tool_args.get("command", "")
                )
            else:
                target_tool = get_tool(tool_name)
                if target_tool and target_tool["function"]:
                    tool_result = await asyncio.to_thread(
                        target_tool["function"], **tool_args
                    )
                else:
                    tool_result = f"Error: Tool '{tool_name}' not found."
        except Exception as e:
            tool_result = f"Execution error: {str(e)}"
            log_error(f"Tool {tool_name} crashed: {e}")

        log_result("agent", tool_result)

        # Confirmation required — pause and return state for resumption.
        if isinstance(tool_result, str) and tool_result.startswith(
            "NEEDS_CONFIRMATION:"
        ):
            command = tool_result.replace("NEEDS_CONFIRMATION:", "").strip()
            return {
                "type": "needs_confirmation",
                "content": f"Sir, I need your approval to run: {command}. Should I proceed?",
                "pending_state": {
                    "goal": goal,
                    "confirmed_command": command,
                    "messages": messages,
                    "retry_counts": retry_counts,
                    "succeeded": list(succeeded),
                },
            }

        is_error = isinstance(tool_result, str) and any(
            x in tool_result.lower()
            for x in [
                "error",
                "failed",
                "exception",
                "permission denied",
                "not found",
                "blocked",
            ]
        )

        if is_error:
            retry_counts[tool_name] = retry_counts.get(tool_name, 0) + 1
            log_error(
                f"Tool {tool_name} failure. Attempt {retry_counts[tool_name]}/{MAX_RETRIES_PER_TOOL}"
            )
            if retry_counts[tool_name] >= MAX_RETRIES_PER_TOOL:
                return {
                    "type": "reply",
                    "content": f"Sir, {tool_name} keeps failing after {MAX_RETRIES_PER_TOOL} attempts: '{str(tool_result)[:100]}'. Want me to try a different approach?",
                }
        else:
            retry_counts[tool_name] = 0
            succeeded.add(call_signature)

            # Terminal tool succeeded → the goal is done. Skip the extra
            # summarization inference and reply from the tool result directly.
            if tool_name in TERMINAL_TOOLS:
                log_system("agent", f"Terminal tool '{tool_name}' done — completing.")
                return {"type": "reply", "content": _tool_message(tool_result)}

        truncated_result = str(tool_result)[:4000]
        if len(str(tool_result)) > 4000:
            truncated_result += "... [Truncated]"

        # Feed the tool result back as a proper tool message.
        messages.append(
            {"role": "tool", "tool_name": tool_name, "content": truncated_result}
        )

    log_system("agent", "Max iterations reached.")
    return {
        "type": "reply",
        "content": "Sir, I hit my step limit on that task. Want me to try a different approach?",
    }
