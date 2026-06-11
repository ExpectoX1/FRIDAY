import time
import json
import subprocess
from tools.apps import open_app
from tools.mac_core import (
    click_element_by_label,
    type_text,
    press_enter,
    get_frontmost_app,
    read_accessibility_tree,
)

# =========================================================
# BACKGROUND COMPATIBLE NAVIGATOR
# =========================================================


def navigate_chrome_to_url(url: str) -> dict:
    """Directly sets Chrome's active tab URL in the background, bypassing keystrokes."""
    try:
        script = f'tell application "Google Chrome" to set URL of active tab of front window to "{url}"'
        subprocess.run(["osascript", "-e", script], check=True)
        return {"status": "success", "message": f"Navigated background tab to {url}"}
    except Exception as e:
        return {"status": "error", "message": f"Navigation failed: {str(e)}"}


def activate_application(app_name: str) -> bool:
    """Forces global OS focus to the target app so it can safely receive keystrokes."""
    try:
        script = f'tell application "{app_name}" to activate'
        subprocess.run(["osascript", "-e", script], check=True)
        return True
    except Exception:
        return False


# =========================================================
# RUNTIME ENGINE LOGIC
# =========================================================


def step(num: int, desc: str, func, *args, **kwargs) -> bool:
    print(f"\n[STEP {num}] {desc}")
    result = func(*args, **kwargs)

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            print(f"  ✅ {result}")
            return True

    if result.get("status") == "success":
        print(f"  ✅ {result.get('message', result.get('typed', 'Done'))}")
        return True
    else:
        print(f"  ❌ {result.get('message', 'Unknown error')}")
        return False


def wait_for_page(keyword: str, app: str = "Google Chrome", max_wait: int = 12) -> bool:
    print(f"  ⏳ Waiting for '{keyword}' to appear in page context...")
    for i in range(max_wait):
        time.sleep(1)
        res_str = read_accessibility_tree(app)
        result = json.loads(res_str)

        # Scan tree labels safely
        match = [
            n
            for n in result.get("tree", [])
            if keyword.lower() in (n.get("label") or "").lower()
        ]
        if match:
            print(
                f"  ✅ Found '{keyword}' inside the active AX tree layer after {i+1}s"
            )
            return True
        print(f"  ⏳ Parsing live layout trees... ({i+1}s)")
    print(f"  ⚠️ '{keyword}' not captured within time constraints.")
    return False


def main():
    print("=" * 50)
    print("FRIDAY WORKFLOW TEST — Background Resilient Netflix Search")
    print("=" * 50)

    # Step 1 — Spin up Chrome container
    if not step(1, "Open Google Chrome Infrastructure", open_app, "Google Chrome"):
        return
    time.sleep(1.5)

    # Steps 2, 3, 4 Optimized — Native Background Navigation
    print("\n[STEP 2-4] Routing direct background connection to Netflix URL")
    nav_res = navigate_chrome_to_url("https://netflix.com")
    if nav_res["status"] != "success":
        print(f"  ❌ {nav_res['message']}")
        return
    print(f"  ✅ {nav_res['message']}")

    # Step 4c — Wait for Netflix DOM to stream into the accessibility interface
    # Netflix landing pages use "Sign In", profiles use "Search" or "Browse"
    loaded = wait_for_page("Sign In", max_wait=12) or wait_for_page(
        "Browse", max_wait=2
    )
    if not loaded:
        # Fallback check to let execution proceed if it's already sitting on the profile select screen
        print("  ⚠️ Continuing tree search sequence via custom fallback routing...")

    # Step 5 — Background Element Click targeting the magnifying glass
    print("\n[STEP 5] Locating and pressing Search Elements")
    clicked = False
    # Dynamic string mapping to match alternative localization formats across Netflix headers
    for label in [
        "Search titles, people, genres",
        "Search Box",
        "Search Netflix",
        "Search",
        "search",
    ]:
        result = json.loads(click_element_by_label(label, "Google Chrome"))
        if result.get("status") == "success":
            print(f"  ✅ Clicked Accessibility Node: '{label}'")
            clicked = True
            break
        print(f"  ↳ Node '{label}' not reachable, scanning layout alternatives...")

    if not clicked:
        print(
            "  ⚠️ Could not click search via accessibility. Injecting global focus fallback..."
        )
        activate_application("Google Chrome")
        time.sleep(0.3)

    # Step 6 — Safely route system typing context to Chrome text window bounds
    activate_application("Google Chrome")
    time.sleep(0.2)

    if not step(6, "Type Search Query Payload", type_text, "The Good Doctor"):
        return
    time.sleep(0.3)

    # Step 7 — Final Execution Trigger
    if not step(7, "Press Enter to execute query processing", press_enter):
        return

    print("\n" + "=" * 50)
    print("WORKFLOW SEQUENCE COMPLETE")
    print("=" * 50)


if __name__ == "__main__":
    main()
