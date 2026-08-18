# Kappa Ticket Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hand off ticket-worthy WhatsApp threads to Kappa (the company's help-desk system) instead of only writing local markdown files, with per-group client/project mapping managed via the backend's own Swagger UI, real media attachments, and duplicate-safe traceability.

**Architecture:** A new `KappaClient` wraps Kappa's REST API (multipart ticket creation, paginated client/project lists). The scheduler's existing per-thread flow gains a branch: no client mapped on the group → local file (unchanged existing behavior); client mapped → build a payload, upload any media, call Kappa, and record the result in a new `kappa_tickets` table whose UNIQUE constraint is the actual duplicate-prevention mechanism. A small new router exposes group↔client/project mapping and live Kappa list lookups through the existing FastAPI app's `/docs`.

**Tech Stack:** Python 3.11+, httpx (already a dependency) for the Kappa HTTP client, existing pytest + respx test patterns.

**Spec:** `docs/superpowers/specs/2026-08-12-kappa-integration-design.md`

## Global Constraints

- Handoff-only: no field-mapping intelligence, no status sync back from Kappa, no automated retries. Fixed defaults for `help_type` ("Soporte"), `severity` ("3"), `sla_classification` ("NORMAL") — isolated in one function so they're a small change later.
- Local file writing (existing `write_ticket`) is a fallback only: used when a group has no `kappa_client_id` mapped, or when the Kappa API call itself fails.
- `kappa_tickets` uniqueness key is `(group_id, sender_id, last_message_id)` — the same "last message in the thread at ticketing time" key the local ticket-folder naming already uses, since a thread can only become due again after a genuinely new message arrives.
- Kappa's endpoints accept `api_key` in the request body/form regardless of HTTP method (confirmed empirically, including on `GET`) — never send it as a header.
- Kappa ticket creation always uses `multipart/form-data` (never plain JSON), with one repeated `files` field per attachment — confirmed via Kappa's dev.
- Kappa's `initiatives-all-ordo` endpoint denormalizes the *client's* name onto a field literally called `trade_name`, and the project's own display name is in a separate field called `initiative_name` — confirmed by cross-referencing known project IDs from real tickets. Do not confuse these two fields.
- The whole Kappa integration is optional at the config level: `kappa_base_url`/`kappa_api_key` default to `None` if the `kappa:` section is absent from `config.yaml`, so the already-running config doesn't break. When absent, `kappa_client` is `None` everywhere and the pipeline behaves exactly as it did before this plan (local files only).
- No database migration mechanism exists or is needed here — no production `data/monitor.db` file exists yet, so schema changes just go into the `CREATE TABLE IF NOT EXISTS` strings in `db.py`.

---

## File Structure

```
WahaMonitor/
  config.example.yaml          # Modify: add kappa: section (Task 1)
  src/monitor/
    db.py                        # Modify: groups columns + kappa_tickets table (Task 1)
    config.py                    # Modify: kappa_base_url, kappa_api_key (Task 1)
    groups.py                    # Modify: get_group_mapping, set_group_mapping, list_groups (Task 2)
    kappa_tickets.py              # Create: has_existing_kappa_ticket, record_kappa_ticket (Task 3)
    kappa_client.py                # Create: KappaClient (Task 4)
    tickets.py                      # Modify: extract guess_media_extension (Task 5)
    kappa_payload.py                 # Create: build_kappa_payload, collect_media_files (Task 5)
    scheduler.py                      # Modify: process_due_threads Kappa branch (Task 6)
    kappa_routes.py                    # Create: 4 endpoints (Task 7)
    main.py                             # Modify: wire KappaClient + kappa_routes (Task 8)
  tests/
    test_db.py                            # Modify (Task 1)
    test_config.py                         # Modify (Task 1)
    test_groups.py                          # Modify (Task 2)
    test_kappa_tickets.py                    # Create (Task 3)
    test_kappa_client.py                      # Create (Task 4)
    test_tickets.py                            # Modify (Task 5)
    test_kappa_payload.py                       # Create (Task 5)
    test_scheduler.py                            # Modify (Task 6)
    test_kappa_routes.py                          # Create (Task 7)
    test_main_smoke.py                             # Modify (Task 8)
```

---

### Task 1: Schema and config extensions

**Files:**
- Modify: `src/monitor/db.py`
- Modify: `src/monitor/config.py`
- Modify: `config.example.yaml`
- Modify: `tests/test_db.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `groups` table gains nullable `kappa_client_id INTEGER`, `kappa_project_id INTEGER`. New table `kappa_tickets(id, group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at)` with `UNIQUE(group_id, sender_id, last_message_id)`. `Config` gains `kappa_base_url: str | None`, `kappa_api_key: str | None`, both defaulting to `None` if the `kappa:` YAML section is absent.

- [ ] **Step 1: Write the failing tests for the schema**

Add to `tests/test_db.py` (add `import pytest` to the existing imports at the top of the file):

```python
def test_groups_table_has_kappa_mapping_columns(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO groups (group_id, name, excluded, last_synced_at, kappa_client_id, kappa_project_id) "
        "VALUES (?, ?, 0, ?, ?, ?)",
        ("g1", "Test Group", "2026-08-12T00:00:00", 60, 192),
    )
    conn.commit()

    row = conn.execute(
        "SELECT kappa_client_id, kappa_project_id FROM groups WHERE group_id = ?", ("g1",)
    ).fetchone()
    assert row == (60, 192)


