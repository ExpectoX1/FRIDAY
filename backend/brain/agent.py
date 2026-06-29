import json
import asyncio
import os
import re
from brain.llm import agent_chat, agent_chat_stream
from brain.personality import get_personality
from tools.registry import get_tool
from sandbox.executor import run as executor_run, execute as executor_execute
from logger import log_system, log_tool, log_result, log_error, status
from bridge import state_bus

MAX_ITERATIONS = 10
MAX_RETRIES_PER_TOOL = 3

# ── Success verification ──────────────────────────────────────────────────────
# A tool returning no error does NOT prove the GOAL was met: a shell script can
# run cleanly yet do the wrong thing, a write can land the wrong content, a git
# commit can succeed while nothing was staged. When the agent declares the goal
# done AND it took a consequential (state-changing) action, a cheap local judge
# re-checks that the goal was actually accomplished before we accept completion.
# Pure read/lookup tools (search_web, read_file) need no such check — their
# result IS the deliverable. Disable with FRIDAY_VERIFY=0 (e.g. for benchmarks).
VERIFY_ENABLED = os.getenv("FRIDAY_VERIFY", "1") != "0"
CONSEQUENTIAL_TOOLS = {"run_shell", "write_file"}
MAX_VERIFICATION_PUSHBACKS = 1
VERIFY_SYSTEM = "You are a strict QA verifier for an AI agent. Be terse and literal."


def _short_args(args: dict) -> str:
    return ", ".join(f"{k}={str(v)[:60]}" for k, v in (args or {}).items())


def _parse_verdict(raw: str) -> tuple[bool, str]:
    """Parse a verifier reply into (achieved, reason). Fail-OPEN: anything that
    isn't an explicit NOT_ACHIEVED counts as achieved, so the verifier can never
    block a real completion on its own ambiguity or a malformed reply."""
    text = (raw or "").strip()
    if "NOT_ACHIEVED" in text.upper().replace(" ", "_"):
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return False, (reason[:300] or "the goal was not fully accomplished")
    return True, ""


def _verify_goal(goal: str, action_log: list) -> tuple[bool, str]:
    """Cheap local judge: given the goal and the actions actually taken (with
    their results), was the goal genuinely accomplished? Returns (achieved,
    reason). Fail-open on any error — verification must never strand the user."""
    if not action_log:
        return True, ""
    try:
        from brain.llm import ask  # lazy: agent is imported early in the brain
    except Exception:
        return True, ""

    steps = "\n".join(
        f"- {name}({_short_args(args)}) -> {str(result)[:200]}"
        for name, args, result in action_log
    )
    prompt = (
        f'GOAL: "{goal}"\n\nACTIONS TAKEN (tool -> result):\n{steps}\n\n'
        "Did these actions ACTUALLY accomplish the goal? Judge the end state, not "
        "the intent — e.g. a push must have pushed, a written file must contain "
        "what was asked, a 'commit' with nothing staged did NOT commit. Reply on "
        "ONE line, exactly one of:\n"
        "ACHIEVED\n"
        "NOT_ACHIEVED: <one short reason what is missing>"
    )
    try:
        raw = ask(prompt, system=VERIFY_SYSTEM)
    except Exception:
        return True, ""
    return _parse_verdict(raw)

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


# A tool result is a failure only when it ANNOUNCES one — a dict with
# status="error", or a string that *begins* with a known error marker. We must
# never substring-match "error"/"exception"/"failed" anywhere in the result:
# reading a file that imports HTTPException, or a search result that mentions an
# error, is not a tool failure. That false positive used to flip last_failed and
# send the agent flailing — e.g. running git on, and committing, an unrelated
# repo to "fix" a failure that never happened.
_ERROR_PREFIXES = (
    "error",                              # "Error: ...", "Error reading file:", "Error writing file:"
    "execution error",
    "blocked:",                           # executor: blocked metachars / dangerous command
    "file not found",                     # read_file miss
    "search failed",                      # search_web / read_page
    "fatal:",                             # git
    "command not found",
    "no such file",
    "permission denied",
    "traceback (most recent call last)",  # uncaught python error in a run_shell script
)


def _tool_failed(result) -> bool:
    """True only when a tool announces a failure (see _ERROR_PREFIXES)."""
    if isinstance(result, dict):
        return str(result.get("status", "")).lower() == "error"
    if isinstance(result, str):
        return result.lstrip().lower().startswith(_ERROR_PREFIXES)
    return False


# Inspection/discovery verbs that belong in a TOOL CALL, not in narrated intent.
_NEXT_ACTION_RE = re.compile(
    r"\b(let me|i'?ll|i will|i'?m going to|i need to|i should|let me first|let's)\b"
    r"[^.!?]*?\b(take a look|look at|look into|check|read|open|examine|inspect|"
    r"review|analy[sz]e|fetch|find|search|list|see what|explore|investigate|"
    r"go through|dig into|pull up)\b",
    re.IGNORECASE,
)


