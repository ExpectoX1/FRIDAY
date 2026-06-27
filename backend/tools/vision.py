import os
import subprocess
import ollama

# qwen2.5vl:3b reads the screen accurately (incl. on-screen text) and is fast
# (~1s warm, vs ~5s for gemma3:12b) and small enough to coexist with the gemma4
# brain without thrashing memory. Override with FRIDAY_VISION_MODEL.
VISION_MODEL = os.getenv("FRIDAY_VISION_MODEL", "qwen2.5vl:3b")
SCREENSHOT_PATH = "/tmp/friday_vision.png"

# Unload the vision model shortly after use so it doesn't sit in memory evicting
# the gemma4 brain (vision is occasional; the brain is hot every turn).
VISION_KEEP_ALIVE = "60s"


def look_at_screen(question: str = "Describe what is currently on the screen.") -> dict:
    """Capture the screen and have a local vision model answer a question about
    it. Lets FRIDAY actually 'see' — what's open, whether something looks right,
    reading on-screen text, etc."""
    try:
        subprocess.run(
            ["screencapture", "-x", SCREENSHOT_PATH], check=True, timeout=10
        )
        # Downscale the (often Retina) screenshot — smaller image = much faster
        # vision inference, with negligible loss for describing the screen.
        subprocess.run(
            ["sips", "-Z", "1280", SCREENSHOT_PATH], capture_output=True, timeout=10
        )

        prompt = (
            "You are FRIDAY's vision system looking at the user's Mac screen. "
            "Answer concisely in 1-3 conversational sentences.\n\n"
            f"Question: {question}"
        )
        response = ollama.chat(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": prompt, "images": [SCREENSHOT_PATH]}],
            keep_alive=VISION_KEEP_ALIVE,
        )
        return {"status": "success", "message": response.message.content.strip()}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Screen capture timed out, Sir."}
    except Exception as e:
        return {"status": "error", "message": f"I couldn't analyze the screen: {e}"}
