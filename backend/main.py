import queue
import threading
import asyncio
import time
import json
import re
import random
import os
import sounddevice as sd
from voice.stt import listen, transcribe, rms, _input_device, SAMPLE_RATE, BLOCK_DURATION
from voice.tts import generate, play
from brain.llm import chat, is_complex
from brain.agent import run_agent
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import *
from memory.store import store
from memory.retrieve import search_memory

text_queue = queue.Queue()
audio_queue = queue.Queue()
is_speaking = threading.Event()
friday_done = threading.Event()
friday_done.set()

# ── Barge-in (interrupt FRIDAY while she's speaking) ─────────────────────────
# While speaking, a monitor watches the mic; sustained input LOUDER than her
# own speaker bleed counts as an interruption -> stop playback and listen.
# Threshold is well above the normal speech threshold to avoid self-triggering
# on her own voice; tune with FRIDAY_BARGE_THRESHOLD (lower = more sensitive).
# Works best with headphones; set FRIDAY_BARGE_IN=0 to disable.
BARGE_IN = os.getenv("FRIDAY_BARGE_IN", "1") == "1"
BARGE_THRESHOLD = float(os.getenv("FRIDAY_BARGE_THRESHOLD", "0.06"))
BARGE_BLOCKS = 2  # ~0.5s of sustained loud input before we treat it as a barge-in
interrupt_event = threading.Event()

LLM_INTERPRET = {"search_memory", "search_web"}

# Spoken immediately when a request routes to the multi-step agent, so the user
# hears feedback within ~1s instead of waiting out several seconds of silence.
AGENT_ACK_PHRASES = [
    "On it, Sir.",
    "Let me look into that.",
    "Working on it, Boss.",
    "Give me a moment.",
    "Right away, Sir.",
]

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


def _split_sentences(text: str) -> list[str]:
    """Split a reply into speakable chunks at sentence boundaries, merging
    very short fragments so we don't get choppy one-word utterances."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, buf = [], ""
    for p in parts:
        if not p:
            continue
        buf = f"{buf} {p}".strip() if buf else p
        if len(buf) >= 40:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def enqueue_speech(text: str):
    """Queue a reply for TTS sentence-by-sentence. The generator/player workers
    pipeline these, so FRIDAY starts speaking the first sentence while later
    ones are still being synthesized — lower time-to-first-audio on long replies."""
    if not text:
        return
    for chunk in _split_sentences(str(text)):
        text_queue.put(chunk)


# =========================================================
# TTS WORKERS
# =========================================================


def _drain_queue(q: queue.Queue):
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


def barge_in_monitor():
    """While FRIDAY is speaking, watch the mic and interrupt on sustained loud
    input (the user talking over her). Only runs during speech, so it never
    contends with the main listen() stream."""
    if not BARGE_IN:
        return
    block = int(SAMPLE_RATE * BLOCK_DURATION)
    while True:
        is_speaking.wait()  # idle until she starts speaking
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=block, device=_input_device(),
            )
            stream.start()
        except Exception:
            time.sleep(0.2)
            continue
        loud = 0
        while is_speaking.is_set():
            try:
                chunk, _ = stream.read(block)
            except Exception:
                break
            if rms(chunk.flatten()) > BARGE_THRESHOLD:
                loud += 1
                if loud >= BARGE_BLOCKS:
                    log_system("main", "Barge-in — stopping playback to listen.")
                    interrupt_event.set()
                    sd.stop()
                    _drain_queue(audio_queue)
                    _drain_queue(text_queue)
                    is_speaking.clear()
                    friday_done.set()
                    break
            else:
                loud = 0
        stream.stop()
        stream.close()


def tts_generator_worker():
    while True:
        text = text_queue.get()
        if text is None:
            break
        friday_done.clear()
        audio = generate(text)
        if audio is not None and not interrupt_event.is_set():
            audio_queue.put(audio)
        text_queue.task_done()


def tts_player_worker():
    while True:
        audio = audio_queue.get()
        if audio is None:
            break
        if interrupt_event.is_set():  # interrupted — drop pending audio
            audio_queue.task_done()
            continue
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
        enqueue_speech(response.get("content", ""))

    elif rtype == "needs_confirmation":
        # Store pending state and ask user
        pending_confirmation["active"] = True
        pending_confirmation["state"] = response.get("pending_state")
        log_system("main", "Pending confirmation stored.")
        enqueue_speech(response.get("content", "Should I proceed Sir?"))

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
                    prompt = f"Based on our conversation and this memory context, give a natural, concise spoken answer to what the user just asked. Do NOT ask what they want — just answer directly.\n\nMemory:\n{result}"
                elif name == "search_web":
                    prompt = f"Based on our conversation and these web search results, give the user a natural, concise spoken answer to what they just asked. Lead with the key facts. Do NOT ask what they want — just summarize and answer directly.\n\nResults:\n{result}"
                follow_up = await asyncio.to_thread(chat, prompt)
                enqueue_speech(follow_up.get("content", str(result)))
            except Exception as e:
                log_error(f"LLM follow-up failed: {e}")
                enqueue_speech(str(result)[:200])
            return

        if isinstance(result, dict):
            enqueue_speech(
                result.get("message") or result.get("content") or "Done Sir."
            )
        else:
            enqueue_speech(result if result else "Done Sir.")

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

    # Warm every cold path in parallel while the startup line plays, so the
    # first real request doesn't pay the model-load tax: brain (gemma4),
    # router (qwen3b), and the memory stack (GLiNER + Neo4j).
    await asyncio.gather(
        asyncio.to_thread(chat, "System initialization ping."),
        asyncio.to_thread(is_complex, "warm up the router"),
        asyncio.to_thread(search_memory, "warm up"),
    )
    log_system("main", "Models warmed (brain, router, memory).")

    ready_audio = generate("All systems online Sir, ready when you are.")
    if ready_audio is not None:
        audio_queue.put(ready_audio)

    await asyncio.sleep(2)

    while True:
        while not friday_done.is_set():
            await asyncio.sleep(0.05)

        # Fresh turn — clear any prior interrupt so the workers aren't gated.
        interrupt_event.clear()

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
            # Immediate audible ack so the user isn't met with silence while the
            # multi-step loop runs (several seconds of inference). Plays while
            # run_agent works.
            enqueue_speech(random.choice(AGENT_ACK_PHRASES))
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
    barge_thread = threading.Thread(target=barge_in_monitor, daemon=True)

    generator_thread.start()
    player_thread.start()
    barge_thread.start()

    asyncio.run(assistant_loop())
