# bureau

A shared world where AI agents (Hermes) appear as characters acting out their work.

This repo is the **first minimal prototype**: type a task → a Hermes character cube walks to the
right desk as the agent actually uses each tool, then speaks its answer. It's a thin relay between
a live Hermes agent and a browser 3D scene — nothing more. See [PLAN.md](PLAN.md) for the full
plan and [PROTOCOL.md](PROTOCOL.md) for the message contract.

## Run it

```bash
cd bureau
pip install -r requirements.txt
python server.py            # serves http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and type a task.

- **Without Hermes running**, the server falls back to a scripted **demo** run so you can see the
  cube walk between desks and speak — the whole browser pipeline, standalone.
- **With Hermes running**, it relays the real agent. Start the Hermes API server first (from the
  `hermes-agent` repo, with a provider API key configured):

  ```bash
  API_SERVER_ENABLED=true hermes gateway run     # listens on 127.0.0.1:8642
  ```

  Then in the browser, type e.g. `search the web for the Eiffel Tower height and tell me` and watch
  the cube walk to the Research Desk as the real `web_search` tool runs, then speak the live answer.

### Multi-character mode (subagents)

Real Hermes runs usually **delegate** work to subagents, where the actual tools run. To see each
subagent appear as its own character — a "boss" that dispatches, and workers that walk to the right
desk for the real tool they run — start Hermes with subagent events enabled:

```bash
API_SERVER_SUBAGENT_EVENTS=true API_SERVER_ENABLED=true hermes gateway run
```

This flag comes from a small, opt-in, backward-compatible patch to Hermes' API server
(`gateway/platforms/api_server.py` — forward `subagent.*` events on the run SSE). It is proposed
upstream as a pull request; without it (stock Hermes / flag off), Bureau still works in single-cube
mode automatically — no errors, just one character. Demo mode also showcases the multi-character
flow with no Hermes at all.

### Config

- `HERMES_URL` — Hermes API base URL (default `http://127.0.0.1:8642`)
- (Hermes side) `API_SERVER_SUBAGENT_EVENTS=true` — enable multi-character mode (see above)
- `API_SERVER_KEY` — if Hermes requires a Bearer token, set the same value here
- `PORT` — Bureau server port (default `8000`)

## Out of scope (for now)

Multiplayer, human control, persistence, Docker/Kubernetes, subagents-as-characters — all deferred
until the core concept is proven.
