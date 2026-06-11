import queue
import threading
import asyncio
import time
import json
from voice.stt import listen, transcribe
from voice.tts import generate, play
from brain.llm import chat, is_complex
from brain.agent import run_agent
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import *
from memory.store import store

text_queue = queue.Queue()
audio_queue = queue.Queue()
is_speaking = threading.Event()
friday_done = threading.Event()
friday_done.set()

LLM_INTERPRET = {"search_memory", "search_web"}

# Pending confirmation state — Option B proper implementation
pending_confirmation: dict = {
    "active": False,
    "state": None,
}

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


# =========================================================
# ROUTING
# =========================================================





def _is_confirmation(text: str) -> bool:
    return text.lower().strip() in CONFIRMATION_PHRASES


def _is_denial(text: str) -> bool:
    return text.lower().strip() in DENIAL_PHRASES


# =========================================================
# TTS WORKERS
# =========================================================


def tts_generator_worker():
    while True:
        text = text_queue.get()
        if text is None:
            break
        friday_done.clear()
        audio = generate(text)
        if audio is not None:
            audio_queue.put(audio)
        text_queue.task_done()


def tts_player_worker():
    while True:
        audio = audio_queue.get()
        if audio is None:
            break
        is_speaking.set()
        friday_done.clear()
        play(audio)
        audio_queue.task_done()
        if audio_queue.empty() and text_queue.empty():
            is_speaking.clear()
            time.sleep(0.5)
            friday_done.set()


# =========================================================
# RESPONSE HANDLER
# =========================================================


async def handle_response(response: dict):
    global pending_confirmation
    friday_done.clear()
    rtype = response.get("type")

    if rtype == "reply":
        log_response(response)
        text_queue.put(response.get("content", ""))

    elif rtype == "needs_confirmation":
        # Store pending state and ask user
        pending_confirmation["active"] = True
        pending_confirmation["state"] = response.get("pending_state")
        log_system("main", "Pending confirmation stored.")
        text_queue.put(response.get("content", "Should I proceed Sir?"))

    elif rtype == "tool":
        name = response.get("name")
        args = response.get("args", {})

        log_tool("tool", name, args)
        tool = get_tool(name)

        if tool is None:
            text_queue.put(f"I don't have a tool called {name} yet Sir.")
            return

        if tool["function"] is None:
            text_queue.put(f"The {name} tool isn't wired up yet Sir.")
            return

        try:
            if name == "run_shell":
                result = await asyncio.to_thread(executor_run, args.get("command", ""))
            else:
                result = await asyncio.to_thread(tool["function"], **args)
        except TypeError as e:
            log_error(f"Tool {name} bad args {args}: {e}")
            text_queue.put(f"Something went wrong Sir, bad arguments for {name}.")
            return
        except Exception as e:
            log_error(f"Tool {name} failed: {e}")
            text_queue.put(f"That didn't work Sir, {name} ran into an error.")
            return

        log_result("tool", result)

        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            command = result.replace("NEEDS_CONFIRMATION:", "").strip()
            text_queue.put(
                f"Sir I need your approval to run: {command}. Should I proceed?"
            )
            return

        if name in LLM_INTERPRET and result:
            try:
                if name == "search_memory":
                    prompt = f"Using this memory context, answer the user's last question naturally:\n{result}"
                elif name == "search_web":
                    prompt = f"Using these search results, answer the user's question naturally:\n{result}"
                follow_up = await asyncio.to_thread(chat, prompt)
                text_queue.put(follow_up.get("content", str(result)))
            except Exception as e:
                log_error(f"LLM follow-up failed: {e}")
                text_queue.put(str(result)[:200])
            return

        if isinstance(result, dict):
            text_queue.put(
                result.get("message") or result.get("content") or "Done Sir."
            )
        else:
            text_queue.put(result if result else "Done Sir.")

    else:
        log_error(response.get("content", "Unknown error"))
        text_queue.put(response.get("content", "Something went wrong Sir."))


# =========================================================
# MAIN LOOP
# =========================================================


async def assistant_loop():
    global pending_confirmation

    log_system("main", "FRIDAY ONLINE")

    startup_audio = generate("Starting systems Sir, getting everything online.")
    if startup_audio is not None:
        audio_queue.put(startup_audio)

    await asyncio.to_thread(chat, "System initialization ping.")

    ready_audio = generate("All systems online Sir, ready when you are.")
    if ready_audio is not None:
        audio_queue.put(ready_audio)

    await asyncio.sleep(2)

    while True:
        while not friday_done.is_set():
            await asyncio.sleep(0.05)

        audio = await asyncio.to_thread(listen)
        text = await asyncio.to_thread(transcribe, audio)

        if not text.strip() or len(text.strip()) < 3:
            continue

        print(f"You: {text}")
        log_user(text)

        # ── Confirmation flow ─────────────────────────────────────────
        if pending_confirmation["active"]:
            if _is_confirmation(text):
                log_system("main", "Confirmation received — resuming agent.")
                saved_state = pending_confirmation["state"]
                pending_confirmation = {"active": False, "state": None}
                from brain.llm import history as chat_history
                response = await run_agent(
                    saved_state["goal"],
                    resume_state=saved_state,
                    chat_history=chat_history,
                )
                await handle_response(response)
                if response.get("type") == "reply":
                    chat_history.append({"role": "user", "content": saved_state["goal"]})
                    chat_history.append({
                        "role": "assistant",
                        "content": json.dumps({"type": "reply", "content": response.get("content") or response.get("message") or "Done Sir."})
                    })
                asyncio.create_task(store(f"User: {text}"))
                continue

            elif _is_denial(text):
                log_system("main", "Confirmation denied — cancelling.")
                pending_confirmation = {"active": False, "state": None}
                text_queue.put("Understood Sir, cancelled.")
                asyncio.create_task(store(f"User: {text}"))
                continue

            else:
                # User said something unrelated — clear confirmation, proceed normally
                log_system("main", "Unrelated input — clearing pending confirmation.")
                pending_confirmation = {"active": False, "state": None}

        # ── Normal routing ────────────────────────────────────────────
        if is_complex(text):
            log_system("main", "Routing to agent loop.")
            from brain.llm import history as chat_history
            response = await run_agent(text, chat_history=chat_history)
            if response.get("type") == "reply":
                chat_history.append({"role": "user", "content": text})
                chat_history.append({
                    "role": "assistant",
                    "content": json.dumps({"type": "reply", "content": response.get("content") or response.get("message") or "Done Sir."})
                })
        else:
            response = await asyncio.to_thread(chat, text)

        log_response(response)
        await handle_response(response)
        asyncio.create_task(store(f"User: {text}"))

        await asyncio.sleep(0.01)


if __name__ == "__main__":
    generator_thread = threading.Thread(target=tts_generator_worker, daemon=True)
    player_thread = threading.Thread(target=tts_player_worker, daemon=True)

    generator_thread.start()
    player_thread.start()

    asyncio.run(assistant_loop())
