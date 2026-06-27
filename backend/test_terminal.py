import sys
import json
import asyncio
import time
from brain.llm import chat, is_complex
from brain.agent import run_agent  # Integrated the Agent Loop
from tools.registry import get_tool
from sandbox.executor import run as executor_run, execute
from logger import log_user, log_response, log_tool, log_result, log_error
from memory.store import store

# =========================================================
# CONSTANTS & CONFIG
# =========================================================

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

TESTS = [
    "Hi how are you",
    "Make a file on my desktop called auto_test.txt",
    "Write 'FRIDAY auto test passed' in it",
    "Read the file at ~/Desktop/auto_test.txt",
    "Delete the file auto_test.txt from my desktop",
    "List files on my desktop",
    "What is my current directory",
    "What time is it",
    "Run sudo rm something",
    "Access my .ssh folder",
    "Search for Barcelona transfer news",
    "What is my sister's name",
    "I am buying a car in December",
    "I am learning guitar",
]

# =========================================================
# ROUTING HEURISTIC
# =========================================================





# =========================================================
# SHARED TOOL EXECUTOR (Used for Single-Shot Fallbacks)
# =========================================================


def execute_tool(name: str, args: dict) -> tuple[str | None, float]:
    """Executes a tool and returns a tuple of (result, latency_ms)."""
    tool = get_tool(name)
    start_time = time.perf_counter()

    if tool is None:
        return f"I don't have a tool called {name} yet.", 0.0

    if tool["function"] is None:
        return f"The {name} tool isn't wired up yet.", 0.0

    try:
        if name == "run_shell":
            res = executor_run(args.get("command", ""))
        else:
            res = tool["function"](**args)
    except Exception as e:
        res = f"Execution Failure: {str(e)}"

    latency = (time.perf_counter() - start_time) * 1000
    return res, latency


# =========================================================
# HANDLE RESPONSE — MANUAL MODE (Single-Shot Routing only)
# =========================================================


def handle_manual_single_shot(response: dict, llm_latency: float):
    """Processes single-shot execution if routing bypassed the agent loop."""
    rtype = response.get("type")
    print(f"⏱️  [Metrics] Single-Shot LLM Latency: {llm_latency:.2f}ms")

    if rtype == "reply":
        print(f"💬 FRIDAY: {response.get('content')}\n")
        return

    if rtype == "tool":
        name = response.get("name")
        args = response.get("args", {})

        log_tool("tool", name, args)
        print(f"🛠️  [Tool Invocation] {name} → {args}")

        result, tool_latency = execute_tool(name, args)
        print(f"⏱️  [Metrics] Tool Latency: {tool_latency:.2f}ms")

        if result is None:
            print("📦 [Result] Done.\n")
            return

        log_result("tool", result)

        from brain.llm import set_last_result
        set_last_result(name, result)

        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            command = result.replace("NEEDS_CONFIRMATION:", "").strip()
            print(f"🔒 [CONFIRMATION REQUIRED] {command}")
            confirm = input("Approve execution? (yes/no): ").strip().lower()
            if confirm == "yes":
                confirm_start = time.perf_counter()
                result = execute(command)
                confirm_lat = (time.perf_counter() - confirm_start) * 1000
                print(f"⏱️  [Metrics] Exec Latency: {confirm_lat:.2f}ms")
                print(f"📦 [Result] {result}\n")
            else:
                print("🚫 [Cancelled by User]\n")
            return

        if name == "search_memory" and result:
            print(f"🧠 [Memory Retrieval] {result}")
            mem_start = time.perf_counter()
            follow_up = chat(
                f"Based on our conversation and this memory context, give a natural, concise spoken answer to what the user just asked. Do NOT ask what they want — just answer directly.\n\nMemory:\n{result}"
            )
            mem_lat = (time.perf_counter() - mem_start) * 1000
            print(f"⏱️  [Metrics] Context Synthesis Latency: {mem_lat:.2f}ms")
            print(f"💬 FRIDAY: {follow_up.get('content', result)}\n")
            return

        if name == "search_web" and result:
            print(f"🌐 [Web Search] {result}")
            web_start = time.perf_counter()
            follow_up = chat(
                f"Based on our conversation and these web search results, give the user a natural, concise spoken answer to what they just asked. Lead with the key facts. Do NOT ask what they want — just summarize and answer directly.\n\nResults:\n{result}"
            )
            web_lat = (time.perf_counter() - web_start) * 1000
            print(f"⏱️  [Metrics] Context Synthesis Latency: {web_lat:.2f}ms")
            print(f"💬 FRIDAY: {follow_up.get('content', result)}\n")
            return

        print(f"📦 [Result] {result}\n")
        return

    log_error(response.get("content", "Unknown response type"))
    print(f"❌ [Error] {response.get('content', 'Something went wrong')}\n")


# =========================================================
# RUN MODES
# =========================================================


