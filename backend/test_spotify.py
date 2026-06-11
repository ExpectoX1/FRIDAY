import time
import subprocess


def run_cmd(cmd_list):
    return subprocess.run(cmd_list, capture_output=True, text=True)


def main():
    print("=" * 50)
    print("FRIDAY WORKFLOW TEST — Universal Search Engine Match")
    print("=" * 50)

    # 1. Wake up Spotify and forcefully pass the clean text query to its background listener
    print("[STEP 1] Initializing background app state with query routing...")
    run_cmd(["open", "spotify:search:The Weeknd Blinding Lights"])
    time.sleep(
        1.2
    )  # Give the framework breathing room to complete the API search fetch

    # 2. Force application context to the foreground
    run_cmd(["osascript", "-e", 'tell application "Spotify" to activate'])
    time.sleep(0.3)

    # 3. Inject a native macOS keyboard return stroke directly into the active app layer
    print("[STEP 2] Deploying hardware execution signal...")
    script_play = """
    tell application "System Events"
        tell process "Spotify"
            key code 36 -- Hardware Return key to fire whatever is highlighted at top of search
        end tell
    end tell
    """

    res = run_cmd(["osascript", "-e", script_play])

    if "error" in res.stderr.lower():
        print("  ⚠️ System Events blocked. Attempting background toggle fallback...")
        # Fallback: Send a raw spacebar event if focus alignment was slightly off
        run_cmd(["osascript", "-e", 'tell application "Spotify" to play'])
    else:
        print("  ✅ Execution signal dispatched cleanly.")

    print("\n" + "=" * 50)
    print("WORKFLOW SEQUENCE DEPLOYED")
    print("=" * 50)


if __name__ == "__main__":
    main()
