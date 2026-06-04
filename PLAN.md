# Bureau — Minimal Prototype Plan

## Context

**Bureau** is a shared world where AI agents (Hermes) appear as characters acting out their
work. This document plans only the **first minimal prototype**: the smallest thing that
connects a live Hermes agent to a browser UI, to **validate the core concept** before building
anything bigger.

The concept to validate: *an agent's real activity stream can drive a character in a browser —
type a task, and the Hermes character walks to the right desk as it actually uses each tool,
then speaks its answer.* Everything else (multiplayer, human control, persistence, Kubernetes)
is deliberately deferred until this proves out.

**The scariest unknown is already resolved.** Reading the Hermes code confirmed it emits a
fine-grained event stream at exactly the granularity needed (see *Hermes contract* below). So
the prototype is a thin relay, not a research project.

## What we're building (one picture)

```
 Browser (Three.js, 3D)                 Bureau server (Python)              Hermes
 ──────────────────────                 ─────────────────────              ──────
  type a task  ───────── WebSocket ───▶  POST /v1/runs  ───────────────▶  starts run
                                          GET .../events (SSE)  ◀────────  tool.started,
  cube walks to desk  ◀── WS (events) ──  relay each event                tool.completed,
  thinking / speech bubble                normalize a little              message.delta,
  speaks the answer                                                       run.completed
```

Three small parts, **no build toolchain**:
- **Bureau server** — one Python file. Serves the static page, and on a WebSocket "task"
  message calls Hermes and relays its SSE events to the browser.
- **Browser** — one HTML file. A 3D scene (Three.js from a CDN, no npm/Vite) with one agent
  cube and a few labeled desks. Maps each event to "walk to desk + show bubble".
- **PROTOCOL.md** — the tiny message contract between the two.

The browser owns the (trivial) movement animation since there's only one character and no
human player — so the server stays a dumb relay. No tick loop, no server-side world state.

## Hermes contract (verified in code)

- Start a run: `POST http://127.0.0.1:8642/v1/runs` with `{"input": "<task text>"}` →
  `{"run_id": "...", "status": "started"}` (HTTP 202).
- Event stream: `GET http://127.0.0.1:8642/v1/runs/{run_id}/events` →
  `text/event-stream`, each line `data: {json}`. Event types:
  - `tool.started` — `{tool, preview}`
  - `tool.completed` — `{tool, duration, error}`
  - `message.delta` — `{delta}` (accumulate into the spoken reply)
  - `reasoning.available` — `{text}`
  - `run.completed` — `{output, usage}` / `run.failed` `{error}` / `run.cancelled`
- Server is `aiohttp` on `127.0.0.1:8642`, enabled with env `API_SERVER_ENABLED=true`.
  No auth required for localhost (set `API_SERVER_KEY` to require a Bearer token).
- Source of truth (in the sibling `hermes-agent` repo):
  `gateway/platforms/api_server.py` — run handler `_handle_runs` (~line 2676),
  SSE handler `_handle_run_events` (~line 2920), event callback `_make_run_event_callback`
  (~line 2646).
- Caveat for later: subagent events are intentionally **not** forwarded on this SSE stream
  (`api_server.py:2672`). Out of scope for the prototype; revisit via the gateway event bus
  when we want subagents-as-characters. **This caveat turned out to dominate real behavior —
  see Validation below.**

## Validation results (2026-06-04) — concept proven, with one real catch

The prototype was run end-to-end against a live Hermes (provider: `claude-sonnet-4-6` via the
2GIS proxy `ai-openai-proxy.k8s.n3.2gis.io`, reachable only on VPN). Driving Hermes through the
Bureau WebSocket relay:

- **No-tool task** (`"reply with: pong"`) → `message` deltas → `reasoning` → `done` in **2.6s**.
  The full relay path (POST → live SSE → normalize by `event` key → WS) works as designed.
- **Web-search task** (`"search the web for the Eiffel Tower height…"`) → the cube walks, then
  speaks the correct answer *"The Eiffel Tower is 330 metres tall."* in **13.4s**. Concept
  validated: a real agent run drives the character and its spoken answer. ✅

**The catch (confirms the subagent caveat above).** On the web-search task the only tool event
the top-level run emitted was:
```
tool.started  tool=delegate_task   →  station "desk" (Workbench)
tool.completed tool=delegate_task
done           "The Eiffel Tower is 330 metres tall."
```
Hermes **delegated** the actual work to a subagent, and the real `web_search` happened *inside*
that subagent — whose events are intentionally not forwarded on this SSE stream. So:
- The character walks/speaks correctly, **but** it goes to the generic Workbench, not the
  Research Desk, because the only visible tool name is `delegate_task`. The per-tool → desk
  mapping (`STATION_RULES` in `server.py`) does not fire on delegated work.
- This means the **rich "walk to the right desk per tool" payoff depends on subagent events**,
  which only the gateway event bus exposes — not this run-scoped SSE API.

Other confirmed contract details from the live run:
- The events SSE is **live & single-consumer**: you must subscribe right after `POST /v1/runs`
  and hold the connection for the whole run. Reconnecting to an in-flight run returns
  `{"error": {"code": "run_not_found"}}` even while the status endpoint still reads `running`.
  `server.py` already does the right thing (subscribe-and-hold); no change needed.
- A failed model call surfaces as `run.failed` only after Hermes exhausts its retries
  (~118s for a 3× provider timeout), with an often-empty `error` string. The real cause shows
  up in the **gateway terminal**, not the event payload.

### Implication for next steps
1. *Cosmetic, optional:* map `delegate`/`task` to a sensible station (e.g. a "Dispatch" desk) and
   add a minimum dwell time per station so the cube doesn't teleport. Concept is already proven.
