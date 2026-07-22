# Dan's Beacon — Frontend Dashboard Design

## Summary

A read-only internal dashboard for browsing the Spanish-language WhatsApp
support tickets that the existing "Dan's Beacon" backend writes to
`tickets/`. Built with React + Vite, styled with a "Diner Americana"
visual identity (mustard/ochre palette, Bebas Neue wordmark). Ships as a
single Docker image: the existing FastAPI backend serves both the JSON
API and the built frontend's static files, so there is one deploy, not
two. Users log in with email/password; an admin role can create new
accounts. Each ticket also carries a status (Pendiente / En progreso /
Resuelto) with a causa raíz + solución that the support team fills in,
plus a minimalist timeline of status changes.

## Goals

- Let the support team browse tickets: list view with filtering (group,
  date range, free-text search) and a detail view per ticket showing the
  Spanish summary, problem description, original messages, and inline
  media previews (images, audio, documents).
- Full user accounts (email + password), with an admin role that can
  create new accounts for teammates. No public signup.
- Let the support team mark each ticket's status (Pendiente / En
  progreso / Resuelto), record a causa raíz and solución (required to
  move to Resuelto), and see a minimalist history of that ticket's
  status changes.
- Single Docker deployment: one image, one container, serving both the
  API and the frontend.
- Match the established visual identity: Diner Americana palette
  (mustard `#e8a33d` / charcoal `#2b2420` / cream `#f4e3c1` / brown
  `#c97b2e`), Bebas Neue for the wordmark and headers, sidebar + table
  layout for the ticket list, single-column layout for ticket detail.

## Non-goals (this stage)

- No group-management UI (monitoring opt-out/include) — stays on the
  backend's existing CLI.
- No SSO/OAuth — email + password only.
- No real-time updates (polling/websockets) — a page refresh is enough
  for this stage.

## Backend Additions

New tables in the existing `monitor.db` SQLite database:

- `users(id, email, password_hash, role, created_at)` — `role` is either
  `"admin"` or `"user"`. No separate sessions table; auth uses a signed
  JWT in an httpOnly cookie (24h expiry) rather than server-side session
  storage.
- `ticket_status(ticket_id PRIMARY KEY, status, causa_raiz, solucion,
  updated_at)` — the current state of one ticket. `status` is one of
  `"pendiente"`, `"en_progreso"`, `"resuelto"`. A ticket with no row here
  is implicitly `"pendiente"` with empty `causa_raiz`/`solucion` — rows
  are only created the first time someone changes a ticket's status, so
  existing ticket files on disk don't need a backfill migration.
- `ticket_status_history(id, ticket_id, status, changed_by, changed_at)`
  — an append-only log; one row is inserted every time a ticket's status
  changes (not on every causa_raiz/solución edit), recording who made the
  change and when. This is what powers the status timeline.

New API endpoints on the existing FastAPI service:

- `POST /api/auth/login` — email + password → sets httpOnly JWT cookie
  on success, 401 on failure.
- `POST /api/auth/logout` — clears the auth cookie.
- `GET /api/auth/me` — returns the current user's email + role, 401 if
  not authenticated. The frontend uses this on load to determine auth
  state and role-gate the admin UI.
- `POST /api/admin/users` — creates a new user account (email, password,
  role). Admin-role only; 403 for non-admin callers.
- `GET /api/tickets` — lists tickets by scanning the `tickets/` folder on
  each request: parses each ticket folder name (date/group/sender) and
  reads the corresponding `ticket.md` for the summary snippet. Query
  params: `group`, `date_from`, `date_to`, `q` (free-text match against
  summary + problem description). A ticket folder that fails to parse
  (missing/corrupt `ticket.md`) is skipped and logged server-side rather
  than failing the whole listing.
- `GET /api/tickets/{ticket_id}` — full detail for one ticket: parsed
  markdown fields (summary, problem description, original messages), the
  list of its media filenames, its current status/causa_raiz/solución
  (defaulting to `"pendiente"` + empty fields if no `ticket_status` row
  exists yet), and its full status-change history (from
  `ticket_status_history`) for the timeline. Returning the full history
  alongside the ticket avoids a separate history endpoint — the
  frontend's compact dot view just shows the last couple of entries and
  the modal shows all of them.
- `GET /api/tickets/{ticket_id}/media/{filename}` — serves one media
  file from that ticket's folder, for inline preview or download.
- `PUT /api/tickets/{ticket_id}/status` — body: `{status, causa_raiz?,
  solucion?}`. Upserts the `ticket_status` row and, if `status` differs
  from the ticket's current status, appends a `ticket_status_history`
  row (`changed_by` = the authenticated user). Returns 400 if `status`
  is `"resuelto"` and either `causa_raiz` or `solucion` is empty —
  moving to Resuelto requires both fields filled in as part of the same
  submit. Moving between Pendiente and En progreso has no such
  requirement.

