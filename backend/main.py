import queue
import threading
import asyncio
import time
import json
import re
import random
import os
import subprocess
import sounddevice as sd
from voice.stt import listen, transcribe, rms, _input_device, SAMPLE_RATE, BLOCK_DURATION
from voice.tts import generate, play, generate_stream
from brain.llm import chat, chat_stream, is_complex
from brain.agent import run_agent
from tools.registry import get_tool
from sandbox.executor import run as executor_run
from logger import *
from memory.store import store
from memory.retrieve import search_memory
from bridge import state_bus, server as bridge_server
from proactive.scheduler import scheduler

text_queue = queue.Queue()
audio_queue = queue.Queue()
# Typed commands from the island (POST /api/input). The voice loop takes the
# next turn from here instead of the mic when something is queued.
typed_input_queue = queue.Queue()
is_speaking = threading.Event()
friday_done = threading.Event()
friday_done.set()

# ── Barge-in (interrupt FRIDAY while she's speaking) ─────────────────────────
# While speaking, a monitor watches the mic; sustained input LOUDER than her
# own speaker bleed counts as an interruption -> stop playback and listen.
# Threshold is well above the normal speech threshold to avoid self-triggering
# on her own voice; tune with FRIDAY_BARGE_THRESHOLD (lower = more sensitive).
# Default OFF: on laptop speakers her own voice bleeds into the mic and
# self-triggers the interrupt (no echo cancellation). Enable with headphones via
# FRIDAY_BARGE_IN=1; tune sensitivity with FRIDAY_BARGE_THRESHOLD.
BARGE_IN = os.getenv("FRIDAY_BARGE_IN", "0") == "1"
BARGE_THRESHOLD = float(os.getenv("FRIDAY_BARGE_THRESHOLD", "0.06"))
BARGE_BLOCKS = max(2, int(0.5 / BLOCK_DURATION))  # ~0.5s sustained loud input
interrupt_event = threading.Event()

LLM_INTERPRET = {"search_memory", "search_web", "read_page"}

# Spoken immediately when a request routes to the multi-step agent, so the user
# hears feedback within ~1s instead of waiting out several seconds of silence.
AGENT_ACK_PHRASES = [
    "On it, Sir.",
    "Let me look into that.",
    "Working on it, Boss.",
    "Give me a moment.",
    "Right away, Sir.",
]

# Quiet latency fillers. These are not answers; they are short, human-feeling
# cues used only when the model/tool path is taking long enough that silence
# would feel awkward.
THINKING_CUES = os.getenv("FRIDAY_THINKING_CUES", "1") == "1"
THINKING_CUE_FIRST_SEC = float(os.getenv("FRIDAY_THINKING_CUE_FIRST_SEC", "1.6"))
THINKING_CUE_SECOND_SEC = float(os.getenv("FRIDAY_THINKING_CUE_SECOND_SEC", "6.0"))
THINKING_CUE_PHRASES = [
    "Let me think.",
    "One moment.",
    "I'm checking.",
    "Let me see.",
    "I'm on it.",
]
THINKING_CUE_FOLLOWUPS = [
    "Still working on it.",
    "Almost there.",
    "I'm checking a little deeper.",
    "This may take a moment.",
]

# Pending confirmation state — Option B proper implementation
pending_confirmation: dict = {
    "active": False,
    "state": None,
}

# Set once the voice loop's asyncio loop is running, so the menu-bar thread can
# schedule approve/deny coroutines onto it via run_coroutine_threadsafe.
MAIN_LOOP = None

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





_AFFIRM_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "proceed", "confirm"}


def _normalize_reply(text: str) -> str:
    # STT adds trailing punctuation ("Yes.") which broke exact-match confirmation.
    return text.lower().strip().strip(".!?,").strip()


def _is_confirmation(text: str) -> bool:
    t = _normalize_reply(text)
    if not t:
        return False
    # Match known phrases, or any reply that simply starts with an affirmation
    # ("yes", "yes go for it", "yeah do it").
    return t in CONFIRMATION_PHRASES or t.split()[0] in _AFFIRM_WORDS


def _is_denial(text: str) -> bool:
    t = _normalize_reply(text)
    if not t:
        return False
    return t in DENIAL_PHRASES or t.split()[0] in {"no", "nope", "cancel", "stop", "abort"}


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


# What FRIDAY most recently spoke — used to discard mic input that is just her
# own voice bleeding back (e.g. when approval comes from the menu button while
# the voice loop is mid-listen and captures her reply).
_last_spoken = ""


