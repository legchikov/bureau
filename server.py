"""Bureau server — the whole backend.

Serves the static page and, on a WebSocket "task" message, calls a live Hermes agent and relays
its SSE event stream to the browser (normalized per PROTOCOL.md). If Hermes is unreachable, falls
back to a scripted demo run so the scene is demonstrable standalone.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HERMES_URL = os.getenv("HERMES_URL", "http://127.0.0.1:8642").rstrip("/")
API_SERVER_KEY = os.getenv("API_SERVER_KEY", "")
PORT = int(os.getenv("PORT", "8000"))

STATIC_DIR = Path(__file__).parent / "static"

# Map a Hermes tool name (by substring) to a station the browser knows by name.
# First match wins; order matters.
STATION_RULES = [
    (("search", "web", "exa"), "research"),
    (("code", "bash", "python", "shell", "file"), "code"),
    (("image", "art", "fal"), "art"),
    (("mail", "message", "send"), "comms"),
]


def station_for(tool: str) -> str:
    name = (tool or "").lower()
    for needles, station in STATION_RULES:
        if any(n in name for n in needles):
            return station
    return "desk"


app = FastAPI()


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {API_SERVER_KEY}"} if API_SERVER_KEY else {}


async def relay_hermes(ws: WebSocket, prompt: str) -> None:
    """Start a Hermes run and relay its SSE events to the browser.

    Raises httpx errors if Hermes is unreachable so the caller can fall back to demo mode.
    """
    reply = ""  # accumulated message text
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None)) as client:
        resp = await client.post(
            f"{HERMES_URL}/v1/runs",
            json={"input": prompt},
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        run_id = resp.json()["run_id"]

        events_url = f"{HERMES_URL}/v1/runs/{run_id}/events"
        async with client.stream("GET", events_url, headers=_auth_headers()) as stream:
            async for line in stream.aiter_lines():
                if not line.startswith("data: "):
                    continue  # skip keepalive comments (": ...") and blank separators
                try:
                    ev = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    continue

                kind = ev.get("event")
                if kind == "tool.started":
                    tool = ev.get("tool", "")
                    await ws.send_json({
                        "type": "tool.started",
                        "tool": tool,
                        "station": station_for(tool),
                    })
                elif kind == "tool.completed":
                    await ws.send_json({
                        "type": "tool.completed",
                        "tool": ev.get("tool", ""),
                        "error": bool(ev.get("error", False)),
                    })
                elif kind == "message.delta":
                    reply += ev.get("delta", "")
                    await ws.send_json({"type": "message", "text": reply})
                elif kind == "reasoning.available":
                    await ws.send_json({"type": "reasoning", "text": ev.get("text", "")})
                elif kind == "run.completed":
                    await ws.send_json({"type": "done", "output": ev.get("output", reply)})
                    return
                elif kind == "run.failed":
                    await ws.send_json({"type": "error", "error": ev.get("error", "run failed")})
                    return
                elif kind == "run.cancelled":
                    await ws.send_json({"type": "error", "error": "run cancelled"})
                    return
                # run.stopping and anything else: ignore


async def relay_demo(ws: WebSocket, prompt: str) -> None:
    """Scripted fake run so the scene works without Hermes. Tags every message with demo: true."""
    async def send(msg: dict, pause: float = 0.0):
        msg["demo"] = True
        await ws.send_json(msg)
        if pause:
            await asyncio.sleep(pause)

    await send({"type": "reasoning", "text": "Let me look into that..."}, 0.8)

    await send({"type": "tool.started", "tool": "web_search", "station": "research"}, 1.4)
    await send({"type": "tool.completed", "tool": "web_search", "error": False}, 0.6)

    await send({"type": "tool.started", "tool": "python", "station": "code"}, 1.4)
    await send({"type": "tool.completed", "tool": "python", "error": False}, 0.6)

    answer = f'(demo) Here\'s what I found about "{prompt.strip()}".'
    acc = ""
    for word in answer.split(" "):
        acc = (acc + " " + word).strip()
        await send({"type": "message", "text": acc}, 0.12)

    await send({"type": "done", "output": answer})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("[bureau] websocket connected")
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") != "task":
                continue
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                continue
            print(f"[bureau] task: {prompt!r}")
            try:
                await relay_hermes(ws, prompt)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as e:
                print(f"[bureau] Hermes unavailable ({e!r}) — demo mode")
                await relay_demo(ws, prompt)
    except WebSocketDisconnect:
        print("[bureau] websocket disconnected")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
