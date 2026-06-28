from pathlib import Path
import time

import sounddevice as sd
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "voice_samples"

VOICES = [
    ("af_heart", "current voice"),
    ("af_bella", "warm / expressive"),
    ("af_sarah", "clear / assistant-like"),
    ("af_nicole", "deeper / calmer"),
    ("af_sky", "light / youthful"),
    ("bf_emma", "British / polished"),
    ("bf_isabella", "British / softer"),
    ("af_bella__af_heart", "blend: bella + heart"),
    ("af_sarah__af_heart", "blend: sarah + heart"),
]


def play_file(path: Path) -> None:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    sd.play(audio, sample_rate, blocking=True, latency="high")


def main() -> None:
    print("\nFRIDAY voice audition\n")
    print("Press Ctrl+C to stop.\n")

    for index, (voice, note) in enumerate(VOICES, start=1):
        path = SAMPLES / f"{voice}.wav"
        if not path.exists():
            print(f"[{index}/{len(VOICES)}] Missing: {path}")
            continue

        print(f"[{index}/{len(VOICES)}] Playing {voice} - {note}")
        play_file(path)
        time.sleep(0.8)

    print("\nDone.")


if __name__ == "__main__":
    main()
