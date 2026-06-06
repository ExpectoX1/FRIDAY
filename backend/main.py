import queue
import threading
import asyncio
from voice.stt import listen, transcribe
from voice.tts import generate, play
from brain.llm import stream_chat

text_queue = queue.Queue()
audio_queue = queue.Queue()
is_speaking = threading.Event()

def tts_generator_worker():
    """Takes text, generates audio, puts in audio queue"""
    while True:
        text = text_queue.get()
        if text is None:
            break
        audio = generate(text)
        if audio is not None:
            audio_queue.put(audio)
        text_queue.task_done()

def tts_player_worker():
    """Takes audio arrays, plays them back to back"""
    while True:
        audio = audio_queue.get()
        if audio is None:
            break
        is_speaking.set()
        play(audio)
        audio_queue.task_done()
        if audio_queue.empty():
            is_speaking.clear()

async def assistant_loop():
    startup_audio = generate("Friday Online Sir, All systems okay.")
    if startup_audio is not None:
        audio_queue.put(startup_audio)
    while True:
        # wait until FRIDAY is done speaking
        while is_speaking.is_set():
            await asyncio.sleep(0.05)

        audio = listen()
        text = transcribe(audio)

        if not text.strip() or len(text.strip()) < 3:
            continue

        print(f"You: {text}")

        for sentence in stream_chat(text):
            print(f"FRIDAY: {sentence}")
            text_queue.put(sentence)

        await asyncio.sleep(0.01)

if __name__ == "__main__":
    # start both workers
    generator_thread = threading.Thread(target=tts_generator_worker, daemon=True)
    player_thread = threading.Thread(target=tts_player_worker, daemon=True)
    
    generator_thread.start()
    player_thread.start()

    asyncio.run(assistant_loop())