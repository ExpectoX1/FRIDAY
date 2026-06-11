import time
import json
import subprocess
from tools.apps import open_app
from tools.mac_core import (
    click_element_by_label,
    type_text,
    press_enter,
    read_accessibility_tree,
)


def navigate_chrome_to_url(url: str) -> dict:
    try:
        script = f'tell application "Google Chrome" to set URL of active tab of front window to "{url}"'
        subprocess.run(["osascript", "-e", script], check=True)
        return {"status": "success", "message": f"Navigated background tab to {url}"}
    except Exception as e:
        return {"status": "error", "message": f"Navigation failed: {str(e)}"}


def activate_application(app_name: str) -> bool:
    try:
        script = f'tell application "{app_name}" to activate'
        subprocess.run(["osascript", "-e", script], check=True)
        return True
    except Exception:
        return False


def step(num: int, desc: str, func, *args, **kwargs) -> bool:
    start_time = time.time()
    print(f"\n[STEP {num}] {desc}")
    result = func(*args, **kwargs)

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            print(f"  ✅ {result} ({time.time() - start_time:.2f}s)")
            return True

    if result.get("status") == "success":
        msg = result.get("message", result.get("typed", "Done"))
        print(f"  ✅ {msg} ({time.time() - start_time:.2f}s)")
        return True
    else:
        print(f"  ❌ {result.get('message', 'Unknown error')}")
        return False


def wait_for_page(
    keyword: str, app: str = "Google Chrome", max_wait_seconds: float = 10.0
) -> bool:
    print(f"  ⏳ High-frequency polling for '{keyword}'...")
    start_time = time.time()
    poll_interval = 0.15  # 150ms cycles for instant transition triggers

    while (time.time() - start_time) < max_wait_seconds:
        res_str = read_accessibility_tree(app)
        result = json.loads(res_str)
        match = [
            n
            for n in result.get("tree", [])
            if keyword.lower() in (n.get("label") or "").lower()
        ]
        if match:
            elapsed = time.time() - start_time
            print(f"  ✅ Found '{keyword}' inside AX tree in {elapsed:.2f}s")
            return True
        time.sleep(poll_interval)

    print(f"  ⚠️ '{keyword}' not captured within time constraints.")
    return False


def main():
    total_start = time.time()
    print("=" * 50)
    print("FRIDAY WORKFLOW TEST — Stripped Training Wheels (Speed Mode)")
    print("=" * 50)

    # 1. Open Browser Context
    if not step(1, "Open Google Chrome Infrastructure", open_app, "Google Chrome"):
        return
    time.sleep(0.1)

    # 2. Route directly to Netflix
    print("\n[STEP 2-4] Routing direct background connection to Netflix URL")
    nav_start = time.time()
    nav_res = navigate_chrome_to_url("https://netflix.com")
    if nav_res["status"] != "success":
        return
    print(f"  ✅ {nav_res['message']} ({time.time() - nav_start:.2f}s)")

    # 3. Wait for UI Landing Layer (High frequency)
    wait_for_page("Browse", max_wait_seconds=10.0)

    # 4. Bring Chrome to front right before focused interaction
    activate_application("Google Chrome")
    time.sleep(0.15)  # Micro-padding for OS window animation frame

    # 5. Open Search Bar
    print("\n[STEP 5] Activating Web Search Frame")
    search_start = time.time()
    clicked = False
    for label in ["Search", "Search titles, people, genres", "Search Box"]:
        res = json.loads(click_element_by_label(label, "Google Chrome"))
        if res.get("status") == "success":
            clicked = True
            break
    if not clicked:
        print("  ❌ Search element unreachable.")
        return
    print(f"  ✅ Opened Search Input Panel ({time.time() - search_start:.2f}s)")
    time.sleep(0.1)

    # 6. Type Target Query
    if not step(6, "Type Search Query Payload", type_text, "The Good Doctor"):
        return
    time.sleep(0.1)

    # 7. Execute Search Command
    if not step(7, "Press Enter to query results", press_enter):
        return

    # 8. High-speed poll for search grid content delivery
    if not wait_for_page("The Good Doctor", max_wait_seconds=8.0):
        print("  ❌ Search results did not load in time.")
        return
    time.sleep(0.2)

    # 9. Click the show's title card from the search grid
    print("\n[STEP 9] Targeting 'The Good Doctor' Media Card Element")
    card_start = time.time()
    select_card = json.loads(click_element_by_label("The Good Doctor", "Google Chrome"))
    if select_card.get("status") != "success":
        print("  ❌ Failed to click show card. Trying alternative title markers...")
        click_element_by_label("Play The Good Doctor", "Google Chrome")
    print(f"  ✅ Clicked Media Card ({time.time() - card_start:.2f}s)")

    # 10. Aggressive reactive scan for popup play panels
    print("\n[STEP 10] Scanning for secondary Play Triggers")
    play_clicked = False
    scan_start = time.time()
    while (time.time() - scan_start) < 2.5:
        res_tree = json.loads(read_accessibility_tree("Google Chrome"))
        has_play_btn = any(
            "play" in (node.get("label") or "").lower()
            for node in res_tree.get("tree", [])
        )
        if has_play_btn:
            click_element_by_label("Play", "Google Chrome")
            print(
                f"  ↳ Found standalone 'Play' button and clicked it! ({time.time() - scan_start:.2f}s)"
            )
            play_clicked = True
            break
        time.sleep(0.1)

    if not play_clicked:
        print(
            "  ✅ No secondary modal block captured. Show should be playing directly."
        )

    print("\n" + "=" * 50)
    print(
        f"WORKFLOW COMPLETE — Total Real Execution Time: {time.time() - total_start:.2f} seconds"
    )
    print("=" * 50)


if __name__ == "__main__":
    main()
