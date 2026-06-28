from faster_whisper import WhisperModel
import sounddevice as sd
import numpy as np
import os
from collections import deque

SAMPLE_RATE = 16000
BLOCK_DURATION = float(os.getenv("FRIDAY_STT_BLOCK_DURATION", "0.10"))
SILENCE_THRESHOLD = float(os.getenv("FRIDAY_STT_THRESHOLD", "0.012"))
# Adaptive per-listen threshold (calibrate against ambient noise). Default OFF:
# it regressed reliability — with any background audio the calibrated bar climbs
# toward THRESHOLD_CAP (~3x the old fixed 0.012) and stops hearing normal speech.
# The fixed SILENCE_THRESHOLD is the known-good behavior; opt in with =1.
ADAPTIVE_THRESHOLD = os.getenv("FRIDAY_STT_ADAPTIVE", "0") == "1"
MAX_SILENCE_SECONDS = float(os.getenv("FRIDAY_STT_MAX_SILENCE", "1.35"))  # don't cut off on a mid-sentence pause
CALIBRATION_SECONDS = float(os.getenv("FRIDAY_STT_CALIBRATION_SECONDS", "0.45"))
THRESHOLD_MULTIPLIER = float(os.getenv("FRIDAY_STT_THRESHOLD_MULTIPLIER", "3.0"))
MIN_RECORD_SECONDS = float(os.getenv("FRIDAY_STT_MIN_RECORD_SECONDS", "0.45"))
# Hard cap on the adaptive threshold so a loud calibration sample (e.g. FRIDAY's
# own speech bleeding in) can't set the bar above normal speaking volume.
THRESHOLD_CAP = float(os.getenv("FRIDAY_STT_THRESHOLD_CAP", "0.040"))
# Give up waiting for speech to START after this long and return empty, so the
# main loop re-listens and re-calibrates. Without this, a single bad calibration
# leaves the mic permanently deaf (started never flips) and FRIDAY hangs at
# "Listening" until restart.
MAX_WAIT_SECONDS = float(os.getenv("FRIDAY_STT_MAX_WAIT", "18.0"))
# Keep a short rolling buffer of audio from *before* speech is detected, so the
# quiet onset of the first word isn't clipped (a big cause of misheard input).
PRE_ROLL_SECONDS = float(os.getenv("FRIDAY_STT_PRE_ROLL_SECONDS", "0.65"))
PRE_ROLL_BLOCKS = max(1, int(PRE_ROLL_SECONDS / BLOCK_DURATION))
WHISPER_VAD = os.getenv("FRIDAY_WHISPER_VAD", "1") == "1"
WHISPER_VAD_SILENCE_MS = int(os.getenv("FRIDAY_WHISPER_VAD_SILENCE_MS", "420"))
DEBUG_AUDIO = os.getenv("FRIDAY_AUDIO_DEBUG", "0") == "1"


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
    return float(np.sqrt(np.mean(np.square(chunk))))


def _adaptive_threshold(stream, block_size: int) -> tuple[float, deque]:
    """Measure ambient mic level and return a per-listen speech threshold.

    Fixed thresholds miss soft speech on quiet mics and trigger too eagerly on
    noisy ones. A short calibration gives each listen a local noise floor while
    preserving SILENCE_THRESHOLD as the minimum sensitivity floor.
    """
    samples = []
    pre_roll = deque(maxlen=PRE_ROLL_BLOCKS)
    blocks = max(1, int(CALIBRATION_SECONDS / BLOCK_DURATION))
    for _ in range(blocks):
        chunk, _ = stream.read(block_size)
        chunk = chunk.flatten()
        pre_roll.append(chunk)
        samples.append(rms(chunk))

    noise_floor = float(np.median(samples)) if samples else 0.0
    threshold = max(SILENCE_THRESHOLD, noise_floor * THRESHOLD_MULTIPLIER)
    # Prevent an accidental loud calibration sample from making FRIDAY deaf.
    threshold = min(threshold, THRESHOLD_CAP)

    if DEBUG_AUDIO:
        print(f"[STT] noise={noise_floor:.5f} threshold={threshold:.5f}")

    return threshold, pre_roll

def listen(should_abort=None):
    """Record until the user stops speaking. If should_abort() becomes true
    (e.g. a typed command arrived from the island), stop early and return empty
    audio — the caller then takes the typed input instead of transcribing."""
    recording = []
    silence_time = 0
    speech_time = 0
    waited = 0.0  # time spent waiting for speech to start (deafness watchdog)
    started = False
    block_size = int(SAMPLE_RATE * BLOCK_DURATION)

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=block_size,
        device=_input_device(),
    )

    stream.start()
    if ADAPTIVE_THRESHOLD:
        threshold, pre_roll = _adaptive_threshold(stream, block_size)
    else:
        # Known-good fixed threshold — always hears normal speech regardless of
        # background audio (the pre-rework behavior).
        threshold, pre_roll = SILENCE_THRESHOLD, deque(maxlen=PRE_ROLL_BLOCKS)
    if DEBUG_AUDIO:
        print(f"[STT] threshold={threshold:.4f} (adaptive={ADAPTIVE_THRESHOLD})")

    while True:
        if should_abort is not None and should_abort():
            stream.stop()
            stream.close()
            return np.array([], dtype=np.float32)

        chunk, _ = stream.read(block_size)
        chunk = chunk.flatten()
        volume = rms(chunk)

        if not started:
            pre_roll.append(chunk)
            if volume > threshold:
                started = True
                silence_time = 0
                speech_time = BLOCK_DURATION
                recording.extend(pre_roll)  # include the lead-in audio
            else:
                # Watchdog: if speech never starts (e.g. the threshold calibrated
                # too high off FRIDAY's own echo), bail so the caller re-listens
                # and re-calibrates instead of going permanently deaf.
                waited += BLOCK_DURATION
                if waited >= MAX_WAIT_SECONDS:
                    if DEBUG_AUDIO:
                        print(f"[STT] No speech in {MAX_WAIT_SECONDS:.0f}s "
                              f"(threshold={threshold:.4f}) — re-listening.")
                    break
        else:
            recording.append(chunk)
            if volume > threshold:
                silence_time = 0
                speech_time += BLOCK_DURATION
            else:
                silence_time += BLOCK_DURATION
                if silence_time >= MAX_SILENCE_SECONDS and speech_time >= MIN_RECORD_SECONDS:
                    break

    stream.stop()
    stream.close()
    if DEBUG_AUDIO:
        print("Speech ended")

    if not recording:
        return np.array([], dtype=np.float32)

    return np.concatenate(recording)

def transcribe(audio):
    if len(audio) == 0:
        return ""
    segments, info = model.transcribe(
        audio,
        language="en",
        beam_size=5,
        vad_filter=WHISPER_VAD,
        vad_parameters={
            "min_silence_duration_ms": WHISPER_VAD_SILENCE_MS,
            "speech_pad_ms": 320,
        } if WHISPER_VAD else None,
    )
    text = ""
    for seg in segments:
        text += seg.text + " "
    if DEBUG_AUDIO:
        duration = len(audio) / SAMPLE_RATE
        print(f"[STT] duration={duration:.2f}s lang={getattr(info, 'language', '?')} text={text.strip()!r}")
    return text.strip()
