import sounddevice as sd
import numpy as np
from kokoro import KPipeline
import os
import math
import threading
import re

try:
    from scipy.signal import resample_poly
except Exception:  # pragma: no cover - optional quality upgrade
    resample_poly = None

pipeline = KPipeline(lang_code='a')
TTS_SAMPLE_RATE = 24000
TTS_VOICE = os.getenv("FRIDAY_TTS_VOICE", "af_bella")
TTS_SPEED = float(os.getenv("FRIDAY_TTS_SPEED", "1.0"))
TTS_PEAK = float(os.getenv("FRIDAY_TTS_PEAK", "0.86"))
TTS_FADE_MS = int(os.getenv("FRIDAY_TTS_FADE_MS", "14"))
TTS_OUTPUT_RATE = os.getenv("FRIDAY_TTS_OUTPUT_RATE")

_stream_lock = threading.Lock()
_output_stream = None
_output_stream_rate = None

def clean_for_tts(text: str) -> str:
    text = text.replace("*", "")
    text = text.replace("#", "")
    text = text.replace("...", ", ")
    text = text.replace("\n", " ")
    if text.endswith(":"):
        text = text[:-1]
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text.strip()

def _output_sample_rate() -> int:
    if TTS_OUTPUT_RATE:
        return int(TTS_OUTPUT_RATE)
    try:
        device_index = sd.default.device[1]
        device = sd.query_devices(device_index, "output")
        return int(device.get("default_samplerate") or TTS_SAMPLE_RATE)
    except Exception:
        return TTS_SAMPLE_RATE


def apply_fade(audio: np.ndarray, sample_rate: int, fade_ms: int = TTS_FADE_MS) -> np.ndarray:
    fade_samples = int(sample_rate * fade_ms / 1000)
    # Guard short chunks: a fade longer than the clip would corrupt it.
    if audio.shape[0] < fade_samples * 2:
        return audio
    fade_in = np.linspace(0, 1, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1, 0, fade_samples, dtype=np.float32)
    audio[:fade_samples] *= fade_in
    audio[-fade_samples:] *= fade_out
    return audio


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate or audio.size == 0:
        return audio
    if resample_poly is not None:
        gcd = math.gcd(from_rate, to_rate)
        return resample_poly(audio, to_rate // gcd, from_rate // gcd).astype(np.float32)

    # Fallback: lower quality, but avoids hard dependency surprises.
    duration = audio.shape[0] / from_rate
    old_x = np.linspace(0, duration, num=audio.shape[0], endpoint=False)
    new_len = max(1, int(duration * to_rate))
    new_x = np.linspace(0, duration, num=new_len, endpoint=False)
    return np.interp(new_x, old_x, audio).astype(np.float32)


def _prepare_audio(audio: np.ndarray, output_rate: int) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return audio

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    audio = _resample(audio, TTS_SAMPLE_RATE, output_rate)

    # Do not boost every chunk to full scale; that makes quiet chunks noisy and
    # sentence boundaries pop. Only scale down peaks that could clip.
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > TTS_PEAK:
        audio = audio / peak * TTS_PEAK

    audio = np.tanh(audio * 1.05).astype(np.float32)
    return np.ascontiguousarray(apply_fade(audio, output_rate), dtype=np.float32)


def _get_output_stream(sample_rate: int):
    global _output_stream, _output_stream_rate
    if (
        _output_stream is not None
        and _output_stream_rate == sample_rate
        and not _output_stream.closed
    ):
        if not _output_stream.active:
            _output_stream.start()
        return _output_stream

    if _output_stream is not None:
        try:
            _output_stream.close()
        except Exception:
            pass

    _output_stream = sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        latency="high",
        blocksize=0,
    )
    _output_stream.start()
    _output_stream_rate = sample_rate
    return _output_stream

def generate(text: str):
    text = clean_for_tts(text)
    if not text:
        return None
    chunks = []
    for _, _, audio in pipeline(text, voice=TTS_VOICE, speed=TTS_SPEED):
        chunks.append(audio)
    if not chunks:
        return None
    return np.concatenate(chunks)


def generate_stream(text: str):
    """Generator that yields audio chunks as they are synthesized by Kokoro."""
    text = clean_for_tts(text)
    if not text:
        return
    for _, _, audio in pipeline(text, voice=TTS_VOICE, speed=TTS_SPEED):
        if audio is not None:
            yield audio


def play(audio: np.ndarray):
    if audio is None:
        return
    output_rate = _output_sample_rate()
    audio = _prepare_audio(audio, output_rate)
    if audio.size == 0:
        return

    # Use a persistent stream instead of repeatedly starting/stopping sd.play().
    # blocksize=0 lets PortAudio choose a host-friendly buffer size, which is
    # more robust when the LLM is also loading the CPU.
    with _stream_lock:
        stream = _get_output_stream(output_rate)
        try:
            underflowed = stream.write(audio.reshape(-1, 1))
            if underflowed:
                print("[TTS] Output underflow detected; consider FRIDAY_TTS_OUTPUT_RATE or lowering LLM load.")
        except Exception:
            # If sd.stop() or a device change invalidated the stream, recreate it.
            global _output_stream
            try:
                if _output_stream is not None:
                    _output_stream.close()
            finally:
                _output_stream = None
            stream = _get_output_stream(output_rate)
            stream.write(audio.reshape(-1, 1))
