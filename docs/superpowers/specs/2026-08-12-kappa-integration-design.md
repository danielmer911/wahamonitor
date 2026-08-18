# Kappa Ticket Handoff — Design

## Summary

Extend the WahaMonitor backend so that a ticket-worthy WhatsApp thread is
handed off to Kappa (the company's internal help-desk system,
`https://kappa.lambdaanalytics.co`) instead of only writing a local
markdown file. This is a **handoff-only** integration: WahaMonitor's
responsibility ends the moment a ticket successfully lands in Kappa.
Local file writing becomes a fallback used when a group has no Kappa
client mapped yet, or when the Kappa API call itself fails — not a
parallel system of record.

## Goals

- Map each monitored WhatsApp group to a Kappa `client` and (optionally)
  `project`, manageable via a couple of unauthenticated REST endpoints
  browsable through the backend's own FastAPI `/docs` (Swagger) UI — no
  separate admin tool needed.
- When a thread becomes ticket-worthy and its group has a client mapped,
  create a real ticket in Kappa via `POST /api/helpdesk/create-ordo/`,
  including any WhatsApp media as real file attachments
  (`multipart/form-data`, repeated `files` field).
- Never create a duplicate Kappa ticket for the same WhatsApp conversation
  snapshot, even across crashes/retries.
- Fall back to the existing local markdown ticket writer when there's no
  client mapping or the Kappa call fails — and flag the failure case for
  human follow-up.
- Keep the "which fields go where" logic isolated in one place, since
  several fields (severity, help_type, sla_classification) use fixed
  placeholder defaults today but are expected to become LLM-classified
  later.

## Non-goals (this stage)

- No LLM-based classification of severity/help_type/sla_classification —
  fixed defaults for now (see Field Mapping below).
- No syncing ticket status *back* from Kappa into WahaMonitor, and no
  `PATCH`/update calls after creation — pure one-way handoff.
- No automated retry of a failed Kappa call — a human handles it via
  `needs-review list` (existing CLI) once flagged.
- No resolution of the still-unmapped WAHA groups (Novedades Agente IA
  Omnicanal, VeriData, Onergy, Alerta de contratos GH, C.cajas-Lambda) or
  the ambiguous "Euro" client (id 60 vs 928) — those get mapped manually
  via the new endpoints once confirmed, outside this spec.

## Data Model Changes

`src/monitor/db.py` schema additions:

- `groups` table gains two nullable columns: `kappa_client_id INTEGER`,
  `kappa_project_id INTEGER`. Both default to absent/null — an unmapped
  group is simply a group where these are `NULL`.
- New table `kappa_tickets`:
  ```sql
  CREATE TABLE IF NOT EXISTS kappa_tickets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      group_id TEXT NOT NULL,
      sender_id TEXT NOT NULL,
      last_message_id TEXT NOT NULL,
      kappa_ticket_id INTEGER NOT NULL,
      kappa_token TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(group_id, sender_id, last_message_id)
  );
  ```
  `last_message_id` is the same uniqueness key the local ticket-folder
  naming already uses — the thread's last message at the moment it was
  evaluated. A thread can only become due for evaluation again after a
  genuinely new message arrives, so this triple never repeats for two
  distinct real conversations, which is what makes it safe to use as a
  duplicate-prevention key.

`src/monitor/config.py` gains a `kappa` section: `kappa_base_url: str`,
`kappa_api_key: str`.

## Kappa API Client (`src/monitor/kappa_client.py`)

A new module mirroring the existing `waha_client.py` pattern:

- `create_ticket(fields: dict, files: list[tuple[str, bytes, str]]) -> dict`
  — POSTs `multipart/form-data` to `/api/helpdesk/create-ordo/` with
  `api_key` and all `fields` as form fields, and one `files` part per
  `(filename, content, mimetype)` tuple. Returns the parsed JSON response
  (includes `id` and `token`).
- `list_clients() -> list[dict]` — paginates through
  `GET /api/clients-all-ordo/`, returns `{"id": int, "trade_name": str}`
  per client.
- `list_projects() -> list[dict]` — same shape, via
  `GET /api/initiatives-all-ordo/`.

Note: Kappa's endpoints accept the `api_key` in the request body/form
regardless of HTTP method (confirmed empirically — even `GET` requests
with a JSON body work). All three functions send it the same way rather
than relying on a header.

## Field Mapping (`src/monitor/kappa_payload.py`)

A single function, `build_kappa_payload(thread, decision, client_id, project_id) -> dict`,
isolates every WhatsApp-thread-to-Kappa-field decision so the fixed
defaults below are a one-place change when the LLM starts classifying
these instead:

