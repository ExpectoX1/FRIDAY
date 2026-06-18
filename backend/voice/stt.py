from faster_whisper import WhisperModel
import sounddevice as sd
import numpy as np
import os

SAMPLE_RATE = 16000
BLOCK_DURATION = 0.25
SILENCE_THRESHOLD = 0.015
MAX_SILENCE_SECONDS = 0.8


def _input_device():
    """Pick the mic. A hardcoded index breaks whenever the device list shuffles
    (plugging in headphones, reboots), so default to the system input device.
    Override with FRIDAY_MIC_DEVICE if you have a specific mic in mind."""
    override = os.getenv("FRIDAY_MIC_DEVICE")
    if override is not None:
        return int(override)
    default_in = sd.default.device[0]
    return default_in if default_in is not None and default_in >= 0 else None


model = WhisperModel("base.en", device="auto", compute_type="int8")

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

    while True:
        chunk, _ = stream.read(int(SAMPLE_RATE * BLOCK_DURATION))
        chunk = chunk.flatten()
        volume = rms(chunk)

        if volume > SILENCE_THRESHOLD:
            started = True
            silence_time = 0
            recording.append(chunk)
        elif started:
            recording.append(chunk)
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