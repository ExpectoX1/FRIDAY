import json
import asyncio
from brain.llm import agent_chat
from brain.personality import get_personality
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import log_system, log_tool, log_result, log_error

MAX_ITERATIONS = 5
MAX_RETRIES_PER_TOOL = 3


def _build_agent_system_prompt() -> str:
    """Agent system prompt — extends personality with multi-step reasoning instructions."""
    base = get_personality()
    return (
        base
        + """

━━━ AGENT MODE — ACTIVE ━━━

You are now operating in multi-step agent mode. You must reason through tasks step by step.

Rules:
1. Always output a "thought" field explaining your reasoning before acting.
2. If the goal requires multiple steps, execute them one at a time.
3. After each tool result, reason about whether the goal is complete.
4. When the goal is fully complete, output type="reply" with a natural summary.
5. Never repeat a tool call that already succeeded in your execution history.
6. If a tool fails repeatedly, stop and ask the user for help.

Output format:
{"thought": "your reasoning here", "type": "tool", "name": "tool_name", "args": {...}}
{"thought": "goal complete", "type": "reply", "content": "natural response to user"}
"""
    )


async def run_agent(user_utterance: str) -> dict:
    """
    Orchestrates the multi-step Plan-Execute-Observe loop.
    Returns a reply dict for main.py to pass to the TTS queue.
    """
    log_system("agent", f"Goal: '{user_utterance}'")

    # Step 1 — Memory context injection (always)
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

    agent_history = []
    retry_counts = {}  # track failures per tool
    system_prompt = _build_agent_system_prompt()

    base_prompt = f"""{context_summary}
User Goal: "{user_utterance}"

Complete this goal step by step. Check your execution history before each action."""

    for iteration in range(1, MAX_ITERATIONS + 1):
        log_system("agent", f"Iteration {iteration}/{MAX_ITERATIONS}")

        # Build prompt with execution history
        current_prompt = base_prompt
        if agent_history:
            history_str = "\n".join([json.dumps(h) for h in agent_history])
            current_prompt += (
                f"\n\n[Execution History]:\n{history_str}\n\nWhat is your next action?"
            )

        # Step 2 — Planner: Gemma reasons and decides next action
        response = await asyncio.to_thread(agent_chat, current_prompt, system_prompt)

        thought = response.get("thought", "")
        rtype = response.get("type", "reply")
        done = response.get("done", False)

        log_system("agent", f"Thought: {thought}")

        # Exit conditions
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

        # Step 3 — Executor: run the tool
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

        # Step 4 — Observer: check for failures, enforce retry budget
        is_error = isinstance(tool_result, str) and any(
            x in tool_result.lower()
            for x in ["error", "failed", "exception", "permission denied", "not found"]
        )

        if is_error:
            retry_counts[tool_name] = retry_counts.get(tool_name, 0) + 1
            log_error(
                f"Tool {tool_name} failure detected. Attempt {retry_counts[tool_name]}/{MAX_RETRIES_PER_TOOL}"
            )

            if retry_counts[tool_name] >= MAX_RETRIES_PER_TOOL:
                log_system(
                    "agent",
                    f"Tool {tool_name} hit retry cap. Aborting to prevent loop.",
                )
                return {
                    "type": "reply",
                    "content": f"Sir, I ran into a persistent issue executing the {tool_name} tool. It keeps returning: '{tool_result}'. Would you like me to try something else?",
                }
        else:
            retry_counts[tool_name] = 0

        # Handle system confirmation requirements mid-run
        if isinstance(tool_result, str) and tool_result.startswith(
            "NEEDS_CONFIRMATION:"
        ):
            command = tool_result.replace("NEEDS_CONFIRMATION:", "").strip()
            return {
                "type": "reply",
                "content": f"Sir, I need your approval to execute the following terminal command: {command}. Should I proceed?",
            }

        # Format and truncate the result to protect context limits
        truncated_result = str(tool_result)[:300]
        if len(str(tool_result)) > 300:
            truncated_result += "... [Truncated]"

        # Keep a clean log of actions and results in the agent loop context
        history_step = {
            "step": iteration,
            "action": tool_name,
            "args": tool_args,
            "result": truncated_result,
        }
        agent_history.append(history_step)

    # Catch iteration limit overflow (infinite loop safety guardrail)
    log_system("agent", "Maximum thinking iterations reached. Closing loop.")
    return {
        "type": "reply",
        "content": "Sir, I have hit my maximum reasoning steps limit for this task. Let me know if we should try a different approach.",
    }
