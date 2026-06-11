import queue
import threading
import asyncio
import time
from voice.stt import listen, transcribe
from voice.tts import generate, play
from brain.llm import chat
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

# =========================================================
# ROUTING
# =========================================================


def _is_complex_task(text: str) -> bool:
    """
    Decides whether to route through the agent loop or single-shot chat.
    Simple heuristic — replace with a router model later.
    """
    text_lower = text.lower().strip()

    simple_signals = [
        "open ",
        "close ",
        "play ",
        "what time",
        "who is",
        "where is",
        "how are you",
        "what is",
        "set a",
        "pause",
        "stop",
        "volume",
        "skip",
        "next",
    ]
    if any(text_lower.startswith(s) for s in simple_signals):
        return False

    complex_signals = [
        "and then",
        "after that",
        "first ",
        "step by step",
        "push",
        "commit",
        "deploy",
        "research",
        "find and",
        "open and",
        "search and",
        "write and",
        "create and",
        "help me",
        "figure out",
        "work out",
        "can you",
        "go to",
        "navigate to",
        "open chrome and",
    ]
    if any(s in text_lower for s in complex_signals):
        return True

    return False


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
    friday_done.clear()
    rtype = response.get("type")

    if rtype == "reply":
        log_response(response)
        text_queue.put(response.get("content", ""))

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

        # Route the input dynamically based on complexity metrics
        if _is_complex_task(text):
            log_system("main", "Routing to multi-step agent core.")
            response = await run_agent(text)
        else:
            response = await asyncio.to_thread(chat, text)

        # Let handle_response handle clean terminal logging inherently
        await handle_response(response)
        asyncio.create_task(store(f"User: {text}"))

        await asyncio.sleep(0.01)


if __name__ == "__main__":
    generator_thread = threading.Thread(target=tts_generator_worker, daemon=True)
    player_thread = threading.Thread(target=tts_player_worker, daemon=True)

    generator_thread.start()
    player_thread.start()

    asyncio.run(assistant_loop())
