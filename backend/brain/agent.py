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


def _build_agent_system_prompt() -> str:
    base = get_personality()
    cwd = os.getcwd()
    return (
        base
        + f"""

━━━ AGENT MODE — ACTIVE ━━━

You are now operating in multi-step agent mode.

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
1. Always output a "thought" field explaining your reasoning before acting.
2. Execute tasks one step at a time.
3. After each tool result, reason about whether the goal is complete.
4. When complete, output type="reply" with a natural summary.
5. Never repeat a tool call that already succeeded.
6. If a tool fails repeatedly, stop and ask for help.
7. In your thoughts, refer to the user as "Sir", "Boss", or "the user" — never by name.
8. In execution history, always check the "success" field. If success=false, that step needs to be fixed before moving on. Never assume a step succeeded unless success=true.

Output format:
{{"thought": "your reasoning here", "type": "tool", "name": "tool_name", "args": {{...}}}}
{{"thought": "goal complete", "type": "reply", "content": "natural response"}}
"""
    )


async def run_agent(
    user_utterance: str,
    resume_state: dict = None,
) -> dict:
    """
    Orchestrates the multi-step Plan-Execute-Observe loop.

    resume_state: if provided, resumes from a pending confirmation.
    Format: {
        "goal": str,
        "confirmed_command": str,
        "history": list,
        "retry_counts": dict,
        "system_prompt": str,
        "base_prompt": str,
    }
    """
    # ── Resuming from confirmation ──────────────────────────────────────
    # ── Resuming from confirmation ──────────────────────────────────────
    if resume_state:
        log_system("agent", "Resuming from confirmed command.")
        goal = resume_state["goal"]
        confirmed_command = resume_state["confirmed_command"]
        agent_history = resume_state["history"]
        retry_counts = resume_state["retry_counts"]
        system_prompt = resume_state["system_prompt"]
        base_prompt = resume_state["base_prompt"]
        start_iteration = len(agent_history) + 1

        log_system("agent", f"Executing confirmed: {confirmed_command}")
        try:
            tool_result = await asyncio.to_thread(executor_execute, confirmed_command)
        except Exception as e:
            tool_result = f"Execution error: {str(e)}"
            log_error(f"Confirmed command failed: {e}")

        log_result("agent", tool_result)

        # Detect silent failures — git returned status instead of commit success
        result_str = str(tool_result)
        silent_failure = any(
            x in result_str
            for x in [
                "Changes not staged",
                "no changes added",
                "nothing to commit",
                "nothing added to commit",
                "Untracked files",
            ]
        )

        agent_history.append(
            {
                "step": start_iteration,
                "action": "run_shell",
                "args": {"command": confirmed_command},
                "result": result_str[:300],
                "success": not silent_failure,
                "note": (
                    "FAILED — nothing was staged, need to run git add first"
                    if silent_failure
                    else "success"
                ),
            }
        )

        start_iteration += 1
    # ── Fresh start ─────────────────────────────────────────────────────
    else:
        log_system("agent", f"Goal: '{user_utterance}'")
        goal = user_utterance
        agent_history = []
        retry_counts = {}
        system_prompt = _build_agent_system_prompt()
        start_iteration = 1

        # Memory context injection
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

        base_prompt = f"""{context_summary}
User Goal: "{user_utterance}"

Complete this goal step by step. Check your execution history before each action.
If you need to find a project path, use search_memory first, then ls ~/Projects."""

    # ── Agent loop ───────────────────────────────────────────────────────
    for iteration in range(start_iteration, MAX_ITERATIONS + 1):
        log_system("agent", f"Iteration {iteration}/{MAX_ITERATIONS}")

        current_prompt = base_prompt
        if agent_history:
            history_str = "\n".join([json.dumps(h) for h in agent_history])
            current_prompt += (
                f"\n\n[Execution History]:\n{history_str}\n\nWhat is your next action?"
            )

        response = await asyncio.to_thread(agent_chat, current_prompt, system_prompt)

        thought = response.get("thought", "")
        rtype = response.get("type", "reply")
        done = response.get("done", False)

        log_system("agent", f"Thought: {thought}")

        if rtype == "reply" or done:
            log_system("agent", "Goal complete.")
            return {
                "type": "reply",
                "content": response.get("content")
                or response.get("message")
                or "Done Sir.",
            }

        if rtype != "tool":
            log_error(f"Unexpected response type: {rtype}")
            break

        tool_name = response.get("name")
        tool_args = response.get("args", {})

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

        # Confirmation required — return state for resumption
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
                    "history": agent_history,
                    "retry_counts": retry_counts,
                    "system_prompt": system_prompt,
                    "base_prompt": base_prompt,
                },
            }

        truncated_result = str(tool_result)[:300]
        if len(str(tool_result)) > 300:
            truncated_result += "... [Truncated]"

        agent_history.append(
            {
                "step": iteration,
                "action": tool_name,
                "args": tool_args,
                "result": truncated_result,
            }
        )

    log_system("agent", "Max iterations reached.")
    return {
        "type": "reply",
        "content": "Sir, I hit my step limit on that task. Want me to try a different approach?",
    }
