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
4. `uvicorn monitor.main:app --reload` — run the service locally.
5. Point your WAHA instance's webhook at `http://<host>:8000/webhook/waha`.

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
