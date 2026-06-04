# Bureau Protocol

The tiny message contract between the browser and the Bureau server. Both directions are JSON
sent over a single WebSocket at `ws://<host>/ws`.

## Browser → server

```json
{ "type": "task", "prompt": "<text typed by the user>" }
```

That's the only message the browser sends. One task at a time.

## Server → browser

The server normalizes upstream Hermes events into this small, stable set. Every message has a
`type`. A `"demo": true` flag is added to all messages when the server is running scripted demo
mode (Hermes unreachable) instead of relaying a real run.

| message | fields | meaning |
|---------|--------|---------|
| `tool.started` | `tool` (str), `station` (str) | agent began using a tool → walk the character to `station` |
| `tool.completed` | `tool` (str), `error` (bool) | tool finished |
| `reasoning` | `text` (str) | a thought → show a `...` thinking bubble |
| `message` | `text` (str) | the reply **accumulated so far** (replace, don't append) → speech bubble |
| `done` | `output` (str) | run finished → final reply; character returns home |
| `error` | `error` (str) | run failed / relay error |
| `subagent.spawn` | `id` (str), `goal` (str), `depth` (int?), `parent` (str?) | a subagent started → spawn a new character |
| `subagent.tool` | `id` (str), `tool` (str), `station` (str) | that subagent began a tool → walk character `id` to `station` |
| `subagent.done` | `id` (str), `status` (str?) | subagent finished → character leaves |

`station` is one of: `research`, `code`, `art`, `comms`, `desk` (fallback). The browser keeps a
fixed coordinate per station.

The `subagent.*` messages drive **multi-character** mode: the main agent ("boss") dispatches via
`delegate_task`, and each subagent appears as its own character that walks to the desk for the
**real** tool it runs (e.g. `web_search` → Research). These only appear when the upstream Hermes
forwards subagent events (see below); otherwise the boss alone runs in single-cube mode.

## Upstream Hermes contract (for maintainers)

The server is a thin relay over the Hermes API server (`127.0.0.1:8642`, enable with
`API_SERVER_ENABLED=true`):

- `POST /v1/runs` with `{"input": "<task>"}` → `202 {"run_id": "...", "status": "started"}`
- `GET /v1/runs/{run_id}/events` → `text/event-stream`, lines `data: {json}\n\n`

**Each Hermes event is a flat JSON object keyed by `event`** (not `type`), plus `run_id` and
`timestamp`. Relevant types and fields the server consumes:

- `tool.started` → `tool`, `preview`
- `tool.completed` → `tool`, `duration` (float s), `error` (**bool**)
- `message.delta` → `delta` (the server accumulates these into the running reply)
- `reasoning.available` → `text`
- `run.completed` → `output`, `usage`; `run.failed` → `error` (str); `run.cancelled`; `run.stopping`

**Subagent events (opt-in).** A stock Hermes does **not** forward subagent activity on this SSE.
A Hermes started with `API_SERVER_SUBAGENT_EVENTS=true` additionally emits (each flat, keyed by
`event`, with the same `run_id`/`timestamp`):

- `subagent.start` → `subagent_id`, `parent_id`, `depth`, `goal`, `task_index`, `model`
- `subagent.tool` → `subagent_id`, `tool` (the real tool, e.g. `web_search`), `preview`, `goal`
- `subagent.complete` → `subagent_id`, `status`, `summary`

The Bureau server maps these to the `subagent.spawn|tool|done` browser messages above (reusing the
same tool→station rule). When they're absent (flag off / stock Hermes), Bureau runs in single-cube
mode automatically — no configuration needed. This flag is added by an opt-in patch to Hermes
(`gateway/platforms/api_server.py`); see the Bureau README.