| Kappa field | Source | Notes |
|---|---|---|
| `tomador_nombre` | `thread.sender_name` | |
| `tomador_telefono` | `thread.sender_id` | WhatsApp suffix (`@c.us` etc.) stripped |
| `description` | `f"{decision.summary}\n\n{decision.problem_description}"` | Spanish, matches existing ticket content |
| `help_type` | fixed default `"Soporte"` | placeholder pending real classification |
| `severity` | fixed default `"3"` | placeholder pending real classification |
| `sla_classification` | fixed default `"NORMAL"` | placeholder pending real classification |
| `incident_date` | thread's first message timestamp | |
| `client` | group's mapped `kappa_client_id` | required — this function is only called when present |
| `project` | group's mapped `kappa_project_id` | omitted/null if the group has no project mapped |
| `tomador_email`, `operational_impact`, `link`, `module` | — | not sourced from WhatsApp, omitted |

## Group → Client/Project Mapping Endpoints (`src/monitor/kappa_routes.py`)

New unauthenticated FastAPI router (consistent with the rest of the
backend's current no-auth posture), wired into `main.py` alongside the
existing webhook app:

- `GET /api/kappa/clients` — live-fetches Kappa's client list.
- `GET /api/kappa/projects` — live-fetches Kappa's project list.
- `GET /api/groups` — lists discovered WAHA groups with their current
  `kappa_client_id`/`kappa_project_id` (or `null`).
- `PUT /api/groups/{group_id}/mapping` — body
  `{"kappa_client_id": int | null, "kappa_project_id": int | null}`, sets
  both in one call. Either can be `null` to clear it.

All four are browsable and callable via the backend's built-in Swagger
UI at `/docs` — no separate admin tool needed for this workflow.

## Scheduler Integration

`process_due_threads` (in `src/monitor/scheduler.py`) changes what
happens for a ticket-worthy thread, inside the existing per-thread
try/except:

1. Look up the thread's group mapping (`kappa_client_id`).
2. **No client mapped** → write the local file (existing `write_ticket`),
   mark `ticketed`. No Kappa call attempted, no `needs_review` — this is
   an expected routing state, not an error.
3. **Client mapped** → check `kappa_tickets` for an existing row with
   this `(group_id, sender_id, last_message_id)`. If found, the ticket
   was already sent (e.g. a prior crash after success but before some
   other step) — skip straight to marking `ticketed`, no duplicate call.
4. Otherwise, download any WhatsApp media via the existing
   `waha_client.download_media`, build the payload via
   `build_kappa_payload`, and call `kappa_client.create_ticket`.
   - **Success** → insert the `kappa_tickets` row, mark `ticketed`.
   - **Failure** (network/HTTP error) → write the local file as fallback,
     mark `ticketed` **and** `needs_review`, so a human sees it in the
     existing `needs-review list` CLI command and knows Kappa is out of
     sync for this one.

## Error Handling

- Kappa API failures degrade to the local-file fallback rather than
  losing the ticket outright — matches the project's existing
  batch-isolation philosophy (one thread's failure never blocks others
  in the same scheduler tick).
- A `needs_review` thread from a Kappa failure still has a local file, so
  nothing is silently lost even though Kappa itself doesn't have it yet.
- The `kappa_tickets` UNIQUE constraint is the duplicate-prevention
  mechanism for retries *after* a row has been committed — once
  `record_kappa_ticket` commits, `has_existing_kappa_ticket` will find it
  and any re-evaluation of that thread is skipped rather than calling
  Kappa again.
- **Residual risk (accepted, not solved):** the constraint only protects
  the window *after* the local row commits. A process crash (OS kill,
  deploy, host restart) in the narrow window between `create_ticket`
  returning success and `record_kappa_ticket`'s `conn.commit()`
  completing leaves nothing recorded locally. On restart, the thread is
  still "due," gets re-evaluated, `has_existing_kappa_ticket` returns
  `False`, and `create_ticket` is called again — creating a real
  duplicate ticket in Kappa. This plan's non-goals explicitly exclude
  automated retry/reliability engineering for the Kappa call, so this
  window is an accepted operational risk rather than something this
  system guarantees against. Closing it (e.g. an idempotency key on the
  Kappa side, or an outbox-style two-phase commit) would be a materially
  larger feature and is left as a decision for later if it becomes a
  real operational problem.

## Testing

- `kappa_client.py`: respx-mocked multipart POST assertions (fields +
  files present), paginated list parsing — mirrors `waha_client.py`'s
  existing test style.
- `kappa_payload.py`: pure function, fixture thread/decision in → exact
  dict out, including the phone-number-stripping and optional-project
  cases.
- Scheduler: extend the existing per-thread test suite with the
  no-mapping/local-fallback path, the successful-handoff path, the
  Kappa-failure-with-local-fallback path, and the duplicate-skip path
  (pre-seed a `kappa_tickets` row, assert `create_ticket` is never
  called again for that key).
- `kappa_routes.py`: FastAPI `TestClient` tests for listing and mapping,
  mocking the Kappa list calls.

## Open Items (deferred, not blocking this spec)

- Confirming which of client `60`/`928` the six "Euro" groups actually
  belong to, and mapping the five still-unresolved groups — done via the
  new endpoints once confirmed, not part of building the feature itself.
- The exact MCP `api_key`/URL for WAHA's own MCP server remains
  unconfirmed — unrelated to this handoff, already a known gap from the
  original backend build.