def run_auto():
    print("=" * 75)
    print("                      FRIDAY SYSTEM AUTOMATION SUITE")
    print("=" * 75)

    passed = warned = failed = 0
    suite_start = time.perf_counter()

    # Need an event loop instance to run the async agent core during tests
    loop = asyncio.get_event_loop()

    for idx, test in enumerate(TESTS, 1):
        print(f'\n[Test #{idx}] Input: "{test}"')
        log_user(test)

        is_agent = _is_complex_task(test)
        route_label = "Agent Multi-Step Loop" if is_agent else "Single-Shot Core"
        print(f"  ├── Route:   {route_label}")

        start_time = time.perf_counter()

        if is_agent:
            # Route to async Agent Core
            response = loop.run_until_complete(run_agent(test))
        else:
            # Route to basic single-shot execution
            response = chat(test)

        latency = (time.perf_counter() - start_time) * 1000
        log_response(response)

        # Parse output signatures safely
        content = response.get("content") or response.get("message") or ""

        if "error" in content.lower() or "failed" in content.lower():
            status = f"{FAIL} FAILURE: {content[:60]}..."
            failed += 1
        elif "approval" in content.lower() or "proceed" in content.lower():
            status = f"{WARN} HALT: Requires Confirmation"
            warned += 1
        else:
            status = f"{PASS} SUCCESS: {content[:60]}..."
            passed += 1

        print(f"  └── Latency: {latency:.1f}ms")
        print(f"  └── Status:  {status}")

    suite_total_time = time.perf_counter() - suite_start
    print("\n" + "=" * 75)
    print(f"EXECUTION SUMMARY: {passed} passed | {warned} warnings | {failed} failed")
    print(f"Total Suite Runtime: {suite_total_time:.2f} seconds")
    print("=" * 75)


def run_manual():
    print("=" * 55)
    print("      FRIDAY INTERACTIVE TERMINAL TESTING ENVIRONMENT")
    print("      Type 'exit' or 'quit' to terminate session")
    print("=" * 55 + "\n")

    loop = asyncio.get_event_loop()

    # Pending confirmation state
    pending_confirmation = {"active": False, "state": None}

    CONFIRMATION_PHRASES = {
        "yes",
        "yes go ahead",
        "proceed",
        "go ahead",
        "do it",
        "confirm",
        "approved",
        "run it",
        "sure",
        "ok go ahead",
        "yeah",
        "yep",
        "affirmative",
    }
    DENIAL_PHRASES = {
        "no",
        "cancel",
        "stop",
        "don't",
        "abort",
        "nevermind",
        "never mind",
        "no thanks",
    }

    while True:
        try:
            user_input = input("👤 You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nFRIDAY: Goodbye.")
            break

        if user_input.lower() in {"exit", "quit"}:
            print("FRIDAY: Shutting down interface session.")
            break

        if not user_input:
            continue

        log_user(user_input)

        # ── Confirmation flow ─────────────────────────────────────
        if pending_confirmation["active"]:
            if user_input.lower().strip() in CONFIRMATION_PHRASES:
                print("🔄 [Resuming Agent Loop...]")
                saved_state = pending_confirmation["state"]
                pending_confirmation = {"active": False, "state": None}

                agent_start = time.perf_counter()
                from brain.llm import history as chat_history
                # Pass active history state through confirmation resumption
                response = loop.run_until_complete(
                    run_agent(
                        saved_state["goal"],
                        resume_state=saved_state,
                        chat_history=chat_history,
                    )
                )
                agent_latency = (time.perf_counter() - agent_start) * 1000
                print(f"⏱️  [Metrics] Total Agent Loop Runtime: {agent_latency:.2f}ms")

                if response.get("type") == "needs_confirmation":
                    pending_confirmation["active"] = True
                    pending_confirmation["state"] = response.get("pending_state")
                    print(
                        f"💬 FRIDAY: {response.get('content', 'Should I proceed?')}\n"
                    )
                else:
                    print(f"💬 FRIDAY: {response.get('content', 'Done.')}\n")
                    chat_history.append({"role": "user", "content": saved_state["goal"]})
                    chat_history.append({
                        "role": "assistant",
                        "content": json.dumps({"type": "reply", "content": response.get("content") or response.get("message") or "Done Sir."})
                    })

                log_response(response)
                loop.run_until_complete(store(f"User: {user_input}"))
                continue

            elif user_input.lower().strip() in DENIAL_PHRASES:
                pending_confirmation = {"active": False, "state": None}
                print("💬 FRIDAY: Understood Sir, cancelled.\n")
                loop.run_until_complete(store(f"User: {user_input}"))
                continue

            else:
                # Unrelated input — clear out stale state
                pending_confirmation = {"active": False, "state": None}

        # ── Normal routing ────────────────────────────────────────
        if is_complex(user_input):
            print("🧠 [Routing] Sent to Agent Loop Core...")

            from brain.llm import history as chat_history

            agent_start = time.perf_counter()
            response = loop.run_until_complete(
                run_agent(user_input, chat_history=chat_history)
            )
            agent_latency = (time.perf_counter() - agent_start) * 1000

            print(f"⏱️  [Metrics] Total Agent Loop Runtime: {agent_latency:.2f}ms")

            if response.get("type") == "needs_confirmation":
                pending_confirmation["active"] = True
                pending_confirmation["state"] = response.get("pending_state")
                print(f"💬 FRIDAY: {response.get('content', 'Should I proceed?')}\n")
            else:
                print(f"💬 FRIDAY: {response.get('content', 'Done.')}\n")
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({
                    "role": "assistant",
                    "content": json.dumps({"type": "reply", "content": response.get("content") or response.get("message") or "Done Sir."})
                })
        else:
            # Single-Shot Core Route
            llm_start = time.perf_counter()
            response = chat(user_input)
            llm_latency = (time.perf_counter() - llm_start) * 1000
            handle_manual_single_shot(response, llm_latency)

        log_response(response)
        loop.run_until_complete(store(f"User: {user_input}"))


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "manual"

    if mode == "auto":
        run_auto()
    else:
        run_manual()
