"""Local bridge for the FRIDAY Island Mac app.

Exposes (on 127.0.0.1:8767, separate from the graph viz on 8766):
  WS   /ws/state    push every state change (plus an initial snapshot)
  GET  /api/health  liveness + current state
  POST /api/approval  {"approved": true|false}  -> resume/cancel a pending action
  POST /api/input     {"text": "..."}           -> typed command (Phase 3; 503 for now)

Runs in its own thread with its own event loop (uvicorn), so it never contends
with the voice loop or the rumps menu bar. Approval is dispatched onto the voice
loop via run_coroutine_threadsafe, reusing the same approve/deny hooks the menu
bar uses — so the island, the menu bar, and voice all resolve the SAME pending
confirmation.
"""
import asyncio

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from bridge import state_bus

app = FastAPI(title="FRIDAY Island Bridge")

# Wired up by main.py once the voice loop is running.
_handlers = {"loop": None, "approve": None, "deny": None, "submit_text": None}


def configure(loop, approve_coro, deny_coro, submit_text=None) -> None:
    """Register the voice loop + coroutine hooks. approve_coro/deny_coro are the
    same approve_pending/deny_pending coroutines the menu bar uses."""
    _handlers.update(
        loop=loop, approve=approve_coro, deny=deny_coro, submit_text=submit_text
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "state": state_bus.get_state()["state"]}


@app.post("/api/approval")
async def approval(payload: dict):
    loop = _handlers["loop"]
    fn = _handlers["approve"] if payload.get("approved") else _handlers["deny"]
    if not loop or not fn:
        return JSONResponse(status_code=503, content={"error": "backend not ready"})
    asyncio.run_coroutine_threadsafe(fn(), loop)
    return {"ok": True}


@app.post("/api/input")
async def submit_input(payload: dict):
    loop, fn = _handlers["loop"], _handlers["submit_text"]
    if not loop or not fn:
        # Phase 3 — typed-command routing not wired yet. Codex shows a disabled
        # / retry state on 503.
        return JSONResponse(
            status_code=503, content={"error": "typed input not available yet"}
        )
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "empty text"})
    asyncio.run_coroutine_threadsafe(fn(text), loop)
    return {"ok": True}


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    state_bus.subscribe(loop, queue)
    try:
        await ws.send_json(state_bus.get_state())  # initial snapshot
        while True:
            await ws.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        state_bus.unsubscribe(queue)


def run(host: str = "127.0.0.1", port: int = 8767) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")
