import sounddevice as sd
import numpy as np
from kokoro import KPipeline
import re,time

pipeline = KPipeline(lang_code='a')

def clean_for_tts(text: str) -> str:
    text = text.replace("*", "")
    text = text.replace("#", "")
    text = text.replace("...", ", ")
    text = text.replace("\n", " ")
    if text.endswith(":"):
        text = text[:-1]
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text.strip()

def apply_fade(audio: np.ndarray, fade_ms: int = 10) -> np.ndarray:
    fade_samples = int(24000 * fade_ms / 1000)
    # Guard short chunks: a fade longer than the clip would corrupt it.
    if audio.shape[0] < fade_samples * 2:
        return audio
    fade_in = np.linspace(0, 1, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1, 0, fade_samples, dtype=np.float32)
    audio[:fade_samples] *= fade_in
    audio[-fade_samples:] *= fade_out
    return audio

def generate(text: str):
    text = clean_for_tts(text)
    if not text:
        return None
    chunks = []
    for _, _, audio in pipeline(text, voice='af_heart', speed=1.0):
        chunks.append(audio)
    if not chunks:
        return None
    return np.concatenate(chunks)


def generate_stream(text: str):
    """Generator that yields audio chunks as they are synthesized by Kokoro."""
    text = clean_for_tts(text)
    if not text:
        return
    for _, _, audio in pipeline(text, voice='af_heart', speed=1.0):
        if audio is not None:
            yield audio


def play(audio: np.ndarray):
    if audio is None:
        return
    # Own a contiguous float32 buffer so the in-place fade is safe and the audio
    # backend doesn't have to re-copy/convert mid-stream.
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val * 0.95
    audio = apply_fade(audio)
    # latency="high" requests a larger output buffer. The playback thread runs
    # while gemma4 saturates the machine, so a small buffer starves and crackles;
    # a high-latency buffer rides through the inference load cleanly.
    sd.play(audio, samplerate=24000, blocking=False, latency="high")
    sd.wait()