All ticket endpoints require any authenticated user (role doesn't
matter); only `/api/admin/users` checks for `role == "admin"`.

## Frontend Structure

- **Login page** — plain email/password form.
- **Ticket list page** — icon sidebar (nav + "DAN'S BEACON" wordmark) and
  a dense table of tickets (group, date, sender, summary snippet), with
  group/date-range/search filters above the table. Clicking a row
  navigates to that ticket's detail page.
- **Ticket detail page** — single column, top to bottom: ticket metadata
  header (group, sender, date), Spanish "Resumen", "Descripcion del
  problema", "Mensajes originales" (chronological), "Adjuntos" with
  inline previews (images render directly, audio gets a player, other
  documents show a download link with a file-type icon), and finally
  the **resolution panel**: a three-way segmented control for status
  (Pendiente / En progreso / Resuelto), "Causa raíz" and "Solución" text
  fields, a "Guardar" submit button, and a compact dot timeline
  underneath summarizing the last couple of status transitions.
  Submitting with status "Resuelto" and either field empty shows a
  validation error instead of calling the API. Clicking the compact
  dot timeline opens a modal with the full vertical status-change
  history (status + timestamp for every transition).
- **Admin: user management page** — list of existing users plus a
  create-user form (email, password, role). Only visible/reachable for
  admin-role accounts; the nav item is hidden for regular users, and the
  page itself checks `/api/auth/me`'s role before rendering (defense in
  depth alongside the backend's own 403).

A small API client module wraps the `/api/*` calls; auth state is
derived from `GET /api/auth/me` on app load, redirecting to `/login` if
unauthenticated, and redirecting away from `/login` if already
authenticated.

## Visual Design

- **Palette:** mustard/ochre `#e8a33d` as the primary accent; deep
  charcoal `#2b2420` for the sidebar and other dark surfaces; cream
  `#f4e3c1` and warm brown `#c97b2e` as supporting tones.
- **Typography:** Bebas Neue for the "DAN'S BEACON" wordmark and section
  headings; the system UI sans-serif stack for body text and table
  content (readability at small sizes takes priority there).
- **Layout:** icon sidebar + dense table for the ticket list; strict
  single-column top-to-bottom flow for ticket detail (header → resumen →
  mensajes originales → adjuntos → resolution panel).
- **Resolution panel:** segmented control for status, fields, "Guardar"
  button, and a compact dot-and-line timeline below it; clicking the
  compact timeline opens a modal/slide-over with the full vertical
  history (status + timestamp per entry).
- Mockups for all of the above were validated interactively during
  brainstorming (palette/font direction, font comparison, list layout,
  detail layout, resolution panel + timeline) before being written into
  this spec.

## Error Handling & Edge Cases

- Expired or missing auth cookie on any `/api/*` call → 401; frontend
  redirects to `/login`.
- Malformed/unreadable ticket folder → skipped from `/api/tickets`
  results with a server-side warning log, not a broken listing.
- Empty states (no tickets yet, no search results) render a plain
  message rather than an empty/broken table.
- Non-admin calling `/api/admin/users` → 403; frontend also hides that
  UI for non-admins as a first line of defense.
- Submitting status `"resuelto"` with an empty `causa_raiz` or
  `solucion` → 400 from the backend; the frontend also validates this
  client-side before submitting, so the common case never round-trips.

## Testing

- **Backend:** pytest tests for the new endpoints (login/logout/me,
  admin user creation and its 403 case, ticket list/detail/media, and
  the status endpoint's transitions including the resuelto-requires-
  both-fields 400 case and the history-row-per-status-change behavior),
  following the existing project's TDD + mocked-external-services
  pattern. Tests use a temporary `tickets/` folder with fixture ticket
  files; no real WAHA/LLM/MCP calls, consistent with the rest of the
  suite.
- **Frontend:** Vitest + React Testing Library for the key flows: login,
  ticket list rendering + filtering, ticket detail rendering with media
  previews, admin-only visibility of the user-management page, the
  resolution panel's status/field submission (including the client-side
  validation block on Resuelto with empty fields), and the compact
  timeline opening the full-history modal. The API client is mocked in
  these tests.

## Deployment

Single multi-stage `Dockerfile`:

1. **Build stage** — Node image, `npm run build` to produce the React
   app's static `dist/` output.
2. **Runtime stage** — the existing Python backend image, with the built
   `dist/` copied in and mounted as static files at `/` by FastAPI,
   alongside the existing `/api/*` routes.

Result: one image, one container, one `docker run` — no separate
frontend deployment or reverse-proxy step needed for this stage.
