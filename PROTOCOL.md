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

`station` is one of: `research`, `code`, `art`, `comms`, `desk` (fallback). The browser keeps a
fixed coordinate per station.

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

Subagent / `_thinking` events are intentionally not forwarded by Hermes — out of scope here.
