import queue
import threading
import asyncio
import time
from voice.stt import listen, transcribe
from voice.tts import generate, play
from brain.llm import chat
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import *
from memory.store import store

text_queue = queue.Queue()
audio_queue = queue.Queue()
is_speaking = threading.Event()
friday_done = threading.Event()
friday_done.set()  # starts as done


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


def handle_response(response: dict):
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

        if name == "run_shell":
            result = executor_run(args.get("command", ""))
        else:
            result = tool["function"](**args)

        log_result("tool", result)

        if isinstance(result, str) and result.startswith("NEEDS_CONFIRMATION:"):
            command = result.replace("NEEDS_CONFIRMATION:", "").strip()
            text_queue.put(
                f"Sir I need your approval to run: {command}. Should I proceed?"
            )
            return

        # memory results go back through LLM for natural response
        if name == "search_memory" and result:
            follow_up = chat(
                f"Using this memory context, answer the user's last question naturally and concisely:\n{result}"
            )
            text_queue.put(follow_up.get("content", result))
            return

        text_queue.put(result if result else "Done Sir.")

    else:
        log_error(response.get("content", "Unknown error"))
        text_queue.put(response.get("content", "Something went wrong Sir."))


async def assistant_loop():

    log_system("main", "FRIDAY ONLINE")

    # speak startup message while models load
    startup_audio = generate("Starting systems Sir, getting everything online.")
    if startup_audio is not None:
        audio_queue.put(startup_audio)

    # pre-warm Ollama while TTS plays
    from brain.llm import chat

    chat("test message friday")

    # ready
    ready_audio = generate("All systems online Sir, ready when you are.")
    if ready_audio is not None:
        audio_queue.put(ready_audio)

    await asyncio.sleep(4)
    while True:
        # wait until FRIDAY is completely done
        while not friday_done.is_set():
            await asyncio.sleep(0.05)

        audio = listen()
        text = transcribe(audio)

        if not text.strip() or len(text.strip()) < 3:
            continue

        print(f"You: {text}")
        log_user(text)
        response = chat(text)
        log_response(response)
        print(f"[RESPONSE] {response}")
        handle_response(response)
        asyncio.create_task(store(f"Siddharth: {text}"))

        await asyncio.sleep(0.01)


if __name__ == "__main__":
    generator_thread = threading.Thread(target=tts_generator_worker, daemon=True)
    player_thread = threading.Thread(target=tts_player_worker, daemon=True)

    generator_thread.start()
    player_thread.start()

    asyncio.run(assistant_loop())
