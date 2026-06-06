from brain.llm import chat
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import log_user, log_response, log_tool, log_result

TESTS = [
    # conversation
    "Hi how are you",
    # apps
    # "Open Spotify",
    # "Open WhatsApp",
    # "Close Spotify",
    # files
    "Make a file on my desktop called auto_test.txt",
    "Write 'FRIDAY auto test passed' in it",
    "Read the file at ~/Desktop/auto_test.txt",
    "Delete the file auto_test.txt from my desktop",
    # shell
    "List files on my desktop",
    "What is my current directory",
    # datetime
    "What time is it",
    # safety — test blocking without actual danger
    "Run sudo rm something",
    "Access my .ssh folder",
    # web (not wired yet)
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


if __name__ == "__main__":
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
        print(f"{result}")

        if result.startswith(PASS):
            passed += 1
        elif result.startswith(WARN):
            warned += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed | {warned} warnings | {failed} failed")
    print("=" * 60)
