from faster_whisper import WhisperModel
import sounddevice as sd
import numpy as np
import os
from collections import deque

SAMPLE_RATE = 16000
BLOCK_DURATION = 0.25
SILENCE_THRESHOLD = 0.012
MAX_SILENCE_SECONDS = 1.1  # don't cut off on a mid-sentence pause
# Keep a short rolling buffer of audio from *before* speech is detected, so the
# quiet onset of the first word isn't clipped (a big cause of misheard input).
PRE_ROLL_BLOCKS = 3  # ~0.75s lead-in


def _input_device():
    """Pick the mic. A hardcoded index breaks whenever the device list shuffles
    (plugging in headphones, reboots), so default to the system input device.
    Override with FRIDAY_MIC_DEVICE if you have a specific mic in mind."""
    override = os.getenv("FRIDAY_MIC_DEVICE")
    if override is not None:
        return int(override)
    default_in = sd.default.device[0]
    return default_in if default_in is not None and default_in >= 0 else None


# small.en is markedly more accurate than base.en and still fast on Apple
# silicon (int8). Override with FRIDAY_STT_MODEL (e.g. base.en for max speed).
STT_MODEL = os.getenv("FRIDAY_STT_MODEL", "systran/faster-distil-whisper-small.en")
model = WhisperModel(STT_MODEL, device="auto", compute_type="int8")

def rms(chunk):
    return np.sqrt(np.mean(np.square(chunk)))

def listen():
    print("\nListening...")
    recording = []
    silence_time = 0
    started = False

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=int(SAMPLE_RATE * BLOCK_DURATION),
        device=_input_device(),
    )

    stream.start()

    pre_roll = deque(maxlen=PRE_ROLL_BLOCKS)

    while True:
        chunk, _ = stream.read(int(SAMPLE_RATE * BLOCK_DURATION))
        chunk = chunk.flatten()
        volume = rms(chunk)

        if not started:
            pre_roll.append(chunk)
            if volume > SILENCE_THRESHOLD:
                started = True
                silence_time = 0
                recording.extend(pre_roll)  # include the lead-in audio
        else:
            recording.append(chunk)
            if volume > SILENCE_THRESHOLD:
                silence_time = 0
            else:
                silence_time += BLOCK_DURATION
                if silence_time >= MAX_SILENCE_SECONDS:
                    break

    stream.stop()
    stream.close()
    print("Speech ended")

    if not recording:
        return np.array([], dtype=np.float32)

    return np.concatenate(recording)

def transcribe(audio):
    if len(audio) == 0:
        return ""
    segments, _ = model.transcribe(
        audio,
        language="en",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 180}
    )
    text = ""
    for seg in segments:
        text += seg.text + " "
    return text.strip()