def enqueue_speech(text: str):
    """Queue a reply for TTS sentence-by-sentence. The generator/player workers
    pipeline these, so FRIDAY starts speaking the first sentence while later
    ones are still being synthesized — lower time-to-first-audio on long replies."""
    global _last_spoken
    if not text:
        return
    _last_spoken = str(text)
    state_bus.set_state(replyPreview=str(text)[:200])
    for chunk in _split_sentences(str(text)):
        text_queue.put(chunk)


async def _thinking_cues(done: asyncio.Event, first_delay: float | None = None):
    """Speak at most two tiny cues while a turn is still processing.

    The cue is skipped if FRIDAY has already started speaking or TTS is queued,
    so it fills dead air without stepping on the real answer.
    """
    if not THINKING_CUES:
        return

    first = THINKING_CUE_FIRST_SEC if first_delay is None else first_delay
    schedule = [
        (first, THINKING_CUE_PHRASES),
        (THINKING_CUE_SECOND_SEC, THINKING_CUE_FOLLOWUPS),
    ]

    for delay, phrases in schedule:
        try:
            await asyncio.wait_for(done.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        if done.is_set():
            return
        if is_speaking.is_set() or not text_queue.empty() or not audio_queue.empty():
            continue
        enqueue_speech(random.choice(phrases))


def speak_proactive(text: str):
    """Make FRIDAY volunteer something the user didn't just ask for (a fired
    reminder/timer). Rides the normal TTS pipeline so it pipelines and obeys
    barge-in like any other reply. Called from the scheduler thread, so it must
    only touch thread-safe primitives — enqueue_speech does (queue + state bus)."""
    if not text:
        return
    log_system("proactive", f"Speaking proactively: {text}")
    state_bus.set_state("speaking", outcome="neutral", message="Reminder", replyPreview=text[:200])
    enqueue_speech(text)


def _is_self_echo(heard: str) -> bool:
    """True if the transcription is mostly FRIDAY's own last reply echoing back."""
    if not _last_spoken:
        return False
    hw = set(heard.lower().split())
    if len(hw) < 4:
        return False  # short commands are never treated as echo
    sw = set(_last_spoken.lower().split())
    return len(hw & sw) / len(hw) > 0.6


# =========================================================
# TTS WORKERS
# =========================================================


def _drain_queue(q: queue.Queue):
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


def _system_output_volume() -> int:
    """System output volume 0-100 (defaults to 50 if it can't be read)."""
    try:
        r = subprocess.run(
            ["osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True, text=True, timeout=2,
        )
        return max(0, min(100, int(r.stdout.strip())))
    except Exception:
        return 50


def _effective_barge_threshold() -> float:
    """Scale the barge-in threshold by speaker volume: louder speakers bleed more
    of FRIDAY's own voice into the mic, so the bar must rise to avoid her self-
    interrupting. 0% volume -> base; 100% -> 3x base."""
    return BARGE_THRESHOLD * (1 + 2 * _system_output_volume() / 100.0)


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
        threshold = _effective_barge_threshold()  # scaled to current volume
        loud = 0
        while is_speaking.is_set():
            try:
                chunk, _ = stream.read(block)
            except Exception:
                break
            if rms(chunk.flatten()) > threshold:
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
        for audio_chunk in generate_stream(text):
            if interrupt_event.is_set():
                break
            if audio_chunk is not None:
                audio_queue.put(audio_chunk)
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
        state_bus.set_state("speaking", message="Speaking...")
        play(audio)
        audio_queue.task_done()
        if audio_queue.empty() and text_queue.empty():
            is_speaking.clear()
            time.sleep(0.5)
            friday_done.set()
            state_bus.set_state("idle", message="", outcome="neutral")


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
        cmd = (response.get("pending_state") or {}).get("confirmed_command", "")
        state_bus.set_state(
            "approval_required", requiresApproval=True, pendingCommand=cmd,
            message=response.get("content", "Approve?"),
        )
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

        # Remember this result so the next turn can resolve "open it / that page /
        # the chords" against it (single-shot otherwise forgets tool output).
        from brain.llm import set_last_result
        set_last_result(name, result)

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
                elif name == "read_page":
                    prompt = f"Based on our conversation and the full text of this web page, give the user a natural, concise spoken answer to what they just asked. Lead with the key points. Do NOT ask what they want — just summarize and answer directly.\n\nPage:\n{result}"
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
        state_bus.set_state("error", outcome="error", message=response.get("content", "Something went wrong"))
        enqueue_speech(response.get("content", "Something went wrong Sir."))


# =========================================================
# MAIN LOOP
# =========================================================


async def approve_pending():
    """Resume a pending confirmation — called by either voice ('yes') or the
    menu-bar Approve button."""
    global pending_confirmation
    if not pending_confirmation["active"]:
        return
    log_system("main", "Confirmation approved — resuming agent.")
    saved_state = pending_confirmation["state"]
    pending_confirmation = {"active": False, "state": None}
    from brain.llm import history as chat_history
    response = await run_agent(
        saved_state["goal"], resume_state=saved_state, chat_history=chat_history
    )
    await handle_response(response)
    if response.get("type") == "reply":
        chat_history.append({"role": "user", "content": saved_state["goal"]})
        chat_history.append({
            "role": "assistant",
            "content": json.dumps({"type": "reply", "content": response.get("content") or response.get("message") or "Done Sir."}),
        })


async def deny_pending():
    """Cancel a pending confirmation — called by voice ('no') or menu-bar Deny."""
    global pending_confirmation
    if not pending_confirmation["active"]:
        return
    log_system("main", "Confirmation denied — cancelling.")
    pending_confirmation = {"active": False, "state": None}
    enqueue_speech("Understood Sir, cancelled.")


def _resolve_from_menubar(approve: bool):
    """Thread-safe entry point for the menu-bar buttons: schedule approve/deny
    onto the voice loop's asyncio loop."""
    if MAIN_LOOP is None or not pending_confirmation["active"]:
        return
    coro = approve_pending() if approve else deny_pending()
    asyncio.run_coroutine_threadsafe(coro, MAIN_LOOP)


async def assistant_loop():
    global pending_confirmation, MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    # Let the Island bridge resolve confirmations via the same hooks as voice/menu,
    # and feed typed commands into the same queue the loop reads.
    bridge_server.configure(
        MAIN_LOOP, approve_pending, deny_pending, submit_text=typed_input_queue.put
    )

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

        state_bus.set_state("listening", message="Listening...", tool=None, replyPreview="")
        # Listen on the mic, but bail early if a typed command arrives.
        audio = await asyncio.to_thread(listen, lambda: not typed_input_queue.empty())

        typed = not typed_input_queue.empty()
        if typed:
            text = typed_input_queue.get()
            log_system("main", f"Typed command: {text}")
        else:
            state_bus.set_state("transcribing", message="Transcribing...")
            text = await asyncio.to_thread(transcribe, audio)

        if not text.strip() or len(text.strip()) < 3:
            state_bus.set_state("idle", message="")
            continue

        # Self-echo only applies to mic input — never to typed commands.
        if not typed and _is_self_echo(text):
            log_system("main", "Ignored self-echo (heard my own voice).")
            state_bus.set_state("idle", message="")
            continue

        print(f"You: {text}")
        log_user(text)
        state_bus.set_state("thinking", message="Thinking...", transcript=text)

        # ── Confirmation flow ─────────────────────────────────────────
        if pending_confirmation["active"]:
            if _is_confirmation(text):
                await approve_pending()
                asyncio.create_task(store(f"User: {text}"))
                continue

            elif _is_denial(text):
                await deny_pending()
                asyncio.create_task(store(f"User: {text}"))
                continue

            else:
                # User said something unrelated — clear confirmation, proceed normally
                log_system("main", "Unrelated input — clearing pending confirmation.")
                pending_confirmation = {"active": False, "state": None}

        # ── Normal routing ────────────────────────────────────────────
        turn_done = asyncio.Event()
        cue_task = asyncio.create_task(_thinking_cues(turn_done))
        try:
            complex_request = await asyncio.to_thread(is_complex, text)
            if complex_request:
                log_system("main", "Routing to agent loop.")
                # Immediate audible ack so the user isn't met with silence while the
                # multi-step loop runs. If a latency cue already spoke, don't stack
                # another short acknowledgement on top of it.
                if not is_speaking.is_set() and text_queue.empty() and audio_queue.empty():
                    enqueue_speech(random.choice(AGENT_ACK_PHRASES))
                from brain.llm import history as chat_history
                response = await run_agent(text, chat_history=chat_history)
                # handle_response speaks the final reply (sentence-pipelined via
                # enqueue_speech) AND handles needs_confirmation / tool results —
                # the agent path was previously silent without this.
                await handle_response(response)
                if response.get("type") == "reply":
                    chat_history.append({"role": "user", "content": text})
                    chat_history.append({
                        "role": "assistant",
                        "content": json.dumps({"type": "reply", "content": response.get("content") or response.get("message") or "Done Sir."})
                    })
            else:
                response = None
                sentence_buffer = ""

                def run_chat_stream():
                    nonlocal response, sentence_buffer
                    for event_type, data in chat_stream(text):
                        if event_type == "token":
                            sentence_buffer += data
                            parts = re.split(r"(?<=[.!?])\s+", sentence_buffer)
                            if len(parts) > 1:
                                for part in parts[:-1]:
                                    if part.strip():
                                        enqueue_speech(part.strip())
                                sentence_buffer = parts[-1]
                        elif event_type == "tool":
                            name, args = data
                            response = {"type": "tool", "name": name, "args": args}
                        elif event_type == "reply":
                            response = {"type": "reply", "content": data}

                await asyncio.to_thread(run_chat_stream)

                # Enqueue any remaining text in the buffer if it was a reply
                if not response or response.get("type") == "reply":
                    if sentence_buffer.strip():
                        enqueue_speech(sentence_buffer.strip())
                    log_response(response or {"type": "reply", "content": sentence_buffer})
                else:
                    log_response(response)
                    await handle_response(response)
        finally:
            turn_done.set()
            cue_task.cancel()
        asyncio.create_task(store(f"User: {text}"))

        await asyncio.sleep(0.01)


# =========================================================
# MENU BAR APP
# =========================================================

# Toggle the menu-bar UI. When off (or rumps missing), run the plain voice loop.
MENUBAR = os.getenv("FRIDAY_MENUBAR", "1") == "1"


def _run_voice_loop():
    asyncio.run(assistant_loop())


def _start_menubar():
    """Menu-bar app with a click-to-approve confirmation button. Voice 'yes/no'
    still works in parallel — both resolve the same pending confirmation."""
    import rumps

    class FridayBar(rumps.App):
        def __init__(self):
            super().__init__("FRIDAY", title="🤖")
            self.status_item = rumps.MenuItem("FRIDAY — online")
            self.approve_item = rumps.MenuItem("✅ Approve", callback=self._approve)
            self.deny_item = rumps.MenuItem("❌ Deny", callback=self._deny)
            self.menu = [self.status_item, None, self.approve_item, self.deny_item]
            rumps.Timer(self._refresh, 0.4).start()

        def _refresh(self, _):
            if pending_confirmation["active"]:
                cmd = (pending_confirmation["state"] or {}).get("confirmed_command", "")
                self.title = "⚠️"
                self.status_item.title = f"Approve: {cmd[:50]}"
            else:
                self.title = "🤖"
                self.status_item.title = "FRIDAY — online"

        def _approve(self, _):
            _resolve_from_menubar(approve=True)

        def _deny(self, _):
            _resolve_from_menubar(approve=False)

    # Voice loop runs in a background thread; rumps owns the main thread.
    threading.Thread(target=_run_voice_loop, daemon=True).start()
    FridayBar().run()


if __name__ == "__main__":
    generator_thread = threading.Thread(target=tts_generator_worker, daemon=True)
    player_thread = threading.Thread(target=tts_player_worker, daemon=True)
    barge_thread = threading.Thread(target=barge_in_monitor, daemon=True)
    # Local bridge for the FRIDAY Island Mac app (state WS + approval/health HTTP)
    # on 127.0.0.1:8767. Purely additive — the voice app runs identically whether
    # or not anything connects.
    bridge_thread = threading.Thread(target=bridge_server.run, daemon=True)

    generator_thread.start()
    player_thread.start()
    barge_thread.start()
    bridge_thread.start()

    # Proactive layer: fire pending reminders/timers through the TTS pipeline.
    # init() loads persisted triggers; start() spins the background scheduler
    # thread and replays any reminders that came due while FRIDAY was offline.
    # Started after the TTS workers so an overdue reminder has something to play it.
    scheduler.init(speak=speak_proactive)
    scheduler.start()

    if MENUBAR:
        try:
            _start_menubar()
        except Exception as e:
            log_error(f"Menu bar failed ({e}); falling back to voice-only.")
            _run_voice_loop()
    else:
        _run_voice_loop()
