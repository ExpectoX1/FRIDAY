"""FRIDAY end-to-end capability test — hands-off.

Runs real multi-step agent tasks in a throwaway sandbox (/tmp/friday_caps) and
VERIFIES the actual outcome on disk / in the reply — so you can see what FRIDAY
can really do without voice-testing each one. Confirmations are auto-approved
(like clicking Approve). Side-effect-free: only touches the sandbox + read-only
web search; never your real files, apps, or Spotify.

    python test_capabilities.py                      # current brain (qwen)
    FRIDAY_LOCAL_MODEL=gemma4:latest python test_capabilities.py
    FRIDAY_BRAIN=cloud python test_capabilities.py

Each task prints PASS/FAIL, what FRIDAY said, and how long it took.
"""
import asyncio
import shutil
import time
from pathlib import Path

from brain.agent import run_agent

SANDBOX = Path("/tmp/friday_caps")
TASK_TIMEOUT = 180  # seconds per task


# ── helpers ──────────────────────────────────────────────────────────────────
def fresh_sandbox(files: dict | None = None):
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True)
    for name, content in (files or {}).items():
        (SANDBOX / name).write_text(content)


def loose_files():
    return [p for p in SANDBOX.iterdir() if p.is_file()]


def subdirs():
    return [p for p in SANDBOX.iterdir() if p.is_dir()]


def all_files_recursive():
    return [p for p in SANDBOX.rglob("*") if p.is_file()]


MIXED = {
    "photo.jpg": "x", "report.pdf": "x", "song.mp3": "x", "clip.mp4": "x",
    "data.csv": "x", "notes.txt": "x", "archive.zip": "x", "readme.md": "x",
}


async def run_agent_auto(goal: str):
    """Run a task, auto-approving any confirmations (stands in for the user)."""
    resp = await run_agent(goal)
    guard = 0
    while resp.get("type") == "needs_confirmation" and guard < 6:
        guard += 1
        state = resp["pending_state"]
        resp = await run_agent(state["goal"], resume_state=state)
    return resp


# ── tasks: (name, setup, goal, verify(reply) -> (ok, detail)) ────────────────
def _v_sorted(reply):
    return (len(loose_files()) == 0 and len(subdirs()) >= 3 and len(all_files_recursive()) == 8,
            f"{len(subdirs())} folders, {len(loose_files())} loose, {len(all_files_recursive())} files total")


def _v_count8(reply):
    return ("8" in reply, f"reply mentions 8: {'8' in reply}")


def _v_created(reply):
    f = SANDBOX / "hello.txt"
    ok = f.exists() and "FRIDAY was here" in f.read_text()
    return (ok, f"hello.txt exists+content: {ok}")


def _v_batch(reply):
    have = [(SANDBOX / n).exists() for n in ("a.txt", "b.txt", "c.txt")]
    return (all(have), f"a/b/c.txt created: {sum(have)}/3")


def _norm(s: str) -> str:
    # Models sometimes emit Unicode hyphens (‑ – —) — normalize before matching.
    return s.lower().replace("‑", "-").replace("–", "-").replace("—", "-")


def _v_read(reply):
    ok = "orange-42" in _norm(reply)
    return (ok, f"reply contains the secret: {ok}")


def _v_rename(reply):
    txt = list(SANDBOX.glob("*.txt"))
    bak = list(SANDBOX.glob("*.bak"))
    return (len(txt) == 0 and len(bak) == 3, f"{len(txt)} .txt left, {len(bak)} .bak now")


def _v_web(reply):
    return ("canberra" in reply.lower(), f"reply names Canberra: {'canberra' in reply.lower()}")


def _v_multistep(reply):
    made = len(list(SANDBOX.glob("item*.txt")))
    return (made == 5 and "5" in reply, f"{made}/5 files made, reply mentions 5: {'5' in reply}")


TASKS = [
    ("sort by type", lambda: fresh_sandbox(MIXED),
     f"Organize the files in {SANDBOX} into subfolders based on their file type.", _v_sorted),
    ("count files", lambda: fresh_sandbox(MIXED),
     f"How many files are in {SANDBOX}?", _v_count8),
    ("create file w/ content", lambda: fresh_sandbox(),
     f"Create a file called hello.txt in {SANDBOX} containing exactly: FRIDAY was here", _v_created),
    ("batch create", lambda: fresh_sandbox(),
     f"Create three empty files named a.txt, b.txt and c.txt in {SANDBOX}.", _v_batch),
    ("read a file", lambda: fresh_sandbox({"secret.txt": "the code word is orange-42"}),
     f"Read the file {SANDBOX}/secret.txt and tell me the code word.", _v_read),
    ("batch rename", lambda: fresh_sandbox({"one.txt": "x", "two.txt": "x", "three.txt": "x"}),
     f"Rename every .txt file in {SANDBOX} to use a .bak extension instead.", _v_rename),
    ("web search", lambda: None,
     "What is the capital of Australia?", _v_web),
    ("multi-step create+count", lambda: fresh_sandbox(),
     f"Create 5 files named item1.txt through item5.txt in {SANDBOX}, then tell me the total number of files in that folder.", _v_multistep),
]


async def main():
    print("=" * 78)
    print("  FRIDAY CAPABILITY TEST  (sandbox: %s)" % SANDBOX)
    print("=" * 78)
    passed = 0
    for name, setup, goal, verify in TASKS:
        if setup:
            setup()
        t = time.time()
        try:
            resp = await asyncio.wait_for(run_agent_auto(goal), timeout=TASK_TIMEOUT)
            reply = resp.get("content", "") or ""
            ok, detail = verify(reply)
        except asyncio.TimeoutError:
            ok, detail, reply = False, f"TIMEOUT after {TASK_TIMEOUT}s", ""
        except Exception as e:
            ok, detail, reply = False, f"ERROR: {e}", ""
        passed += ok
        dt = time.time() - t
        print(f"\n[{'PASS' if ok else 'FAIL'}] {name}  ({dt:.1f}s)")
        print(f"       goal:   {goal[:88]}")
        print(f"       check:  {detail}")
        if reply:
            print(f"       FRIDAY: {reply[:110].strip()}")

    print("\n" + "=" * 78)
    print(f"  {passed}/{len(TASKS)} capabilities passed")
    print("=" * 78)
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)


if __name__ == "__main__":
    asyncio.run(main())