def _announces_next_action(text: str) -> bool:
    """True when the reply ENDS by announcing an inspection it hasn't done yet
    ("Let me take a look at main.py...") instead of giving the answer. That is not
    completion — the model should call the tool rather than stop. We check only
    the final sentence so a real answer with a trailing "let me know" closer
    (or "I'll fix X") is not mistaken for an unfinished step."""
    if not text:
        return False
    last_sentence = re.split(r"(?<=[.!?])\s+", text.strip())[-1]
    if "let me know" in last_sentence.lower():
        return False
    return bool(_NEXT_ACTION_RE.search(last_sentence))


def _tool_status(name: str, args: dict | None = None) -> str:
    """A short, human, present-progressive line describing what FRIDAY is DOING
    right now (for the UI status line + console). Reads like an assistant
    narrating an action — "Reading main.py", "Checking your calendar" — never the
    internal tool name ("Running get_calendar") or step bookkeeping."""
    args = args or {}

    if name == "search_web":
        q = str(args.get("query", "")).strip()
        return f"Searching the web for {q}" if q else "Searching the web"
    if name == "read_page":
        return "Reading the page"
    if name == "search_memory":
        return "Searching memory"
    if name == "navigate_browser":
        return "Opening the page"
    if name == "run_shell":
        cmd = str(args.get("command", "")).strip()
        return f"Running {cmd[:60]}" if cmd else "Running a command"
    if name == "play_media":
        return "Starting playback"
    if name == "get_date_time":
        return "Checking the time"
    if name == "get_calendar":
        return "Checking your calendar"
    if name == "read_email":
        return "Checking your email"
    if name == "watch_email":
        return "Setting up an email alert"
    if name in ("read_file", "read_project_file"):
        target = args.get("filename") or os.path.basename(str(args.get("path", "")))
        return f"Reading {target}" if target else "Reading the file"
    if name == "write_file":
        target = os.path.basename(str(args.get("path", "")))
        return f"Writing {target}" if target else "Writing the file"
    if name == "find_project":
        return "Finding the project"
    if name in ("open_app", "close_app"):
        verb = "Opening" if name == "open_app" else "Closing"
        return f"{verb} {args.get('name', 'the app')}"
    if name == "get_running_apps":
        return "Checking open apps"
    if name == "look_at_screen":
        return "Looking at your screen"
    if name == "take_screenshot":
        return "Taking a screenshot"
    if name == "set_reminder":
        return "Setting a reminder"
    if name == "set_timer":
        return "Setting a timer"
    if name == "list_reminders":
        return "Checking your reminders"
    if name == "cancel_reminder":
        return "Cancelling that"
    if name == "set_monitor":
        return "Setting up a watch"
    return "Working on it"

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
* When the user names one of their projects, ALWAYS call find_project(<name>) FIRST
  to get its real folder path. The name comes from speech and may be misheard or
  cased differently ("teeny url", "teeny oral" → "teenyurl"); find_project resolves
  it deterministically. NEVER guess the path or use the spoken name literally (no
  `ls ~/Projects/Teeny URL`, no inventing /Users/<name>), and never say a project
  is missing unless find_project returns an error listing the real projects.
* Then use that real path for read_file / run_shell / git -C <path>.
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
2c. NEVER announce an action and then stop ("Let me take a look at main.py...", "Let me check its contents", "I'll read the file now"). If you intend to read/open/inspect/run something, CALL that tool in this SAME step. Only reply with plain text once you ACTUALLY have the answer from the tool results. Narrating intent without calling the tool is treated as not done.
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
7. The user's OWN files, code, and projects (explain/review/"what does this do"/"is this code good"/"what's in this folder"):
    - For a file in one of their projects, prefer read_project_file(project, filename) — it resolves the project AND reads the file in one step (e.g. read_project_file("teenyurl", "main.py")). Otherwise: find_project for the path, run_shell("ls <path>") to see a folder, read_file for an absolute path. Never use look_at_screen for files or folders.
    - Answer ENTIRELY from the contents you actually read. NEVER search_web for a similarly-named project — the user's local "teenyurl" is THEIR code, not some GitHub repo with a similar name. search_web is for external facts/news ONLY, never for understanding the user's own files. If you haven't read the file yet, read it first; do not guess from the name.
    - Give a concrete, grounded answer: say what the code actually does (the real functions/endpoints/logic you saw) and, when asked to review, 1-3 specific suggestions. Never reply with a vague "you've shared a script, let me know if you have questions".
