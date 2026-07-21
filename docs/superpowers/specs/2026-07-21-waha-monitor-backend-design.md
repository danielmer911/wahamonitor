# Dan's Beacon — WAHA Monitoring Agent (Backend), Stage 1

## Summary

A Python service ("Dan's Beacon") that listens to WAHA webhook events from a
WhatsApp account used only for inbound monitoring (no outbound messages in
this stage). It watches configured/auto-discovered WhatsApp support groups,
segments activity per sender, uses an LLM (with WAHA's MCP server for extra
context) to judge when a person has finished describing a problem, and
generates a ticket (Spanish-language summary + any attached media) as local
files. This spec covers the backend/agent only. A separate design will cover
the branded frontend dashboard (project name "Dan's Beacon", American vibe,
ochre color palette) that will read the tickets this backend produces.

## Goals

- Listen to WAHA webhook events for monitored WhatsApp groups.
- Auto-discover groups from WAHA; allow excluding specific groups (opt-out).
- Segment conversation per `(group, sender)` so overlapping/unrelated issues
  from different people in the same group don't get merged into one ticket.
- Decide when a sender's message is "done" (finished describing their issue)
  using both a cheap per-message LLM check and an inactivity-timeout fallback.
- On completion, use WAHA's MCP server to pull broader context, then have the
  LLM produce a Spanish-language ticket summary.
- Write the ticket (markdown) plus any downloaded media (images, audio,
  documents) into a per-thread folder under `tickets/`.
- Support swapping the LLM provider (Anthropic / OpenAI / Ollama) via config.
- Never send outbound WhatsApp messages in this stage.

## Non-goals (this stage)

- No outbound WhatsApp replies/acknowledgements.
- No frontend/dashboard (separate spec).
- No integration with external ticketing systems (Jira/Zendesk/etc.) — local
  files only for now.
- No multi-tenant/multi-account support — one WAHA account/session.

## Architecture & Components

- **Webhook receiver (FastAPI)** — receives WAHA's per-message webhook events
  (text, image, audio, document).
- **Group registry (SQLite)** — periodically synced from WAHA's group list
  (auto-discovery); includes an opt-out table for excluded groups, managed via
  a small CLI (`python -m monitor groups exclude <group_id>` /
  `groups list`).
- **Thread tracker (SQLite)** — one row per `(group_id, sender_id)`: buffered
  messages, last-activity timestamp, inactivity deadline, ticketed flag.
  Dedupes incoming events by WAHA message ID.
- **Scheduler** — background loop watching thread deadlines; fires deep
  evaluation when a sender's inactivity window elapses.
- **LLM abstraction layer** — provider-agnostic interface
  (`generate(prompt) -> text`). Anthropic implementation built first; OpenAI
  and Ollama implementations follow the same interface. Config selects the
  active provider + model. All prompts (quick check, deep evaluation, ticket
  summary) are written for Spanish-language conversations and produce
  Spanish-language output.
- **MCP client** — connects to WAHA's own MCP server so the deep-evaluation
  step can pull additional context (recent group history, sender info, media)
  beyond what the webhook payload included.
- **Ticket writer** — renders a Spanish-language markdown ticket and
  downloads referenced media into a per-thread folder.
- **Config** (`config.yaml` / `.env`) — WAHA base URL + API key, MCP server
  URL, active LLM provider/model/API key, default inactivity window (e.g. 10
  min), max thread lifetime before auto-archiving an unresolved thread.

## Data Flow

1. WAHA POSTs a message event to the webhook receiver.
2. Receiver dedupes by WAHA message ID, resolves sender + group, upserts the
   thread row (append message, reset last-activity, push out the inactivity
   deadline).
3. **Quick check** (cheap LLM call, Spanish prompt): "¿esta persona ya
   terminó de describir su problema?" — if yes, flag the thread for deep
   evaluation immediately instead of waiting out the timer.
4. **Deep evaluation** (triggered by quick-check "yes" or by the inactivity
   timer elapsing): agent calls the MCP client to pull extra context from
   WAHA, then asks the LLM to decide ticket-worthy or not, and if so, produce
   a Spanish summary + extracted fields (problem description, group name,
   sender, timestamps, attachments referenced).
5. If ticket-worthy: ticket writer downloads any media and writes
   `tickets/<fecha>_<grupo>_<remitente>_<id>/ticket.md` + attachments; thread
   marked ticketed.
6. If not ticket-worthy: thread stays open, deadline resets, waits for more
   messages or a longer max-timeout before being archived unticketed.

## Config & Group Discovery

- On startup and on a periodic interval, the agent calls WAHA's API to list
  groups the account belongs to, upserting into the group registry — new
  groups are picked up automatically, no restart required.
- Opt-out list stored in SQLite, editable via CLI, to silence specific
  groups.
- `config.yaml` holds connection/behavior settings not tied to a specific
  group: WAHA base URL/API key, MCP server URL, LLM provider/model/API key,
  default inactivity window, max thread lifetime.
- The agent is strictly read-only against WhatsApp — no outbound sends.

## Error Handling

- **WAHA/MCP unreachable** during deep evaluation: retry with backoff; if
  still failing, degrade gracefully by deciding using only the
  webhook-buffered messages already in the thread.
- **LLM provider failure**: one retry, then mark the thread `needs_review`
  (visible via CLI / a flag file in what would have been the ticket folder)
  rather than silently dropping a real complaint.
- **Duplicate/out-of-order webhook deliveries**: deduped via WAHA message ID
  uniqueness constraint in SQLite.
- **Crash/restart**: safe by construction — thread state, deadlines, group
  registry, and opt-outs all persist in SQLite; the scheduler resumes from
  persisted state.

## Testing

- Unit tests: per-sender thread segmentation, inactivity deadline math,
  dedupe logic, ticket markdown rendering, LLM abstraction interface (mocked
  provider).
- Integration testing: connected directly to the real production WAHA
  instance and real support groups (no stub/mock WAHA server) — acceptable
  here because the agent is strictly read-only (no outbound messages), so a
  bug can at worst produce a bad/missing ticket, not affect customers
  directly. Early runs should be watched closely for mis-segmented threads or
  bad LLM decisions given this hits live conversations.

## Deployment

- Packaged as a Docker image/container; actual hosting/deploy target to be
  decided later. Requires a publicly reachable webhook URL for the remote
  WAHA instance to deliver events to (tunneling or hosting detail, deferred).

## Open items for later stages

- Frontend dashboard ("Dan's Beacon" branding, American vibe, ochre color
  palette, font in the style of Stake/Coca-Cola/Canva) — separate spec.
- Outbound messaging (acknowledgements to customers) — not in scope yet.
- External ticketing system integration — not in scope yet.
- Public webhook hosting/tunneling strategy for the Docker deployment.
