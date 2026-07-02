"""Router-only benchmark: how accurate is the raw qwen2.5:3b classifier on the
labeled routing cases, WITHOUT the keyword tiers in front of it?

This answers the standing architecture question with data: can the hand-tuned
COMPLEX/SIMPLE/REMINDER keyword lists shrink (or go away), with the model
carrying the load? The labeled truth comes from test_regression.py's
ROUTING_CASES + ROUTER_MODEL_CASES — every case there is a behavior we've
committed to (many are pinned regressions from real misroutes).

    python bench_router.py

Reads:
  - raw-router accuracy overall and split by expected label
  - which tier of is_complex currently decides each case (pin vs router)
  - the exact cases the raw router gets wrong (i.e. what the pins are earning)

Run after any change to the router prompt/few-shots/model. If raw accuracy ever
reaches ~parity with the pinned suite, the keyword lists can shrink.
"""
import time

from brain.llm import (
    classify_with_router,
    REMINDER_SIGNALS,
    COMPLEX_SIGNALS,
    SIMPLE_SIGNALS,
)
from test_regression import ROUTING_CASES, ROUTER_MODEL_CASES


def _current_tier(utterance: str) -> str:
    """Which tier of is_complex decides this utterance today."""
    t = utterance.lower().strip()
    if any(s in t for s in REMINDER_SIGNALS):
        return "reminder_pin"
    if any(s in t for s in COMPLEX_SIGNALS):
        return "complex_pin"
    if any(s in t for s in SIMPLE_SIGNALS):
        return "simple_pin"
    return "router"


def run():
    cases = list(ROUTING_CASES) + list(ROUTER_MODEL_CASES)
    wrong = []
    latencies = []
    by_tier_total: dict[str, int] = {}
    by_tier_wrong: dict[str, int] = {}

    print(f"Raw qwen2.5:3b router vs {len(cases)} labeled cases (no keyword tiers):\n")
    for utt, expected in cases:
        tier = _current_tier(utt)
        by_tier_total[tier] = by_tier_total.get(tier, 0) + 1
        t0 = time.time()
        try:
            got = classify_with_router(utt)
        except Exception as e:
            got = None
            print(f"  ERR   {utt[:60]}  ({e})")
        latencies.append(time.time() - t0)
        ok = got == expected
        if not ok:
            wrong.append((utt, expected, tier))
            by_tier_wrong[tier] = by_tier_wrong.get(tier, 0) + 1
        print(
            f"  {'PASS' if ok else 'FAIL'}  raw={'COMPLEX' if got else 'SIMPLE':7} "
            f"(want {'COMPLEX' if expected else 'SIMPLE':7})  [today: {tier:12}]  {utt[:56]}"
        )

    n = len(cases)
    acc = (n - len(wrong)) / n * 100
    avg_ms = sum(latencies) / len(latencies) * 1000
    print(f"\nRaw router accuracy: {n - len(wrong)}/{n} ({acc:.0f}%)  avg {avg_ms:.0f}ms/case")

    print("\nPer-tier (how many of each tier's cases the raw router would get right on its own):")
    for tier in sorted(by_tier_total):
        total = by_tier_total[tier]
        bad = by_tier_wrong.get(tier, 0)
        print(f"  {tier:12}  {total - bad}/{total} correct without the pin")

    if wrong:
        print("\nRaw-router misses (what the keyword pins are currently earning):")
        for utt, expected, tier in wrong:
            print(f"  - want {'COMPLEX' if expected else 'SIMPLE':7} [{tier}]  {utt}")


if __name__ == "__main__":
    run()
