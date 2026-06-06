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
    fade_in = np.linspace(0, 1, fade_samples)
    fade_out = np.linspace(1, 0, fade_samples)
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


def play(audio: np.ndarray):
    if audio is None:
        return
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val * 0.95
    audio = apply_fade(audio)
    sd.stop()
    sd.play(audio, samplerate=24000)
    sd.wait()
    time.sleep(0.05)  # 50ms buffer between chunks