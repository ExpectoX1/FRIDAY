import sys
from brain.llm import chat
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import log_user, log_response, log_tool, log_result

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
]

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"


def handle_and_report(response: dict) -> str:
    rtype = response.get("type")

    if rtype == "reply":
        return f"{PASS} REPLY: {response.get('content', '')[:80]}"

    elif rtype == "tool":
        name = response.get("name")
        args = response.get("args", {})
        tool = get_tool(name)

        if tool is None:
            return f"{FAIL} UNKNOWN TOOL: {name}"

        if tool["function"] is None:
            return f"{WARN} NOT WIRED: {name}"

        if name == "run_shell":
            result = executor_run(args.get("command", ""))
        else:
            result = tool["function"](**args)

        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            return f"{WARN} NEEDS CONFIRMATION: {result.replace('NEEDS_CONFIRMATION:', '').strip()}"

        return f"{PASS} TOOL: {name} → {str(result)[:80]}"

    return f"{FAIL} UNKNOWN RESPONSE TYPE"


def handle_manual(response: dict):
    rtype = response.get("type")

    if rtype == "reply":
        print(f"FRIDAY: {response.get('content')}\n")

    elif rtype == "tool":
        name = response.get("name")
        args = response.get("args", {})
        print(f"[TOOL] {name} → {args}")

        tool = get_tool(name)

        if tool is None:
            print(f"[ERROR] No tool called {name}\n")
            return

        if tool["function"] is None:
            print(f"[NOT WIRED] {name}\n")
            return

        if name == "run_shell":
            result = executor_run(args.get("command", ""))
        else:
            result = tool["function"](**args)

        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            command = result.replace("NEEDS_CONFIRMATION:", "").strip()
            print(f"[CONFIRMATION NEEDED] {command}")
            confirm = input("Approve? (yes/no): ").strip().lower()
            if confirm == "yes":
                from sandbox.executor import execute

                result = execute(command)
            else:
                print("[CANCELLED]\n")
                return

        print(f"[RESULT] {result}\n")


def run_auto():
    print("=" * 60)
    print("FRIDAY AUTO TEST")
    print("=" * 60)

    passed = 0
    warned = 0
    failed = 0

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


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "manual"

    if mode == "auto":
        run_auto()
    else:
        run_manual()