2. *The real upgrade:* **subagents-as-characters via the gateway event bus** is no longer just a
   "nice to have later" — it's what unlocks the per-tool desk mapping for typical Hermes runs,
   which delegate. Promoted from the deferred list to the recommended next milestone.

## File layout

```
bureau/
  server.py            # FastAPI: serve static + WebSocket relay to Hermes (the whole backend)
  static/
    index.html         # Three.js scene + WebSocket client (3D via CDN, no build step)
  requirements.txt     # fastapi, uvicorn, httpx
  PROTOCOL.md          # the browser <-> server message contract
  PLAN.md              # this file
  README.md            # how to run
```

## Browser <-> Bureau protocol (PROTOCOL.md)

Browser → server:
- `{"type": "task", "prompt": "<text typed by the user>"}`

Server → browser (normalized from Hermes events):
- `{"type": "tool.started",   "tool": "web_search", "station": "research"}`
- `{"type": "tool.completed", "tool": "web_search", "error": false}`
- `{"type": "reasoning",      "text": "..."}`
- `{"type": "message",        "text": "<accumulated reply so far>"}`
- `{"type": "done",           "output": "<final reply>"}`
- `{"type": "error",          "error": "<message>"}`

## Event → station mapping (in server.py, a small dict)

Map by substring of the tool name to a station the browser knows by name:

| tool name contains      | station    | desk label        |
|-------------------------|------------|-------------------|
| `search`, `web`, `exa`  | `research` | Research Desk     |
| `code`, `bash`, `python`, `shell`, `file` | `code` | Code Workstation |
| `image`, `art`, `fal`   | `art`      | Art Easel         |
| `mail`, `message`, `send` | `comms`  | Comms Desk        |
| *(anything else)*       | `desk`     | Workbench         |

Browser keeps a fixed coordinate per station. `reasoning` → thought bubble `...` in place.
`message`/`done` → speech bubble with the text. Idle (run done) → walk back to center.

## Build checkpoints (commit each)

0. **Scaffold** — `git init` in `bureau/`, add the files above (stubs), `requirements.txt`,
   `README.md`, MIT `LICENSE`. Server serves `index.html` and accepts a WebSocket that echoes.
   *Done when:* page loads, browser logs "connected", server logs the WS open.
1. **Validate the event stream live** — start Hermes gateway with `API_SERVER_ENABLED=true`
   and a provider key set; `curl` a run and watch real events:
   ```bash
   curl -s -X POST localhost:8642/v1/runs -H 'Content-Type: application/json' \
     -d '{"input":"search the web for the Eiffel Tower height and tell me"}'
   # then, with the returned run_id:
   curl -N localhost:8642/v1/runs/<run_id>/events
   ```
   *Done when:* we see `tool.started`/`tool.completed`/`message.delta`/`run.completed` scroll by.
2. **Relay** — server: on `{"type":"task"}`, `POST /v1/runs`, then stream the SSE with `httpx`
   (`client.stream("GET", url)`, iterate `aiter_lines()`, parse `data: {...}`), normalize each
   event per the table, push over the WebSocket. Accumulate `message.delta` into the reply.
   *Done when:* typing a task in a bare page prints the live event JSON in the browser console.
3. **The scene (payoff)** — `index.html`: Three.js from CDN (importmap, `<script type=module>`),
   a floor plane, one agent cube, ~4 labeled desks at fixed coords, a text-input box. On each
   event: tween the cube to the station, show a thinking/speech bubble (CSS overlay or sprite).
   *Done when:* you type a task and the Hermes cube walks to the research desk, thinks, then
   "speaks" the answer — **concept validated.**

## How to run / verify (end to end)

```bash
# Terminal A — Hermes API server (from the hermes-agent repo, with a provider key configured)
API_SERVER_ENABLED=true hermes gateway run        # listens on 127.0.0.1:8642

# Terminal B — Bureau
cd bureau && pip install -r requirements.txt
python server.py                                   # serves http://localhost:8000

# Browser: open http://localhost:8000, type "search the web for X and summarize", watch.
```

Manual verification = the checkpoint-3 "done when". If 3D fights us, the same protocol drives a
2D `<canvas>` with zero server changes — fall back, then upgrade.

## Explicitly out of scope (for this prototype)

Multiplayer, human possession/control, WASD, server-side tick loop / world state, name tags,
proximity chat, ownership/auth, persistence/DB, Docker/Kubernetes, subagents-as-characters.
All deferred until the concept is proven.

## After it validates (not now)

Server-authoritative tick loop + multiple entities → multiplayer humans → possession →
richer world (more stations, subagents via the gateway event bus) → persistence → k8s.

## Feature #2 shipped (2026-06-04) — subagents-as-characters

The validation finding (subagents hidden) is now addressed. Built:

- **Hermes (opt-in patch):** `API_SERVER_SUBAGENT_EVENTS=true` forwards `subagent.start|tool|complete`
  (with `subagent_id`/`parent_id`/`depth`/`goal`, and the real tool name) on the run SSE — events
  that already reached the API callback but were dropped. Additive, off by default. Branch
  `feat/api-server-subagent-events` on the `legchikov/hermes-agent` fork; PR proposed upstream.
- **Bureau server:** relays the new events into `subagent.spawn|tool|done` WS messages (reusing the
  tool→station map, which now fires on real tools). Demo mode scripts two concurrent subagents.
- **Bureau scene:** an entity manager — the main agent is a "boss" at Dispatch; each subagent spawns
  as its own cube, walks to the desk for its real tool, then fades out on completion. Graceful
  single-cube fallback when subagent events are absent.

See the implementation plan at
`~/.claude/plans/lets-build-according-to-logical-turtle.md` for full detail.