"""
    )


async def run_agent(
    user_utterance: str,
    resume_state: dict = None,
    chat_history: list = None,
    on_token_callback = None,
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

    # What the agent actually DID (tool, args, result) and whether any of it was
    # state-changing — fed to the success verifier when the goal is declared done.
    action_log: list = []
    consequential: set = set()

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

        # A confirmed command is always state-changing — log it so the verifier
        # judges the resumed goal too (this is exactly the silent-failure path).
        action_log.append(("run_shell", {"command": confirmed_command}, result_str[:200]))
        consequential.add("run_shell")

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
    # Track whether the most recent tool call failed, so the model can't claim
    # the goal is done right after an error (it tried to say "Done Sir." after a
    # crashed write_file). We push back and make it fix the failure first.
    last_failed = bool(resume_state) and locals().get("silent_failure", False)
    last_error = ""
    completion_pushbacks = 0
    MAX_COMPLETION_PUSHBACKS = 3
    verification_pushbacks = 0

    for iteration in range(1, MAX_ITERATIONS + 1):
        log_system("agent", f"Iteration {iteration}/{MAX_ITERATIONS}")
        # A plain "Thinking..." reads naturally; the specific action shows up a
        # beat later as the tool fires ("Reading main.py"). Step numbers are
        # internal bookkeeping and shouldn't leak to the user.
        step_message = "Thinking..."
        state_bus.set_state("thinking", message=step_message, tool=None)
        status("Agent", step_message)

        def run_stream():
            res = None
            for event_type, data in agent_chat_stream(messages):
                if event_type == "token":
                    if on_token_callback:
                        on_token_callback(data)
                elif event_type == "tool" or event_type == "reply":
                    res = data
            return res

        response = await asyncio.to_thread(run_stream)

        thought = response.get("thought", "")
        if thought:
            log_system("agent", f"Thought: {thought}")

        if response.get("type") == "reply":
            # Don't accept completion if the last step failed — the goal isn't
            # actually done. Push back and make the model fix it.
            if last_failed and completion_pushbacks < MAX_COMPLETION_PUSHBACKS:
                completion_pushbacks += 1
                log_system("agent", "Reply after a failed step — pushing back.")
                messages.append({
                    "role": "user",
                    "content": (
                        f"The previous step FAILED: {last_error[:300]}. The goal is "
                        "NOT complete — do not say you are done. Fix the cause "
                        "(e.g. provide ALL required tool arguments) and continue "
                        "by calling the appropriate tool now."
                    ),
                })
                continue

            # The model only ANNOUNCED a next step ("Let me take a look at
            # main.py...") without calling the tool — that's not done. Push it to
            # actually act instead of completing on an empty promise.
            content = response.get("content") or ""
            if (_announces_next_action(content)
                    and completion_pushbacks < MAX_COMPLETION_PUSHBACKS):
                completion_pushbacks += 1
                log_system("agent", "Reply only announced a next action — pushing to act.")
                messages.append({
                    "role": "user",
                    "content": (
                        "You said you would do that but did not actually call a tool. "
                        "Do NOT narrate intent and stop. Call the tool now (e.g. "
                        "read_file / run_shell) to perform that step, then answer."
                    ),
                })
                continue

            # Success verification: the model thinks it's done and it took a
            # state-changing action — confirm the goal was ACTUALLY achieved
            # before we tell the user it's done. Runs at most once (bounded
            # latency) and fails open, so it only ever catches a real miss.
            if (VERIFY_ENABLED
                    and verification_pushbacks < MAX_VERIFICATION_PUSHBACKS
                    and consequential):
                state_bus.set_state("thinking", message="Double-checking the result...", tool=None)
                status("Agent", "verifying the result")
                achieved, reason = await asyncio.to_thread(_verify_goal, goal, action_log)
                if not achieved:
                    verification_pushbacks += 1
                    log_system("agent", f"Verification FAILED: {reason}")
                    messages.append({
                        "role": "user",
                        "content": (
                            f"VERIFICATION FAILED: {reason}. The goal is NOT actually "
                            "complete. Inspect the current state with a tool and finish "
                            "the job — do not claim it is done until it truly is."
                        ),
                    })
                    last_failed = False  # the step didn't error; the goal is just unmet
                    continue
                log_system("agent", "Verification passed.")

            log_system("agent", "Goal complete.")
            return {"type": "reply", "content": content or "Done Sir."}

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
        progress = _tool_status(tool_name, tool_args)
        state_bus.set_state("tool_running", tool=tool_name, message=progress)
        status("Agent", progress)

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
        try:
            from bridge.activity import emit_tool_activity
            from brain import code_context
            emit_tool_activity(tool_name, tool_args, tool_result)  # code/file cards to the window
            code_context.record_tool(tool_name, tool_args, tool_result)  # remember for follow-ups
        except Exception:
            pass

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

        is_error = _tool_failed(tool_result)

        # Record what was done for the end-of-goal verifier. Only successful,
        # state-changing actions arm verification — a failed step is already
        # handled by the retry/pushback paths, and reads never need it.
        if not is_error:
            action_log.append((tool_name, tool_args, str(tool_result)[:200]))
            if tool_name in CONSEQUENTIAL_TOOLS:
                consequential.add(tool_name)

        last_failed = is_error
        last_error = str(tool_result) if is_error else ""

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