def test_groups_kappa_mapping_columns_default_to_null(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO groups (group_id, name, excluded, last_synced_at) VALUES (?, ?, 0, ?)",
        ("g2", "Another Group", "2026-08-12T00:00:00"),
    )
    conn.commit()

    row = conn.execute(
        "SELECT kappa_client_id, kappa_project_id FROM groups WHERE group_id = ?", ("g2",)
    ).fetchone()
    assert row == (None, None)


def test_kappa_tickets_table_enforces_unique_constraint(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO kappa_tickets (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("g1", "s1", "m1", 203, "token-abc", "2026-08-12T00:00:00"),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO kappa_tickets (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("g1", "s1", "m1", 999, "token-xyz", "2026-08-12T01:00:00"),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `sqlite3.OperationalError: table groups has no column named kappa_client_id` (and the `kappa_tickets` test fails because the table doesn't exist).

- [ ] **Step 3: Implement the schema change**

In `src/monitor/db.py`, replace the `SCHEMA` string with:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    excluded INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT NOT NULL,
    kappa_client_id INTEGER,
    kappa_project_id INTEGER
);

CREATE TABLE IF NOT EXISTS threads (
    group_id TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    sender_name TEXT,
    messages_json TEXT NOT NULL DEFAULT '[]',
    last_activity_at TEXT NOT NULL,
    deadline_at TEXT NOT NULL,
    ticketed INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, sender_id)
);

CREATE TABLE IF NOT EXISTS seen_messages (
    message_id TEXT PRIMARY KEY
);

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
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Write the failing test for config**

Add to `tests/test_config.py`: two new assertion lines at the end of the existing `test_load_config_reads_all_fields` (its fixture YAML has no `kappa:` section, so this proves the default-to-`None` behavior):

```python
    assert config.kappa_base_url is None
    assert config.kappa_api_key is None
```

And a new test:

```python
def test_load_config_reads_kappa_section_when_present(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            waha:
              base_url: "https://waha.example.com"
              api_key: "waha-key"
            mcp:
              url: "https://waha.example.com/mcp"
              api_key: "mcp-key"
            llm:
              provider: "anthropic"
              model: "claude-sonnet-5"
              api_key: "llm-key"
            behavior:
              default_inactivity_minutes: 10
              max_thread_lifetime_minutes: 240
            storage:
              db_path: "data/monitor.db"
              tickets_dir: "tickets"
            kappa:
              base_url: "https://kappa.example.com"
              api_key: "kappa-key"
            """
        )
    )

    config = load_config(str(config_path))

    assert config.kappa_base_url == "https://kappa.example.com"
    assert config.kappa_api_key == "kappa-key"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'kappa_base_url'`

- [ ] **Step 7: Implement the config change**

In `src/monitor/config.py`, add to the `Config` dataclass (after `tickets_dir`):

```python
    kappa_base_url: str | None
    kappa_api_key: str | None
```

And in `load_config`, add to the `Config(...)` construction:

```python
        kappa_base_url=raw.get("kappa", {}).get("base_url"),
        kappa_api_key=raw.get("kappa", {}).get("api_key"),
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_config.py tests/test_db.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Update `config.example.yaml`**

Add this section anywhere after `storage:`:

```yaml
kappa:
  base_url: "https://kappa.example.com"
  api_key: "REPLACE_ME"
```

- [ ] **Step 10: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/db.py src/monitor/config.py config.example.yaml tests/test_db.py tests/test_config.py
git commit -m "feat: add Kappa schema (group mapping, ticket traceability) and config fields"
```

---

### Task 2: Group ↔ Kappa client/project mapping storage

**Files:**
- Modify: `src/monitor/groups.py`
- Modify: `tests/test_groups.py`

**Interfaces:**
- Consumes: the `groups` table's new `kappa_client_id`/`kappa_project_id` columns (Task 1).
- Produces: `get_group_mapping(conn, group_id: str) -> dict` (keys `kappa_client_id`, `kappa_project_id`, both `int | None`; `{"kappa_client_id": None, "kappa_project_id": None}` for an unknown group). `set_group_mapping(conn, group_id: str, kappa_client_id: int | None, kappa_project_id: int | None) -> None`. `list_groups(conn)` now returns dicts that also include `kappa_client_id` and `kappa_project_id`.

- [ ] **Step 1: Update the two existing `list_groups` assertions**

In `tests/test_groups.py`, update the two exact-dict-equality assertions to include the new keys (both `None`, since no mapping has been set in those tests):

```python
    assert groups == [
        {
            "group_id": "1@g.us",
            "name": "Soporte Acme",
            "excluded": False,
            "kappa_client_id": None,
            "kappa_project_id": None,
        }
    ]
```

(This appears in both `test_sync_groups_inserts_new_groups` and `test_sync_groups_updates_name_without_resetting_excluded` — update both, adjusting `"name"` and `"excluded"` to whatever each test already expects.)

- [ ] **Step 2: Write the failing tests for the new mapping functions**

Add to `tests/test_groups.py`:

```python
from monitor.groups import get_group_mapping, set_group_mapping


def test_get_group_mapping_defaults_to_none_for_unknown_group(tmp_path):
    conn = make_conn(tmp_path)
    assert get_group_mapping(conn, "unknown@g.us") == {"kappa_client_id": None, "kappa_project_id": None}


def test_set_and_get_group_mapping(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}]))

    set_group_mapping(conn, "1@g.us", kappa_client_id=60, kappa_project_id=192)

    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": 60, "kappa_project_id": 192}


def test_set_group_mapping_can_clear_with_none(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}]))
    set_group_mapping(conn, "1@g.us", kappa_client_id=60, kappa_project_id=192)

    set_group_mapping(conn, "1@g.us", kappa_client_id=None, kappa_project_id=None)

    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": None, "kappa_project_id": None}


def test_list_groups_includes_kappa_mapping(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}]))
    set_group_mapping(conn, "1@g.us", kappa_client_id=60, kappa_project_id=None)

    groups = list_groups(conn)

    assert groups == [
        {
            "group_id": "1@g.us",
            "name": "Soporte Acme",
            "excluded": False,
            "kappa_client_id": 60,
            "kappa_project_id": None,
        }
    ]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_groups.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_group_mapping'`, and the two updated assertions fail with a dict-mismatch (missing keys).

- [ ] **Step 4: Implement the changes in `src/monitor/groups.py`**

Replace `list_groups` with:

```python
def list_groups(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT group_id, name, excluded, kappa_client_id, kappa_project_id FROM groups ORDER BY name"
    ).fetchall()
    return [
        {
            "group_id": r[0],
            "name": r[1],
            "excluded": bool(r[2]),
            "kappa_client_id": r[3],
            "kappa_project_id": r[4],
        }
        for r in rows
    ]
```

Add at the end of the file:

```python
def get_group_mapping(conn, group_id: str) -> dict:
    row = conn.execute(
        "SELECT kappa_client_id, kappa_project_id FROM groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        return {"kappa_client_id": None, "kappa_project_id": None}
    return {"kappa_client_id": row[0], "kappa_project_id": row[1]}


def set_group_mapping(conn, group_id: str, kappa_client_id: int | None, kappa_project_id: int | None) -> None:
    conn.execute(
        "UPDATE groups SET kappa_client_id = ?, kappa_project_id = ? WHERE group_id = ?",
        (kappa_client_id, kappa_project_id, group_id),
    )
    conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_groups.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/groups.py tests/test_groups.py
git commit -m "feat: add group to Kappa client/project mapping storage"
```

---

### Task 3: Kappa ticket traceability (duplicate prevention)

**Files:**
- Create: `src/monitor/kappa_tickets.py`
- Test: `tests/test_kappa_tickets.py`

**Interfaces:**
- Consumes: the `kappa_tickets` table (Task 1).
- Produces: `has_existing_kappa_ticket(conn, group_id: str, sender_id: str, last_message_id: str) -> bool`. `record_kappa_ticket(conn, group_id: str, sender_id: str, last_message_id: str, kappa_ticket_id: int, kappa_token: str | None, now: datetime) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kappa_tickets.py
import sqlite3
from datetime import datetime, timezone

import pytest

from monitor.db import get_connection, init_db
from monitor.kappa_tickets import has_existing_kappa_ticket, record_kappa_ticket


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_has_existing_kappa_ticket_false_when_none_recorded(tmp_path):
    conn = make_conn(tmp_path)
    assert has_existing_kappa_ticket(conn, "g1", "s1", "m1") is False


def test_record_and_check_existing_kappa_ticket(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    record_kappa_ticket(conn, "g1", "s1", "m1", 203, "token-abc", now)

    assert has_existing_kappa_ticket(conn, "g1", "s1", "m1") is True
    assert has_existing_kappa_ticket(conn, "g1", "s1", "m2") is False
    assert has_existing_kappa_ticket(conn, "g1", "s2", "m1") is False


def test_record_kappa_ticket_twice_for_same_key_raises(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    record_kappa_ticket(conn, "g1", "s1", "m1", 203, "token-abc", now)

    with pytest.raises(sqlite3.IntegrityError):
        record_kappa_ticket(conn, "g1", "s1", "m1", 999, "token-xyz", now)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kappa_tickets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.kappa_tickets'`

- [ ] **Step 3: Implement `src/monitor/kappa_tickets.py`**

```python
from datetime import datetime


def has_existing_kappa_ticket(conn, group_id: str, sender_id: str, last_message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM kappa_tickets WHERE group_id = ? AND sender_id = ? AND last_message_id = ?",
        (group_id, sender_id, last_message_id),
    ).fetchone()
    return row is not None


def record_kappa_ticket(
    conn,
    group_id: str,
    sender_id: str,
    last_message_id: str,
    kappa_ticket_id: int,
    kappa_token: str | None,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO kappa_tickets (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, now.isoformat()),
    )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kappa_tickets.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/kappa_tickets.py tests/test_kappa_tickets.py
git commit -m "feat: add Kappa ticket traceability for duplicate prevention"
```

---

### Task 4: Kappa API client

**Files:**
- Create: `src/monitor/kappa_client.py`
- Test: `tests/test_kappa_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone HTTP client, mirrors `waha_client.py`'s style).
- Produces: `class KappaClient(base_url: str, api_key: str)` with `create_ticket(fields: dict, files: list[tuple[str, bytes, str]]) -> dict`, `list_clients() -> list[dict]` (each `{"id": int, "trade_name": str}`), `list_projects() -> list[dict]` (each `{"id": int, "name": str, "client_trade_name": str}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kappa_client.py
import httpx
import respx

from monitor.kappa_client import KappaClient


@respx.mock
def test_create_ticket_sends_multipart_with_api_key_and_fields():
    route = respx.post("https://kappa.example.com/api/helpdesk/create-ordo/").mock(
        return_value=httpx.Response(201, json={"id": 203, "token": "abc-123"})
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    result = client.create_ticket({"description": "Factura incorrecta", "client": 1}, [])

    assert result == {"id": 203, "token": "abc-123"}
    request = route.calls.last.request
    assert b'name="api_key"' in request.content
    assert b"test-key" in request.content
    assert b'name="description"' in request.content
    assert request.headers["content-type"].startswith("multipart/form-data")


@respx.mock
def test_create_ticket_attaches_files():
    route = respx.post("https://kappa.example.com/api/helpdesk/create-ordo/").mock(
        return_value=httpx.Response(201, json={"id": 204, "token": "def-456"})
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    client.create_ticket({"description": "Con foto"}, [("foto.jpg", b"fake-image-bytes", "image/jpeg")])

    request = route.calls.last.request
    assert b'name="files"; filename="foto.jpg"' in request.content
    assert b"fake-image-bytes" in request.content


@respx.mock
def test_list_clients_paginates_and_extracts_trade_name():
    respx.get("https://kappa.example.com/api/clients-all-ordo/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": "https://kappa.example.com/api/clients-all-ordo/?page=2",
                "previous": None,
                "results": [{"id": 1, "trade_name": "Lambda Analytics", "other_field": "ignored"}],
            },
        )
    )
    respx.get("https://kappa.example.com/api/clients-all-ordo/?page=2").mock(
        return_value=httpx.Response(
            200,
            json={"count": 2, "next": None, "previous": None, "results": [{"id": 60, "trade_name": "EURO SUPERMERCADOS"}]},
        )
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    clients = client.list_clients()

    assert clients == [
        {"id": 1, "trade_name": "Lambda Analytics"},
        {"id": 60, "trade_name": "EURO SUPERMERCADOS"},
    ]


@respx.mock
def test_list_projects_uses_initiative_name_not_trade_name():
    respx.get("https://kappa.example.com/api/initiatives-all-ordo/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 4, "trade_name": "Lambda Analytics", "initiative_name": "KAPPA"}],
            },
        )
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    projects = client.list_projects()

    assert projects == [{"id": 4, "name": "KAPPA", "client_trade_name": "Lambda Analytics"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kappa_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.kappa_client'`

- [ ] **Step 3: Implement `src/monitor/kappa_client.py`**

```python
import httpx


class KappaClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def create_ticket(self, fields: dict, files: list[tuple[str, bytes, str]]) -> dict:
        data = {"api_key": self.api_key, **fields}
        upload_files = [("files", (name, content, mimetype)) for name, content, mimetype in files]
        response = httpx.post(
            f"{self.base_url}/api/helpdesk/create-ordo/",
            data=data,
            files=upload_files,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def list_clients(self) -> list[dict]:
        items = self._get_all_pages(f"{self.base_url}/api/clients-all-ordo/")
        return [{"id": item["id"], "trade_name": item["trade_name"]} for item in items]

    def list_projects(self) -> list[dict]:
        items = self._get_all_pages(f"{self.base_url}/api/initiatives-all-ordo/")
        return [
            {"id": item["id"], "name": item["initiative_name"], "client_trade_name": item["trade_name"]}
            for item in items
        ]

    def _get_all_pages(self, url: str) -> list[dict]:
        results = []
        next_url = url
        while next_url:
            response = httpx.request("GET", next_url, json={"api_key": self.api_key}, timeout=30)
            response.raise_for_status()
            data = response.json()
            results.extend(data["results"])
            next_url = data.get("next")
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kappa_client.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/kappa_client.py tests/test_kappa_client.py
git commit -m "feat: add Kappa API client (create ticket, list clients/projects)"
```

---

### Task 5: Media extension helper extraction and field mapping

**Files:**
- Modify: `src/monitor/tickets.py`
- Modify: `tests/test_tickets.py`
- Create: `src/monitor/kappa_payload.py`
- Test: `tests/test_kappa_payload.py`

**Interfaces:**
- Consumes: `ThreadRecord`/`Message` (existing `threads.py`), `TicketDecision` (existing `evaluator.py`).
- Produces: `guess_media_extension(media: dict, media_url: str) -> str` (extracted from `tickets.py`, now reusable). `build_kappa_payload(thread: ThreadRecord, decision: TicketDecision, client_id: int, project_id: int | None) -> dict`. `collect_media_files(thread: ThreadRecord, waha_client) -> list[tuple[str, bytes, str]]` (downloads every message's media via `waha_client.download_media`, returns `(filename, content, mimetype)` tuples ready for `KappaClient.create_ticket`'s `files` argument).

- [ ] **Step 1: Extract `guess_media_extension` in `tickets.py` (refactor, no behavior change)**

Read the current `write_ticket` implementation in `src/monitor/tickets.py` first — it has an inline block computing a media file's extension from `mimetype`, falling back to the URL's extension, falling back to `.bin`. Extract that block into a standalone function, and call it from `write_ticket` instead:

```python
def guess_media_extension(media: dict, media_url: str) -> str:
    mimetype = media.get("mimetype")
    extension = None
    if mimetype:
        extension = mimetypes.guess_extension(mimetype)

    if not extension:
        extension = os.path.splitext(media_url)[1]

    if not extension:
        extension = ".bin"

    return extension
```

In `write_ticket`, replace the inline extension-computing lines with:

```python
        extension = guess_media_extension(message.media, media_url)
```

- [ ] **Step 2: Run the existing ticket tests to confirm the refactor didn't change behavior**

Run: `pytest tests/test_tickets.py -v`
Expected: PASS (all existing tests, unchanged — this step is a pure refactor, not new behavior)

- [ ] **Step 3: Add a focused test for the extracted function**

Add to `tests/test_tickets.py`:

```python
from monitor.tickets import guess_media_extension


def test_guess_media_extension_prefers_mimetype():
    assert guess_media_extension({"mimetype": "image/png"}, "https://example.com/file?x=1") == ".png"


def test_guess_media_extension_falls_back_to_url():
    assert guess_media_extension({}, "https://example.com/file.pdf") == ".pdf"


def test_guess_media_extension_falls_back_to_bin():
    assert guess_media_extension({}, "https://example.com/file") == ".bin"
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_tickets.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Write the failing test for `build_kappa_payload`**

```python
# tests/test_kappa_payload.py
from monitor.evaluator import TicketDecision
from monitor.kappa_payload import build_kappa_payload, collect_media_files
from monitor.threads import Message, ThreadRecord


def make_thread(messages=None):
    return ThreadRecord(
        group_id="1@g.us",
        sender_id="521555@c.us",
        sender_name="Juan Perez",
        messages=messages
        or [Message("m1", "Mi factura llego mal", None, "2026-08-12T10:00:00+00:00")],
        last_activity_at="2026-08-12T10:00:00+00:00",
        deadline_at="2026-08-12T10:10:00+00:00",
    )


def test_build_kappa_payload_maps_fixed_fields():
    thread = make_thread()
    decision = TicketDecision(
        ticket_worthy=True,
        summary="Cliente reporta factura incorrecta.",
        problem_description="La factura de julio llego con el monto equivocado.",
    )

    payload = build_kappa_payload(thread, decision, client_id=60, project_id=192)

    assert payload["tomador_nombre"] == "Juan Perez"
    assert payload["tomador_telefono"] == "521555"
    assert payload["description"] == (
        "Cliente reporta factura incorrecta.\n\nLa factura de julio llego con el monto equivocado."
    )
    assert payload["help_type"] == "Soporte"
    assert payload["severity"] == "3"
    assert payload["sla_classification"] == "NORMAL"
    assert payload["incident_date"] == "2026-08-12T10:00:00+00:00"
    assert payload["client"] == 60
    assert payload["project"] == 192


def test_build_kappa_payload_omits_project_when_none():
    thread = make_thread()
    decision = TicketDecision(True, "resumen", "problema")

    payload = build_kappa_payload(thread, decision, client_id=60, project_id=None)

    assert "project" not in payload
    assert payload["client"] == 60


class FakeWahaClient:
    def download_media(self, media_url: str) -> bytes:
        return b"fake-bytes-for-" + media_url.encode()


def test_collect_media_files_downloads_and_names_attachments():
    thread = make_thread(
        messages=[
            Message("m1", "Hola", None, "2026-08-12T10:00:00+00:00"),
            Message(
                "m2",
                "Foto",
                {"url": "https://waha.example.com/files/foto.jpg", "mimetype": "image/jpeg"},
                "2026-08-12T10:01:00+00:00",
            ),
        ]
    )

    files = collect_media_files(thread, FakeWahaClient())

    assert len(files) == 1
    filename, content, mimetype = files[0]
    assert filename == "adjunto_1.jpg"
    assert content == b"fake-bytes-for-https://waha.example.com/files/foto.jpg"
    assert mimetype == "image/jpeg"


def test_collect_media_files_returns_empty_list_when_no_media():
    thread = make_thread()
    assert collect_media_files(thread, FakeWahaClient()) == []
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_kappa_payload.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.kappa_payload'`

- [ ] **Step 7: Implement `src/monitor/kappa_payload.py`**

```python
from monitor.evaluator import TicketDecision
from monitor.threads import ThreadRecord
from monitor.tickets import guess_media_extension

DEFAULT_HELP_TYPE = "Soporte"
DEFAULT_SEVERITY = "3"
DEFAULT_SLA_CLASSIFICATION = "NORMAL"


def _strip_whatsapp_suffix(sender_id: str) -> str:
    return sender_id.split("@", 1)[0]


def build_kappa_payload(thread: ThreadRecord, decision: TicketDecision, client_id: int, project_id: int | None) -> dict:
    payload = {
        "tomador_nombre": thread.sender_name,
        "tomador_telefono": _strip_whatsapp_suffix(thread.sender_id),
        "description": f"{decision.summary}\n\n{decision.problem_description}",
        "help_type": DEFAULT_HELP_TYPE,
        "severity": DEFAULT_SEVERITY,
        "sla_classification": DEFAULT_SLA_CLASSIFICATION,
        "client": client_id,
    }
    if thread.messages:
        payload["incident_date"] = thread.messages[0].timestamp
    if project_id is not None:
        payload["project"] = project_id
    return payload


def collect_media_files(thread: ThreadRecord, waha_client) -> list[tuple[str, bytes, str]]:
    files = []
    index = 0
    for message in thread.messages:
        if not message.media:
            continue
        index += 1
        media_url = message.media["url"]
        content = waha_client.download_media(media_url)
        extension = guess_media_extension(message.media, media_url)
        mimetype = message.media.get("mimetype", "application/octet-stream")
        files.append((f"adjunto_{index}{extension}", content, mimetype))
    return files
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_kappa_payload.py -v`
Expected: PASS (5 passed)

- [ ] **Step 9: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/tickets.py tests/test_tickets.py src/monitor/kappa_payload.py tests/test_kappa_payload.py
git commit -m "feat: add Kappa field mapping and media collection, extract shared extension helper"
```

---

### Task 6: Scheduler integration

**Files:**
- Modify: `src/monitor/scheduler.py`
- Modify: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `get_group_mapping` (Task 2), `has_existing_kappa_ticket`/`record_kappa_ticket` (Task 3), `KappaClient.create_ticket` (Task 4), `build_kappa_payload`/`collect_media_files` (Task 5).
- Produces: `process_due_threads(conn, config, waha_client, llm, group_name_lookup: dict, now: datetime, kappa_client=None) -> int` — same signature as before, with `kappa_client` as a new trailing parameter defaulting to `None` so every existing call site (all 5 existing tests, and the pre-Task-8 state of `main.py`) keeps working unchanged. When `kappa_client` is `None`, behavior is byte-for-byte identical to before this task.

- [ ] **Step 1: Write the failing tests for the three new branches**

Add to `tests/test_scheduler.py` (add `from monitor.groups import set_group_mapping` to the imports):

```python
class FakeKappaClient:
    def __init__(self, response=None, error=None):
        self.response = response or {"id": 900, "token": "tok-900"}
        self.error = error
        self.calls = []

    def create_ticket(self, fields, files):
        self.calls.append((fields, files))
        if self.error:
            raise self.error
        return self.response


def test_process_due_threads_sends_to_kappa_when_client_mapped(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema", None, now.isoformat()), now, inactivity_minutes=10)
    set_group_mapping(conn, "g1", kappa_client_id=60, kappa_project_id=192)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(True, "resumen", "problema detallado"),
    )
    written_folders = []
    monkeypatch.setattr(
        "monitor.scheduler.write_ticket",
        lambda tickets_dir, group_name, thread, decision, waha_client, now: written_folders.append(group_name) or "folder",
    )

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    fake_kappa = FakeKappaClient()
    later = now + timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later,
        kappa_client=fake_kappa,
    )

    assert processed == 1
    assert written_folders == []  # local fallback NOT used
    assert len(fake_kappa.calls) == 1
    fields, files = fake_kappa.calls[0]
    assert fields["client"] == 60
    assert fields["project"] == 192

    from monitor.kappa_tickets import has_existing_kappa_ticket
    assert has_existing_kappa_ticket(conn, "g1", "s1", "m1") is True

    row = conn.execute(
        "SELECT ticketed, needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row == (1, 0)


def test_process_due_threads_skips_duplicate_kappa_send(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema", None, now.isoformat()), now, inactivity_minutes=10)
    set_group_mapping(conn, "g1", kappa_client_id=60, kappa_project_id=None)

    from monitor.kappa_tickets import record_kappa_ticket
    record_kappa_ticket(conn, "g1", "s1", "m1", 900, "tok-900", now)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(True, "resumen", "problema detallado"),
    )

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    fake_kappa = FakeKappaClient()
    later = now + timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later,
        kappa_client=fake_kappa,
    )

    assert processed == 1
    assert fake_kappa.calls == []  # never called again for the same key

    row = conn.execute(
        "SELECT ticketed FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row[0] == 1


def test_process_due_threads_falls_back_to_local_on_kappa_failure(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema", None, now.isoformat()), now, inactivity_minutes=10)
    set_group_mapping(conn, "g1", kappa_client_id=60, kappa_project_id=None)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(True, "resumen", "problema detallado"),
    )
    written_folders = []
    monkeypatch.setattr(
        "monitor.scheduler.write_ticket",
        lambda tickets_dir, group_name, thread, decision, waha_client, now: written_folders.append(group_name) or "folder",
    )

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    fake_kappa = FakeKappaClient(error=RuntimeError("Kappa is down"))
    later = now + timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later,
        kappa_client=fake_kappa,
    )

    assert processed == 1
    assert written_folders == ["Soporte Acme"]  # local fallback WAS used

    from monitor.kappa_tickets import has_existing_kappa_ticket
    assert has_existing_kappa_ticket(conn, "g1", "s1", "m1") is False  # nothing recorded, call failed

    row = conn.execute(
        "SELECT ticketed, needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row == (1, 1)  # ticketed via fallback, but flagged for human review
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL — `TypeError: process_due_threads() got an unexpected keyword argument 'kappa_client'`

- [ ] **Step 3: Implement the scheduler change**

Replace the full contents of `src/monitor/scheduler.py` with:

```python
from datetime import datetime

from monitor.evaluator import deep_evaluate
from monitor.groups import get_group_mapping
from monitor.kappa_payload import build_kappa_payload, collect_media_files
from monitor.kappa_tickets import has_existing_kappa_ticket, record_kappa_ticket
from monitor.mcp_client import fetch_context
from monitor.threads import (
    archive_thread,
    get_due_threads,
    get_stale_threads,
    mark_needs_review,
    mark_ticketed,
    reset_deadline,
)
from monitor.tickets import write_ticket


def _write_local_fallback(conn, config, waha_client, group_name_lookup, thread, decision, now):
    group_name = group_name_lookup.get(thread.group_id, thread.group_id)
    write_ticket(config.tickets_dir, group_name, thread, decision, waha_client, now)
    mark_ticketed(conn, thread.group_id, thread.sender_id)


def _handle_ticket_worthy_thread(conn, config, waha_client, kappa_client, group_name_lookup, thread, decision, now):
    last_message_id = thread.messages[-1].message_id if thread.messages else ""
    mapping = get_group_mapping(conn, thread.group_id)
    client_id = mapping["kappa_client_id"]

    if client_id is None or kappa_client is None:
        _write_local_fallback(conn, config, waha_client, group_name_lookup, thread, decision, now)
        return

    if has_existing_kappa_ticket(conn, thread.group_id, thread.sender_id, last_message_id):
        mark_ticketed(conn, thread.group_id, thread.sender_id)
        return

    try:
        fields = build_kappa_payload(thread, decision, client_id, mapping["kappa_project_id"])
        files = collect_media_files(thread, waha_client)
        result = kappa_client.create_ticket(fields, files)
        record_kappa_ticket(
            conn, thread.group_id, thread.sender_id, last_message_id, result["id"], result.get("token"), now
        )
        mark_ticketed(conn, thread.group_id, thread.sender_id)
    except Exception:
        _write_local_fallback(conn, config, waha_client, group_name_lookup, thread, decision, now)
        mark_needs_review(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)


def process_due_threads(
    conn, config, waha_client, llm, group_name_lookup: dict, now: datetime, kappa_client=None
) -> int:
    due_threads = get_due_threads(conn, now)

    for thread in due_threads:
        try:
            mcp_context = fetch_context(config.mcp_url, config.mcp_api_key, thread.group_id, thread.sender_id)
            decision = deep_evaluate(llm, mcp_context, thread)
            if decision.ticket_worthy:
                _handle_ticket_worthy_thread(
                    conn, config, waha_client, kappa_client, group_name_lookup, thread, decision, now
                )
            else:
                reset_deadline(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)
        except Exception:
            mark_needs_review(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)
            continue

    return len(due_threads)


def archive_stale_threads(conn, config, now: datetime) -> int:
    stale_threads = get_stale_threads(conn, now, config.max_thread_lifetime_minutes)

    for thread in stale_threads:
        archive_thread(conn, thread.group_id, thread.sender_id)

    return len(stale_threads)
```

Note: `mark_ticketed` already sets `needs_review = 0` (existing behavior in `threads.py`) — calling `mark_needs_review` immediately after it in the failure branch correctly leaves the final state as `ticketed=1, needs_review=1`, since `mark_needs_review` only touches the `needs_review`/`deadline_at` columns.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS (all 8 tests — 5 pre-existing + 3 new)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/scheduler.py tests/test_scheduler.py
git commit -m "feat: hand off ticket-worthy threads to Kappa when a client is mapped"
```

---

### Task 7: Kappa mapping and lookup routes

**Files:**
- Create: `src/monitor/kappa_routes.py`
- Test: `tests/test_kappa_routes.py`

**Interfaces:**
- Consumes: `list_groups`, `set_group_mapping` (Task 2), `KappaClient.list_clients`/`list_projects` (Task 4).
- Produces: `create_kappa_router(conn, kappa_client) -> APIRouter` with `GET /api/kappa/clients`, `GET /api/kappa/projects` (both return 503 if `kappa_client is None`), `GET /api/groups`, `PUT /api/groups/{group_id}/mapping` (both always available, regardless of whether Kappa itself is configured).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kappa_routes.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.groups import sync_groups
from monitor.kappa_routes import create_kappa_router


class FakeWahaClient:
    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


class FakeKappaClient:
    def list_clients(self):
        return [{"id": 1, "trade_name": "Lambda Analytics"}]

    def list_projects(self):
        return [{"id": 4, "name": "KAPPA", "client_trade_name": "Lambda Analytics"}]


def make_app(tmp_path, kappa_client):
    conn = get_connection(str(tmp_path / "monitor.db"), check_same_thread=False)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())

    app = FastAPI()
    app.include_router(create_kappa_router(conn, kappa_client))
    return app, conn


def test_get_kappa_clients_returns_list(tmp_path):
    app, _ = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.get("/api/kappa/clients")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "trade_name": "Lambda Analytics"}]


def test_get_kappa_clients_503_when_not_configured(tmp_path):
    app, _ = make_app(tmp_path, None)
    client = TestClient(app)

    response = client.get("/api/kappa/clients")

    assert response.status_code == 503


def test_get_kappa_projects_returns_list(tmp_path):
    app, _ = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.get("/api/kappa/projects")

    assert response.status_code == 200
    assert response.json() == [{"id": 4, "name": "KAPPA", "client_trade_name": "Lambda Analytics"}]


def test_get_groups_lists_discovered_groups_with_mapping(tmp_path):
    app, _ = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.get("/api/groups")

    assert response.status_code == 200
    assert response.json() == [
        {
            "group_id": "1@g.us",
            "name": "Soporte Acme",
            "excluded": False,
            "kappa_client_id": None,
            "kappa_project_id": None,
        }
    ]


def test_put_group_mapping_sets_client_and_project(tmp_path):
    app, conn = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.put("/api/groups/1@g.us/mapping", json={"kappa_client_id": 60, "kappa_project_id": 192})

    assert response.status_code == 200
    from monitor.groups import get_group_mapping
    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": 60, "kappa_project_id": 192}


def test_put_group_mapping_clears_with_null(tmp_path):
    app, conn = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)
    client.put("/api/groups/1@g.us/mapping", json={"kappa_client_id": 60, "kappa_project_id": 192})

    response = client.put("/api/groups/1@g.us/mapping", json={"kappa_client_id": None, "kappa_project_id": None})

    assert response.status_code == 200
    from monitor.groups import get_group_mapping
    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": None, "kappa_project_id": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kappa_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.kappa_routes'`

- [ ] **Step 3: Implement `src/monitor/kappa_routes.py`**

```python
from fastapi import APIRouter, HTTPException

from monitor.groups import list_groups, set_group_mapping


def create_kappa_router(conn, kappa_client) -> APIRouter:
    router = APIRouter()

    @router.get("/api/kappa/clients")
    def get_kappa_clients():
        if kappa_client is None:
            raise HTTPException(status_code=503, detail="Kappa is not configured")
        return kappa_client.list_clients()

    @router.get("/api/kappa/projects")
    def get_kappa_projects():
        if kappa_client is None:
            raise HTTPException(status_code=503, detail="Kappa is not configured")
        return kappa_client.list_projects()

    @router.get("/api/groups")
    def get_groups():
        return list_groups(conn)

    @router.put("/api/groups/{group_id}/mapping")
    def put_group_mapping(group_id: str, payload: dict):
        set_group_mapping(
            conn,
            group_id,
            kappa_client_id=payload.get("kappa_client_id"),
            kappa_project_id=payload.get("kappa_project_id"),
        )
        return {"status": "ok"}

    return router
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kappa_routes.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/kappa_routes.py tests/test_kappa_routes.py
git commit -m "feat: add group-to-Kappa mapping and lookup routes"
```

---

### Task 8: Wire everything into main.py

**Files:**
- Modify: `src/monitor/main.py`
- Modify: `tests/test_main_smoke.py`

**Interfaces:**
- Consumes: `KappaClient` (Task 4), `create_kappa_router` (Task 7), `process_due_threads`'s new `kappa_client` parameter (Task 6).
- Produces: `create_full_app` now constructs a `KappaClient` when `config.kappa_base_url`/`config.kappa_api_key` are both set (otherwise `kappa_client` stays `None`), mounts the Kappa router, and passes `kappa_client` into the scheduler loop's `process_due_threads` call.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_smoke.py`:

```python
def test_create_full_app_wires_kappa_routes_when_configured(tmp_path, monkeypatch):
    import textwrap

    monkeypatch.delenv("MONITOR_DB_PATH", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            waha:
              base_url: "https://waha.example.com"
              api_key: "waha-key"
            mcp:
              url: "https://waha.example.com/mcp"
              api_key: "mcp-key"
            llm:
              provider: "anthropic"
              model: "claude-sonnet-5"
              api_key: "llm-key"
            behavior:
              default_inactivity_minutes: 10
              max_thread_lifetime_minutes: 240
            storage:
              db_path: "{tmp_path}/monitor.db"
              tickets_dir: "{tmp_path}/tickets"
            kappa:
              base_url: "https://kappa.example.com"
              api_key: "kappa-key"
            """
        )
    )

    from monitor.main import create_full_app
    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    response = client.get("/api/groups")
    assert response.status_code == 200


def test_create_full_app_kappa_routes_503_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("MONITOR_DB_PATH", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
waha:
  base_url: "https://waha.example.com"
  api_key: "waha-key"
mcp:
  url: "https://waha.example.com/mcp"
  api_key: "mcp-key"
llm:
  provider: "anthropic"
  model: "claude-sonnet-5"
  api_key: "llm-key"
behavior:
  default_inactivity_minutes: 10
  max_thread_lifetime_minutes: 240
storage:
  db_path: "{tmp_path}/monitor.db"
  tickets_dir: "{tmp_path}/tickets"
"""
    )

    from monitor.main import create_full_app
    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    response = client.get("/api/kappa/clients")
    assert response.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_smoke.py -v`
Expected: FAIL — `404 Not Found` for `/api/groups` and `/api/kappa/clients` (routes not wired yet)

- [ ] **Step 3: Implement the wiring in `src/monitor/main.py`**

Add imports at the top:

```python
from monitor.kappa_client import KappaClient
from monitor.kappa_routes import create_kappa_router
```

In `create_full_app`, after `llm = get_provider(config)` and before `sync_groups(conn, waha_client)`, add:

```python
    kappa_client = None
    if config.kappa_base_url and config.kappa_api_key:
        kappa_client = KappaClient(config.kappa_base_url, config.kappa_api_key)
```

After `app = create_app(conn, config, llm)`, add:

```python
    app.include_router(create_kappa_router(conn, kappa_client))
```

Update `_run_scheduler_loop`'s signature and its call to `process_due_threads`:

```python
def _run_scheduler_loop(conn, config, waha_client, llm, kappa_client, stop_event: threading.Event):
    while not stop_event.is_set():
        group_name_lookup = {g["group_id"]: g["name"] for g in list_groups(conn)}
        now = datetime.now(timezone.utc)
        process_due_threads(conn, config, waha_client, llm, group_name_lookup, now, kappa_client=kappa_client)
        archive_stale_threads(conn, config, now)
        sync_groups(conn, waha_client)
        stop_event.wait(SCHEDULER_INTERVAL_SECONDS)
```

And update the thread-construction call inside `create_full_app` (in the `if start_background_scheduler:` block) to pass `kappa_client` through:

```python
        thread = threading.Thread(
            target=_run_scheduler_loop,
            args=(conn, config, waha_client, llm, kappa_client, stop_event),
            daemon=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_smoke.py -v`
Expected: PASS (all smoke tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -v`
Expected: all tests passing

```bash
git add src/monitor/main.py tests/test_main_smoke.py
git commit -m "feat: wire Kappa client and routes into the full app"
```

---

## Self-Review Notes

- **Spec coverage:** group→client/project mapping + Swagger-browsable endpoints ✅ (Task 7), real multipart media upload ✅ (Tasks 4-5), duplicate-safe traceability via the `kappa_tickets` UNIQUE constraint ✅ (Tasks 1, 3, 6), local-file fallback for both "no mapping" and "Kappa failure" cases ✅ (Task 6), isolated fixed-default field mapping for future LLM classification ✅ (Task 5), optional Kappa config that doesn't break the already-running setup ✅ (Task 1, 8).
- **Placeholder scan:** no `TBD`/`TODO` found; every step has concrete code or an exact command.
- **Type/interface consistency checked:** `get_group_mapping`'s return shape (`{"kappa_client_id", "kappa_project_id"}`) is used identically by Task 6's scheduler code and Task 7's routes. `KappaClient.create_ticket(fields, files)`'s `files` shape (`list[tuple[str, bytes, str]]`) matches exactly what `collect_media_files` (Task 5) produces and what Task 6 passes straight through. `process_due_threads`'s new `kappa_client=None` default means Tasks 1-5 alone leave the existing pipeline's behavior completely unchanged — the feature only activates once Task 6 lands.
- **Migration note carried over from the spec:** no production `data/monitor.db` exists yet, so the schema changes in Task 1 need no migration path — confirmed by checking the repo before writing this plan.

