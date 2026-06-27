"""Quick brain benchmark: latency + tool-selection correctness across models.

Usage: python bench_brain.py
Runs representative single-shot commands through each model with FRIDAY's real
tool spec + native system prompt, and reports per-call latency (warm) and
whether the expected tool (or a plain reply) was produced.
"""
import time
import ollama
from tools.registry import get_tools_spec
from brain.personality import get_personality

MODELS = ["qwen3:14b", "qwen2.5:7b", "gemma4:latest"]
# Qwen3 "thinks" (chain-of-thought) before answering by default, which adds
# seconds per call — disable it for a snappy voice assistant. Ignored by models
# that don't have a thinking mode (gemma4, qwen2.5).
THINK = False

# (utterance, expected) — expected is a tool name, or "reply" for plain chat.
CASES = [
    ("open spotify", "open_app"),
    ("play blinding lights on spotify", "play_media"),
    ("what time is it", "get_date_time"),
    ("how are you today", "reply"),
    ("what's on my screen", "look_at_screen"),
    ("open twitter on chrome", "navigate_browser"),
    ("who is priya", "search_memory"),
    ("what's the latest news on football", "search_web"),
]

SPEC = get_tools_spec()
SYS = get_personality(native_tools=True)


def run(model):
    print(f"\n=== {model} ===")
    # warm-up (model load not counted)
    ollama.chat(model=model, messages=[{"role": "user", "content": "hi"}], keep_alive="5m")
    total, correct = 0.0, 0
    for utt, expected in CASES:
        t = time.time()
        r = ollama.chat(
            model=model,
            messages=[{"role": "system", "content": SYS}, {"role": "user", "content": utt}],
            tools=SPEC,
            keep_alive="5m",
            think=THINK,
        )
        dt = (time.time() - t) * 1000
        total += dt
        m = r.message
        got = m.tool_calls[0].function.name if m.tool_calls else "reply"
        ok = "OK " if got == expected else "XX "
        if got == expected:
            correct += 1
        print(f"  {ok} {dt:6.0f}ms  {got:16} (want {expected:16}) {utt}")
    print(f"  -> {correct}/{len(CASES)} correct | avg {total/len(CASES):.0f}ms")


if __name__ == "__main__":
    for model in MODELS:
        try:
            run(model)
        except Exception as e:
            print(f"\n=== {model} === ERROR: {e}")
