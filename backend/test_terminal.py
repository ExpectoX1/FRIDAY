import sys
import asyncio
from brain.llm import chat
from tools.registry import get_tool
from sandbox.executor import run as executor_run, execute
from logger import log_user, log_response, log_tool, log_result, log_error
from memory.store import store

# =========================================================
# CONSTANTS
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
# SHARED TOOL EXECUTOR
# =========================================================


def execute_tool(name: str, args: dict) -> str | None:
    tool = get_tool(name)

    if tool is None:
        return f"I don't have a tool called {name} yet Sir."

    if tool["function"] is None:
        return f"The {name} tool isn't wired up yet Sir."

    if name == "run_shell":
        return executor_run(args.get("command", ""))

    return tool["function"](**args)


# =========================================================
# HANDLE RESPONSE — MANUAL MODE
# =========================================================


def handle_manual(response: dict):
    rtype = response.get("type")

    if rtype == "reply":
        print(f"FRIDAY: {response.get('content')}\n")
        return

    if rtype == "tool":
        name = response.get("name")
        args = response.get("args", {})

        log_tool("tool", name, args)
        print(f"[TOOL] {name} → {args}")

        result = execute_tool(name, args)

        if result is None:
            print("[RESULT] Done Sir.\n")
            return

        log_result("tool", result)

        # confirmation flow
        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            command = result.replace("NEEDS_CONFIRMATION:", "").strip()
            print(f"[CONFIRMATION NEEDED] {command}")
            confirm = input("Approve? (yes/no): ").strip().lower()
            if confirm == "yes":
                result = execute(command)
                print(f"[RESULT] {result}\n")
            else:
                print("[CANCELLED]\n")
            return

        # memory results go back through LLM for natural response
        if name == "search_memory" and result:
            print(f"[MEMORY] {result}")
            follow_up = chat(
                f"Using this memory context, answer the user's last question naturally and concisely:\n{result}"
            )
            print(f"FRIDAY: {follow_up.get('content', result)}\n")
            return

        print(f"[RESULT] {result}\n")
        return

    log_error(response.get("content", "Unknown response type"))
    print(f"[ERROR] {response.get('content', 'Something went wrong')}\n")


# =========================================================
# HANDLE RESPONSE — AUTO TEST MODE
# =========================================================


def handle_and_report(response: dict) -> str:
    rtype = response.get("type")

    if rtype == "reply":
        return f"{PASS} REPLY: {response.get('content', '')[:80]}"

    if rtype == "tool":
        name = response.get("name")
        args = response.get("args", {})
        result = execute_tool(name, args)

        if result is None:
            return f"{PASS} TOOL: {name} → Done"

        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            return f"{WARN} NEEDS CONFIRMATION: {result.replace('NEEDS_CONFIRMATION:', '').strip()}"

        if name == "search_memory" and result:
            follow_up = chat(f"Using this memory context, answer naturally:\n{result}")
            return f"{PASS} MEMORY: {follow_up.get('content', result)[:80]}"

        return f"{PASS} TOOL: {name} → {str(result)[:80]}"

    return f"{FAIL} UNKNOWN RESPONSE TYPE"


# =========================================================
# RUN MODES
# =========================================================


def run_auto():
    print("=" * 60)
    print("FRIDAY AUTO TEST")
    print("=" * 60)

    passed = warned = failed = 0

    for test in TESTS:
        print(f"\nYou: {test}")
        log_user(test)
        response = chat(test)
        log_response(response)
        result = handle_and_report(response)
        print(result)

        if result.startswith(PASS):
            passed += 1
        elif result.startswith(WARN):
            warned += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed | {warned} warnings | {failed} failed")
    print("=" * 60)


def run_manual():
    print("FRIDAY TERMINAL MODE")
    print("Type 'exit' to quit\n")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit"}:
            print("FRIDAY: Goodbye Sir.")
            break

        if not user_input:
            continue

        log_user(user_input)
        response = chat(user_input)
        log_response(response)
        handle_manual(response)
        asyncio.run(store(f"Siddharth: {user_input}"))


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "manual"

    if mode == "auto":
        run_auto()
    else:
        run_manual()
