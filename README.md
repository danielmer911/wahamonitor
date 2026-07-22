# Dan's Beacon — WAHA Monitoring Agent

Backend service that listens to WAHA webhook events, segments conversation
per WhatsApp group sender, and generates Spanish-language support tickets
under `tickets/` once a sender appears to have finished describing a problem.
Read-only against WhatsApp — no outbound messages are sent.

## Setup

1. Copy `config.example.yaml` to `config.yaml` and fill in your WAHA base
   URL/API key, MCP server URL/API key, and LLM provider credentials.
2. `pip install -e ".[dev]"`
3. `pytest` — runs the full automated test suite (all external services are
   mocked; no live WAHA/LLM calls happen here).
4. `uvicorn monitor.main:app_factory --factory --reload` — run the service locally.
5. Point your WAHA instance's webhook at `http://<host>:8000/webhook/waha`.

## Docker

The image only bundles `config.example.yaml` (placeholder credentials) — it
does **not** ship a real `config.yaml`, since that file holds live WAHA/MCP/LLM
API keys and should never be baked into an image. Before `docker run` will
work you must create your own `config.yaml` (see Setup step 1) and mount it
into the container:

```
docker build -t dans-beacon .
docker run -d \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/tickets:/app/tickets \
  -p 8000:8000 \
  dans-beacon
```

Without the `config.yaml` mount, the process fails at startup with
`FileNotFoundError: Config file not found: config.yaml`.

**DB path**: the Dockerfile sets `MONITOR_DB_PATH=/app/data/monitor.db`. Both
the running service (`monitor.main`) and `python -m monitor.cli` read this
environment variable, and when it is set it always wins over whatever
`storage.db_path` says in your mounted `config.yaml` — this guarantees the
service and the CLI operate on the same SQLite file even if the two disagree.
If you don't set `MONITOR_DB_PATH`, the service falls back to `config.yaml`'s
`storage.db_path` and the CLI falls back to `data/monitor.db`. In Docker,
just rely on `MONITOR_DB_PATH` (already set for you) rather than changing
`storage.db_path` in your mounted config, to avoid the two diverging.

## Manual production verification

Automated tests mock WAHA, the MCP server, and the LLM provider. Before
relying on this in production:

1. Deploy against the real WAHA instance with a real support group.
2. Send a short, clearly-finished complaint message into that group and
   confirm a ticket appears under `tickets/` within the configured
   inactivity window.
3. Send a message with a photo/voice note/document attached and confirm the
   attachment is downloaded into the ticket folder.
4. Check `python -m monitor.cli needs-review list` after a run to catch any
   threads where the LLM or MCP call failed.
5. Verify the MCP tool name used in `src/monitor/mcp_client.py`
   (`get_chat_messages`) matches what the real WAHA MCP server exposes —
   call its `tools/list` method if unsure, and update the constant if the
   name differs.

## CLI

- `python -m monitor.cli groups list` — show discovered groups and their
  excluded/active status.
- `python -m monitor.cli groups exclude <group_id>` — stop monitoring a
  group.
- `python -m monitor.cli groups include <group_id>` — resume monitoring a
  group.
- `python -m monitor.cli needs-review list` — list threads where evaluation
  failed and needs a human look.
