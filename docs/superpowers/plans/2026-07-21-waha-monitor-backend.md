# Dan's Beacon — WAHA Monitoring Agent (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python backend that receives WAHA webhook events, segments conversation per sender, decides via LLM when a complaint is complete, and writes Spanish-language ticket files with attached media.

**Architecture:** A FastAPI webhook receiver upserts incoming messages into a SQLite-backed thread tracker keyed by `(group_id, sender_id)`. A background scheduler polls for threads whose inactivity deadline has elapsed; both the scheduler and the webhook's own "quick check" can trigger a deep evaluation step that pulls extra context from WAHA's MCP server and asks a pluggable LLM provider to decide if a ticket should be written. Ticket output is markdown + downloaded media under `tickets/`.

**Tech Stack:** Python 3.11+, FastAPI + uvicorn, httpx, stdlib sqlite3, PyYAML, Anthropic SDK (first LLM provider), pytest + respx for testing.

## Global Constraints

- No outbound WhatsApp messages anywhere in this codebase — read-only against WAHA.
- All LLM prompts and generated ticket content are in Spanish.
- Conversation state (threads, group registry, opt-outs, seen message IDs) persists in SQLite — no in-memory-only state that would be lost on restart.
- Segmentation unit is `(group_id, sender_id)`, never the whole group.
- LLM provider must go through the `LLMProvider` interface (`generate(prompt: str) -> str`) — no direct SDK calls outside `src/monitor/llm/`.
- Integration testing against real WAHA happens manually against production later (per spec); automated tests in this plan mock all external services (WAHA REST, MCP, LLM).

---

## File Structure

```
WahaMonitor/
  pyproject.toml
  config.example.yaml
  Dockerfile
  README.md
  src/monitor/
    __init__.py
    config.py          # Task 1
    db.py               # Task 2
    waha_client.py       # Task 3
    groups.py            # Task 4
    threads.py           # Task 5
    llm/
      __init__.py
      base.py            # Task 6
      anthropic_provider.py
      factory.py
    evaluator.py          # Task 7
    mcp_client.py          # Task 8
    tickets.py             # Task 9
    scheduler.py            # Task 10
    webhook.py               # Task 11
    cli.py                    # Task 12
    main.py                    # Task 13
  tests/
    test_config.py
    test_db.py
    test_waha_client.py
    test_groups.py
    test_threads.py
    test_llm_factory.py
    test_evaluator.py
    test_mcp_client.py
    test_tickets.py
    test_scheduler.py
    test_webhook.py
    test_cli.py
    test_main_smoke.py
```

---

### Task 1: Project scaffolding & config loader

**Files:**
- Create: `pyproject.toml`
- Create: `config.example.yaml`
- Create: `src/monitor/__init__.py`
- Create: `src/monitor/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` dataclass with fields `waha_base_url: str`, `waha_api_key: str`, `mcp_url: str`, `mcp_api_key: str | None`, `llm_provider: str`, `llm_model: str`, `llm_api_key: str`, `default_inactivity_minutes: int`, `max_thread_lifetime_minutes: int`, `db_path: str`, `tickets_dir: str`. Function `load_config(path: str) -> Config`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "dans-beacon"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "anthropic>=0.30",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "respx>=0.21",
]

[tool.setuptools.packages.find]
where = ["src"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Write `config.example.yaml`**

```yaml
waha:
  base_url: "https://waha.example.com"
  api_key: "REPLACE_ME"

mcp:
  url: "https://waha.example.com/mcp"
  api_key: "REPLACE_ME"

llm:
  provider: "anthropic"
  model: "claude-sonnet-5"
  api_key: "REPLACE_ME"

behavior:
  default_inactivity_minutes: 10
  max_thread_lifetime_minutes: 240

storage:
  db_path: "data/monitor.db"
  tickets_dir: "tickets"
```

- [ ] **Step 3: Create empty `src/monitor/__init__.py`**

```python
```

- [ ] **Step 4: Write the failing test for config loading**

```python
# tests/test_config.py
import textwrap

import pytest

from monitor.config import load_config


def test_load_config_reads_all_fields(tmp_path):
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
            """
        )
    )

    config = load_config(str(config_path))

    assert config.waha_base_url == "https://waha.example.com"
    assert config.waha_api_key == "waha-key"
    assert config.mcp_url == "https://waha.example.com/mcp"
    assert config.mcp_api_key == "mcp-key"
    assert config.llm_provider == "anthropic"
    assert config.llm_model == "claude-sonnet-5"
    assert config.llm_api_key == "llm-key"
    assert config.default_inactivity_minutes == 10
    assert config.max_thread_lifetime_minutes == 240
    assert config.db_path == "data/monitor.db"
    assert config.tickets_dir == "tickets"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "missing.yaml"))
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.config'` (or `monitor`).

- [ ] **Step 6: Implement `src/monitor/config.py`**

```python
import os
from dataclasses import dataclass

import yaml


@dataclass
class Config:
    waha_base_url: str
    waha_api_key: str
    mcp_url: str
    mcp_api_key: str | None
    llm_provider: str
    llm_model: str
    llm_api_key: str
    default_inactivity_minutes: int
    max_thread_lifetime_minutes: int
    db_path: str
    tickets_dir: str


def load_config(path: str) -> Config:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return Config(
        waha_base_url=raw["waha"]["base_url"],
        waha_api_key=raw["waha"]["api_key"],
        mcp_url=raw["mcp"]["url"],
        mcp_api_key=raw["mcp"].get("api_key"),
        llm_provider=raw["llm"]["provider"],
        llm_model=raw["llm"]["model"],
        llm_api_key=raw["llm"]["api_key"],
        default_inactivity_minutes=raw["behavior"]["default_inactivity_minutes"],
        max_thread_lifetime_minutes=raw["behavior"]["max_thread_lifetime_minutes"],
        db_path=raw["storage"]["db_path"],
        tickets_dir=raw["storage"]["tickets_dir"],
    )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml config.example.yaml src/monitor/__init__.py src/monitor/config.py tests/test_config.py
git commit -m "feat: add project scaffolding and config loader"
```

---

### Task 2: SQLite schema & connection helper

**Files:**
- Create: `src/monitor/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `get_connection(db_path: str) -> sqlite3.Connection`, `init_db(conn: sqlite3.Connection) -> None`. Schema tables: `groups(group_id TEXT PRIMARY KEY, name TEXT, excluded INTEGER, last_synced_at TEXT)`, `threads(group_id TEXT, sender_id TEXT, sender_name TEXT, messages_json TEXT, last_activity_at TEXT, deadline_at TEXT, ticketed INTEGER, needs_review INTEGER, PRIMARY KEY(group_id, sender_id))`, `seen_messages(message_id TEXT PRIMARY KEY)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import os
import sqlite3

from monitor.db import get_connection, init_db


def test_init_db_creates_expected_tables(tmp_path):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}

    assert {"groups", "threads", "seen_messages"} <= tables
    assert os.path.isfile(db_path)


def test_init_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    init_db(conn)  # must not raise

    conn.execute("INSERT INTO groups (group_id, name, excluded, last_synced_at) VALUES (?, ?, ?, ?)",
                 ("g1", "Test Group", 0, "2026-07-21T00:00:00"))
    conn.commit()
    row = conn.execute("SELECT name FROM groups WHERE group_id = ?", ("g1",)).fetchone()
    assert row[0] == "Test Group"


def test_get_connection_creates_parent_directory(tmp_path):
    db_path = str(tmp_path / "nested" / "dir" / "monitor.db")
    conn = get_connection(db_path)
    assert isinstance(conn, sqlite3.Connection)
    assert os.path.isdir(tmp_path / "nested" / "dir")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.db'`

- [ ] **Step 3: Implement `src/monitor/db.py`**

```python
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    excluded INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT NOT NULL
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
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return sqlite3.connect(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/db.py tests/test_db.py
git commit -m "feat: add sqlite schema and connection helper"
```

---

### Task 3: WAHA REST client

**Files:**
- Create: `src/monitor/waha_client.py`
- Test: `tests/test_waha_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `class WahaClient` with `__init__(self, base_url: str, api_key: str)`, `list_groups(self) -> list[dict]` (each dict has `id` and `name`), `download_media(self, media_url: str) -> bytes`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_waha_client.py
import httpx
import respx

from monitor.waha_client import WahaClient


@respx.mock
def test_list_groups_returns_id_and_name():
    respx.get("https://waha.example.com/api/default/groups").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "1@g.us", "name": "Soporte Acme"},
                {"id": "2@g.us", "name": "Soporte Beta"},
            ],
        )
    )
    client = WahaClient("https://waha.example.com", "test-key")

    groups = client.list_groups()

    assert groups == [
        {"id": "1@g.us", "name": "Soporte Acme"},
        {"id": "2@g.us", "name": "Soporte Beta"},
    ]


@respx.mock
def test_list_groups_sends_api_key_header():
    route = respx.get("https://waha.example.com/api/default/groups").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = WahaClient("https://waha.example.com", "test-key")

    client.list_groups()

    assert route.calls.last.request.headers["X-Api-Key"] == "test-key"


@respx.mock
def test_download_media_returns_bytes():
    respx.get("https://waha.example.com/files/photo.jpg").mock(
        return_value=httpx.Response(200, content=b"fake-image-bytes")
    )
    client = WahaClient("https://waha.example.com", "test-key")

    data = client.download_media("https://waha.example.com/files/photo.jpg")

    assert data == b"fake-image-bytes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_waha_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.waha_client'`

- [ ] **Step 3: Implement `src/monitor/waha_client.py`**

```python
import httpx


class WahaClient:
    def __init__(self, base_url: str, api_key: str, session: str = "default"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key}

    def list_groups(self) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/api/{self.session}/groups",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def download_media(self, media_url: str) -> bytes:
        response = httpx.get(media_url, headers=self._headers(), timeout=60)
        response.raise_for_status()
        return response.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_waha_client.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/waha_client.py tests/test_waha_client.py
git commit -m "feat: add WAHA REST client"
```

---

### Task 4: Group registry, auto-discovery & opt-out

**Files:**
- Create: `src/monitor/groups.py`
- Test: `tests/test_groups.py`

**Interfaces:**
- Consumes: `get_connection`/`init_db` (Task 2), `WahaClient.list_groups() -> list[dict]` (Task 3, shape `{"id": str, "name": str}`).
- Produces: `sync_groups(conn, waha_client) -> int`, `exclude_group(conn, group_id: str) -> None`, `include_group(conn, group_id: str) -> None`, `list_groups(conn) -> list[dict]` (each `{"group_id", "name", "excluded"}`), `is_excluded(conn, group_id: str) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_groups.py
from monitor.db import get_connection, init_db
from monitor.groups import (
    exclude_group,
    include_group,
    is_excluded,
    list_groups,
    sync_groups,
)


class FakeWahaClient:
    def __init__(self, groups):
        self._groups = groups

    def list_groups(self):
        return self._groups


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_sync_groups_inserts_new_groups(tmp_path):
    conn = make_conn(tmp_path)
    waha = FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}])

    count = sync_groups(conn, waha)

    assert count == 1
    groups = list_groups(conn)
    assert groups == [{"group_id": "1@g.us", "name": "Soporte Acme", "excluded": False}]


def test_sync_groups_updates_name_without_resetting_excluded(tmp_path):
    conn = make_conn(tmp_path)
    waha = FakeWahaClient([{"id": "1@g.us", "name": "Old Name"}])
    sync_groups(conn, waha)
    exclude_group(conn, "1@g.us")

    waha_renamed = FakeWahaClient([{"id": "1@g.us", "name": "New Name"}])
    sync_groups(conn, waha_renamed)

    groups = list_groups(conn)
    assert groups == [{"group_id": "1@g.us", "name": "New Name", "excluded": True}]


def test_exclude_and_include_group(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "G"}]))

    exclude_group(conn, "1@g.us")
    assert is_excluded(conn, "1@g.us") is True

    include_group(conn, "1@g.us")
    assert is_excluded(conn, "1@g.us") is False


def test_is_excluded_unknown_group_is_false(tmp_path):
    conn = make_conn(tmp_path)
    assert is_excluded(conn, "unknown@g.us") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_groups.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.groups'`

- [ ] **Step 3: Implement `src/monitor/groups.py`**

```python
from datetime import datetime, timezone


def sync_groups(conn, waha_client) -> int:
    now = datetime.now(timezone.utc).isoformat()
    remote_groups = waha_client.list_groups()

    for group in remote_groups:
        conn.execute(
            """
            INSERT INTO groups (group_id, name, excluded, last_synced_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                name = excluded.name,
                last_synced_at = excluded.last_synced_at
            """,
            (group["id"], group["name"], now),
        )
    conn.commit()
    return len(remote_groups)


def exclude_group(conn, group_id: str) -> None:
    conn.execute("UPDATE groups SET excluded = 1 WHERE group_id = ?", (group_id,))
    conn.commit()


def include_group(conn, group_id: str) -> None:
    conn.execute("UPDATE groups SET excluded = 0 WHERE group_id = ?", (group_id,))
    conn.commit()


def is_excluded(conn, group_id: str) -> bool:
    row = conn.execute(
        "SELECT excluded FROM groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    return bool(row[0]) if row else False


def list_groups(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT group_id, name, excluded FROM groups ORDER BY name"
    ).fetchall()
    return [
        {"group_id": r[0], "name": r[1], "excluded": bool(r[2])} for r in rows
    ]
```

Note: `ON CONFLICT ... DO UPDATE SET name = excluded.name` refers to SQLite's special `excluded` pseudo-table for upserts, not the `excluded` column of our `groups` table — this is standard SQLite upsert syntax, not a naming collision.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_groups.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/groups.py tests/test_groups.py
git commit -m "feat: add group registry with auto-discovery and opt-out"
```

---

### Task 5: Thread tracker (segmentation, dedupe, deadlines)

**Files:**
- Create: `src/monitor/threads.py`
- Test: `tests/test_threads.py`

**Interfaces:**
- Consumes: `get_connection`/`init_db` (Task 2).
- Produces:
  - `@dataclass Message(message_id: str, text: str, media: dict | None, timestamp: str)`
  - `@dataclass ThreadRecord(group_id: str, sender_id: str, sender_name: str, messages: list[Message], last_activity_at: str, deadline_at: str)`
  - `upsert_message(conn, group_id: str, sender_id: str, sender_name: str, message: Message, now: datetime, inactivity_minutes: int) -> bool` — returns `False` if `message.message_id` was already seen (duplicate), `True` otherwise.
  - `get_due_threads(conn, now: datetime) -> list[ThreadRecord]` — threads with `deadline_at <= now` and not yet ticketed.
  - `mark_ticketed(conn, group_id: str, sender_id: str) -> None`
  - `mark_needs_review(conn, group_id: str, sender_id: str) -> None`
  - `reset_deadline(conn, group_id: str, sender_id: str, now: datetime, inactivity_minutes: int) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_threads.py
from datetime import datetime, timedelta, timezone

from monitor.db import get_connection, init_db
from monitor.threads import (
    Message,
    get_due_threads,
    mark_needs_review,
    mark_ticketed,
    reset_deadline,
    upsert_message,
)


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_upsert_message_creates_new_thread(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    msg = Message(message_id="m1", text="Hola, tengo un problema", media=None, timestamp=now.isoformat())

    applied = upsert_message(conn, "g1", "s1", "Juan", msg, now, inactivity_minutes=10)

    assert applied is True
    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert len(due) == 1
    assert due[0].group_id == "g1"
    assert due[0].sender_id == "s1"
    assert due[0].sender_name == "Juan"
    assert [m.message_id for m in due[0].messages] == ["m1"]


def test_upsert_message_deduplicates_by_message_id(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    msg = Message(message_id="m1", text="Hola", media=None, timestamp=now.isoformat())

    first = upsert_message(conn, "g1", "s1", "Juan", msg, now, inactivity_minutes=10)
    second = upsert_message(conn, "g1", "s1", "Juan", msg, now, inactivity_minutes=10)

    assert first is True
    assert second is False
    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert len(due[0].messages) == 1


def test_interleaved_senders_are_segmented_independently(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)

    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema A", None, now.isoformat()), now, 10)
    upsert_message(conn, "g1", "s2", "Maria", Message("m2", "Problema B", None, now.isoformat()), now, 10)
    upsert_message(conn, "g1", "s1", "Juan", Message("m3", "Mas detalles A", None, now.isoformat()), now, 10)

    due = get_due_threads(conn, now + timedelta(minutes=11))
    by_sender = {t.sender_id: t for t in due}

    assert set(by_sender) == {"s1", "s2"}
    assert [m.message_id for m in by_sender["s1"].messages] == ["m1", "m3"]
    assert [m.message_id for m in by_sender["s2"].messages] == ["m2"]


def test_get_due_threads_excludes_threads_before_deadline(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    due = get_due_threads(conn, now + timedelta(minutes=5))

    assert due == []


def test_mark_ticketed_excludes_thread_from_due_list(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    mark_ticketed(conn, "g1", "s1")

    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert due == []


def test_reset_deadline_pushes_thread_out_of_due_list(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    reset_deadline(conn, "g1", "s1", now + timedelta(minutes=9), inactivity_minutes=10)

    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert due == []


def test_mark_needs_review_does_not_remove_from_due_list(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    mark_needs_review(conn, "g1", "s1")

    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert len(due) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_threads.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.threads'`

- [ ] **Step 3: Implement `src/monitor/threads.py`**

```python
import json
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Message:
    message_id: str
    text: str
    media: dict | None
    timestamp: str


@dataclass
class ThreadRecord:
    group_id: str
    sender_id: str
    sender_name: str
    messages: list[Message]
    last_activity_at: str
    deadline_at: str


def _row_to_thread(row) -> ThreadRecord:
    group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at = row
    messages = [Message(**m) for m in json.loads(messages_json)]
    return ThreadRecord(group_id, sender_id, sender_name, messages, last_activity_at, deadline_at)


def upsert_message(
    conn,
    group_id: str,
    sender_id: str,
    sender_name: str,
    message: Message,
    now: datetime,
    inactivity_minutes: int,
) -> bool:
    seen = conn.execute(
        "SELECT 1 FROM seen_messages WHERE message_id = ?", (message.message_id,)
    ).fetchone()
    if seen:
        return False
    conn.execute("INSERT INTO seen_messages (message_id) VALUES (?)", (message.message_id,))

    deadline_at = (now + timedelta(minutes=inactivity_minutes)).isoformat()
    row = conn.execute(
        "SELECT messages_json FROM threads WHERE group_id = ? AND sender_id = ?",
        (group_id, sender_id),
    ).fetchone()

    if row is None:
        messages_json = json.dumps([message.__dict__])
        conn.execute(
            """
            INSERT INTO threads
                (group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at, ticketed, needs_review)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (group_id, sender_id, sender_name, messages_json, now.isoformat(), deadline_at),
        )
    else:
        existing = json.loads(row[0])
        existing.append(message.__dict__)
        conn.execute(
            """
            UPDATE threads
            SET messages_json = ?, last_activity_at = ?, deadline_at = ?, ticketed = 0
            WHERE group_id = ? AND sender_id = ?
            """,
            (json.dumps(existing), now.isoformat(), deadline_at, group_id, sender_id),
        )
    conn.commit()
    return True


def get_due_threads(conn, now: datetime) -> list[ThreadRecord]:
    rows = conn.execute(
        """
        SELECT group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at
        FROM threads
        WHERE ticketed = 0 AND deadline_at <= ?
        """,
        (now.isoformat(),),
    ).fetchall()
    return [_row_to_thread(row) for row in rows]


def mark_ticketed(conn, group_id: str, sender_id: str) -> None:
    conn.execute(
        "UPDATE threads SET ticketed = 1 WHERE group_id = ? AND sender_id = ?",
        (group_id, sender_id),
    )
    conn.commit()


def mark_needs_review(conn, group_id: str, sender_id: str) -> None:
    conn.execute(
        "UPDATE threads SET needs_review = 1 WHERE group_id = ? AND sender_id = ?",
        (group_id, sender_id),
    )
    conn.commit()


def reset_deadline(conn, group_id: str, sender_id: str, now: datetime, inactivity_minutes: int) -> None:
    deadline_at = (now + timedelta(minutes=inactivity_minutes)).isoformat()
    conn.execute(
        "UPDATE threads SET deadline_at = ? WHERE group_id = ? AND sender_id = ?",
        (deadline_at, group_id, sender_id),
    )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_threads.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/threads.py tests/test_threads.py
git commit -m "feat: add per-sender thread tracker with dedupe and deadlines"
```

---

### Task 6: LLM abstraction layer & Anthropic provider

**Files:**
- Create: `src/monitor/llm/__init__.py`
- Create: `src/monitor/llm/base.py`
- Create: `src/monitor/llm/anthropic_provider.py`
- Create: `src/monitor/llm/factory.py`
- Test: `tests/test_llm_factory.py`

**Interfaces:**
- Consumes: `Config` (Task 1) fields `llm_provider`, `llm_model`, `llm_api_key`.
- Produces: `class LLMProvider(Protocol): def generate(self, prompt: str) -> str: ...`, `class AnthropicProvider(model: str, api_key: str)` implementing it, `get_provider(config: Config) -> LLMProvider`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_factory.py
from unittest.mock import MagicMock, patch

import pytest

from monitor.config import Config
from monitor.llm.factory import get_provider
from monitor.llm.anthropic_provider import AnthropicProvider


def make_config(provider: str) -> Config:
    return Config(
        waha_base_url="https://waha.example.com",
        waha_api_key="k",
        mcp_url="https://waha.example.com/mcp",
        mcp_api_key=None,
        llm_provider=provider,
        llm_model="claude-sonnet-5",
        llm_api_key="llm-key",
        default_inactivity_minutes=10,
        max_thread_lifetime_minutes=240,
        db_path="data/monitor.db",
        tickets_dir="tickets",
    )


def test_get_provider_returns_anthropic_provider():
    provider = get_provider(make_config("anthropic"))
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_rejects_unimplemented_provider():
    with pytest.raises(ValueError, match="openai"):
        get_provider(make_config("openai"))


@patch("monitor.llm.anthropic_provider.Anthropic")
def test_anthropic_provider_generate_returns_text(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="respuesta generada")]
    mock_client.messages.create.return_value = mock_response

    provider = AnthropicProvider(model="claude-sonnet-5", api_key="llm-key")
    result = provider.generate("hola")

    assert result == "respuesta generada"
    mock_client.messages.create.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.llm'`

- [ ] **Step 3: Implement `src/monitor/llm/__init__.py`**

```python
```

- [ ] **Step 4: Implement `src/monitor/llm/base.py`**

```python
from typing import Protocol


class LLMProvider(Protocol):
    def generate(self, prompt: str) -> str: ...
```

- [ ] **Step 5: Implement `src/monitor/llm/anthropic_provider.py`**

```python
from anthropic import Anthropic


class AnthropicProvider:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self._client = Anthropic(api_key=api_key)

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
```

- [ ] **Step 6: Implement `src/monitor/llm/factory.py`**

```python
from monitor.config import Config
from monitor.llm.anthropic_provider import AnthropicProvider
from monitor.llm.base import LLMProvider

_PROVIDERS = {"anthropic": AnthropicProvider}


def get_provider(config: Config) -> LLMProvider:
    provider_cls = _PROVIDERS.get(config.llm_provider)
    if provider_cls is None:
        raise ValueError(
            f"LLM provider '{config.llm_provider}' is not implemented yet "
            f"(available: {sorted(_PROVIDERS)})"
        )
    return provider_cls(model=config.llm_model, api_key=config.llm_api_key)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_llm_factory.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add src/monitor/llm tests/test_llm_factory.py
git commit -m "feat: add pluggable LLM provider interface with Anthropic implementation"
```

---

### Task 7: Evaluator (quick check & deep evaluation)

**Files:**
- Create: `src/monitor/evaluator.py`
- Test: `tests/test_evaluator.py`

**Interfaces:**
- Consumes: `LLMProvider.generate(prompt: str) -> str` (Task 6), `ThreadRecord`/`Message` (Task 5).
- Produces: `@dataclass TicketDecision(ticket_worthy: bool, summary: str, problem_description: str)`, `quick_check(llm: LLMProvider, thread: ThreadRecord) -> bool`, `deep_evaluate(llm: LLMProvider, mcp_context: str, thread: ThreadRecord) -> TicketDecision`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evaluator.py
from monitor.evaluator import TicketDecision, deep_evaluate, quick_check
from monitor.threads import Message, ThreadRecord


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


def make_thread() -> ThreadRecord:
    return ThreadRecord(
        group_id="g1",
        sender_id="s1",
        sender_name="Juan",
        messages=[Message("m1", "Mi factura llego mal, adjunto foto", None, "2026-07-21T10:00:00")],
        last_activity_at="2026-07-21T10:00:00",
        deadline_at="2026-07-21T10:10:00",
    )


def test_quick_check_returns_true_on_si():
    llm = FakeLLM("SI")
    assert quick_check(llm, make_thread()) is True
    assert "Juan" in llm.last_prompt


def test_quick_check_returns_false_on_no():
    llm = FakeLLM("NO")
    assert quick_check(llm, make_thread()) is False


def test_deep_evaluate_parses_ticket_worthy_response():
    llm = FakeLLM(
        "TICKET: SI\n"
        "RESUMEN: Cliente reporta factura incorrecta con foto adjunta.\n"
        "PROBLEMA: La factura de julio llego con el monto equivocado."
    )

    decision = deep_evaluate(llm, mcp_context="Sin contexto adicional.", thread=make_thread())

    assert isinstance(decision, TicketDecision)
    assert decision.ticket_worthy is True
    assert decision.summary == "Cliente reporta factura incorrecta con foto adjunta."
    assert decision.problem_description == "La factura de julio llego con el monto equivocado."


def test_deep_evaluate_parses_not_ticket_worthy_response():
    llm = FakeLLM("TICKET: NO\nRESUMEN: \nPROBLEMA: ")

    decision = deep_evaluate(llm, mcp_context="", thread=make_thread())

    assert decision.ticket_worthy is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_evaluator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.evaluator'`

- [ ] **Step 3: Implement `src/monitor/evaluator.py`**

```python
from dataclasses import dataclass

from monitor.threads import ThreadRecord


@dataclass
class TicketDecision:
    ticket_worthy: bool
    summary: str
    problem_description: str


def _format_messages(thread: ThreadRecord) -> str:
    return "\n".join(f"- {m.text}" for m in thread.messages)


def quick_check(llm, thread: ThreadRecord) -> bool:
    prompt = (
        f"Eres un asistente que monitorea un grupo de soporte de WhatsApp.\n"
        f"Remitente: {thread.sender_name}\n"
        f"Mensajes hasta ahora:\n{_format_messages(thread)}\n\n"
        f"¿Esta persona ya terminó de describir su problema? "
        f"Responde únicamente con SI o NO."
    )
    response = llm.generate(prompt).strip().upper()
    return response.startswith("SI")


def deep_evaluate(llm, mcp_context: str, thread: ThreadRecord) -> TicketDecision:
    prompt = (
        f"Eres un asistente que revisa conversaciones de soporte de WhatsApp para "
        f"decidir si se debe generar un ticket.\n"
        f"Remitente: {thread.sender_name}\n"
        f"Mensajes del remitente:\n{_format_messages(thread)}\n\n"
        f"Contexto adicional del grupo:\n{mcp_context}\n\n"
        f"Responde exactamente en este formato:\n"
        f"TICKET: SI o NO\n"
        f"RESUMEN: <resumen breve en español>\n"
        f"PROBLEMA: <descripcion detallada del problema en español>"
    )
    response = llm.generate(prompt)

    fields = {"TICKET": "", "RESUMEN": "", "PROBLEMA": ""}
    for line in response.splitlines():
        for key in fields:
            prefix = f"{key}:"
            if line.strip().upper().startswith(prefix):
                fields[key] = line.split(":", 1)[1].strip()

    return TicketDecision(
        ticket_worthy=fields["TICKET"].strip().upper().startswith("SI"),
        summary=fields["RESUMEN"],
        problem_description=fields["PROBLEMA"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_evaluator.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/evaluator.py tests/test_evaluator.py
git commit -m "feat: add quick-check and deep-evaluation LLM logic"
```

---

### Task 8: MCP client wrapper

**Files:**
- Create: `src/monitor/mcp_client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone HTTP JSON-RPC client).
- Produces: `class MCPClient(base_url: str, api_key: str | None)` with `call_tool(self, name: str, arguments: dict) -> str`; `fetch_context(mcp_url: str, api_key: str | None, group_id: str, sender_id: str) -> str`.

**Note:** `fetch_context` calls the tool name `get_chat_messages` as a starting assumption for WAHA's MCP tool catalog. Verify the exact tool name against the running WAHA MCP server (e.g. via its `tools/list` method) during the manual prod-connected testing step in Task 13, and adjust the constant in this file if it differs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_client.py
import httpx
import respx

from monitor.mcp_client import MCPClient, fetch_context


@respx.mock
def test_call_tool_sends_jsonrpc_request_and_extracts_text():
    route = respx.post("https://waha.example.com/mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "mensajes recientes del grupo"}]},
            },
        )
    )
    client = MCPClient("https://waha.example.com/mcp", api_key="mcp-key")

    result = client.call_tool("get_chat_messages", {"chatId": "g1", "limit": 50})

    assert result == "mensajes recientes del grupo"
    request_body = route.calls.last.request.content
    assert b"get_chat_messages" in request_body
    assert route.calls.last.request.headers["Authorization"] == "Bearer mcp-key"


@respx.mock
def test_call_tool_raises_on_jsonrpc_error():
    respx.post("https://waha.example.com/mcp").mock(
        return_value=httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "boom"}},
        )
    )
    client = MCPClient("https://waha.example.com/mcp", api_key=None)

    try:
        client.call_tool("get_chat_messages", {})
        assert False, "expected MCPError"
    except Exception as exc:
        assert "boom" in str(exc)


@respx.mock
def test_fetch_context_calls_get_chat_messages(tmp_path):
    respx.post("https://waha.example.com/mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "contexto del grupo"}]},
            },
        )
    )

    context = fetch_context("https://waha.example.com/mcp", "mcp-key", "g1", "s1")

    assert context == "contexto del grupo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.mcp_client'`

- [ ] **Step 3: Implement `src/monitor/mcp_client.py`**

```python
import httpx


class MCPError(Exception):
    pass


class MCPClient:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self._request_id = 0

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def call_tool(self, name: str, arguments: dict) -> str:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = httpx.post(self.base_url, json=payload, headers=self._headers(), timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise MCPError(data["error"].get("message", "MCP error"))

        content = data["result"].get("content", [])
        return "\n".join(part.get("text", "") for part in content if part.get("type") == "text")


def fetch_context(mcp_url: str, api_key: str | None, group_id: str, sender_id: str) -> str:
    client = MCPClient(mcp_url, api_key)
    return client.call_tool("get_chat_messages", {"chatId": group_id, "limit": 50, "senderId": sender_id})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_client.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: add MCP client wrapper for WAHA context lookups"
```

---

### Task 9: Ticket writer

**Files:**
- Create: `src/monitor/tickets.py`
- Test: `tests/test_tickets.py`

**Interfaces:**
- Consumes: `ThreadRecord`/`Message` (Task 5), `TicketDecision` (Task 7), `WahaClient.download_media(media_url: str) -> bytes` (Task 3).
- Produces: `write_ticket(tickets_dir: str, group_name: str, thread: ThreadRecord, decision: TicketDecision, waha_client, now: datetime) -> str` — returns the created folder path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tickets.py
from datetime import datetime, timezone

from monitor.threads import Message, ThreadRecord
from monitor.evaluator import TicketDecision
from monitor.tickets import write_ticket


class FakeWahaClient:
    def download_media(self, media_url: str) -> bytes:
        return b"fake-bytes-for-" + media_url.encode()


def make_thread_with_media() -> ThreadRecord:
    return ThreadRecord(
        group_id="1@g.us",
        sender_id="521555@c.us",
        sender_name="Juan Perez",
        messages=[
            Message("m1", "Mi factura llego mal", None, "2026-07-21T10:00:00+00:00"),
            Message(
                "m2",
                "Aqui la foto",
                {"url": "https://waha.example.com/files/foto.jpg", "mimetype": "image/jpeg"},
                "2026-07-21T10:01:00+00:00",
            ),
        ],
        last_activity_at="2026-07-21T10:01:00+00:00",
        deadline_at="2026-07-21T10:11:00+00:00",
    )


def test_write_ticket_creates_markdown_and_media(tmp_path):
    thread = make_thread_with_media()
    decision = TicketDecision(
        ticket_worthy=True,
        summary="Cliente reporta factura incorrecta con foto adjunta.",
        problem_description="La factura de julio llego con el monto equivocado.",
    )
    now = datetime(2026, 7, 21, 10, 5, tzinfo=timezone.utc)

    folder = write_ticket(str(tmp_path), "Soporte Acme", thread, decision, FakeWahaClient(), now)

    ticket_file = tmp_path / folder / "ticket.md" if not folder.startswith(str(tmp_path)) else None
    import os
    ticket_path = os.path.join(folder, "ticket.md")
    assert os.path.isfile(ticket_path)

    content = open(ticket_path, encoding="utf-8").read()
    assert "Soporte Acme" in content
    assert "Juan Perez" in content
    assert "La factura de julio llego con el monto equivocado." in content

    media_files = [f for f in os.listdir(folder) if f != "ticket.md"]
    assert len(media_files) == 1
    with open(os.path.join(folder, media_files[0]), "rb") as f:
        assert f.read() == b"fake-bytes-for-https://waha.example.com/files/foto.jpg"


def test_write_ticket_folder_name_includes_date_group_and_sender(tmp_path):
    thread = make_thread_with_media()
    decision = TicketDecision(True, "resumen", "problema")
    now = datetime(2026, 7, 21, 10, 5, tzinfo=timezone.utc)

    folder = write_ticket(str(tmp_path), "Soporte Acme", thread, decision, FakeWahaClient(), now)

    folder_name = folder.rstrip("/").split("/")[-1]
    assert folder_name.startswith("2026-07-21")
    assert "soporte-acme" in folder_name.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tickets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.tickets'`

- [ ] **Step 3: Implement `src/monitor/tickets.py`**

```python
import os
import re
from datetime import datetime

from monitor.evaluator import TicketDecision
from monitor.threads import ThreadRecord


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def write_ticket(
    tickets_dir: str,
    group_name: str,
    thread: ThreadRecord,
    decision: TicketDecision,
    waha_client,
    now: datetime,
) -> str:
    date_str = now.strftime("%Y-%m-%d")
    folder_name = f"{date_str}_{_slugify(group_name)}_{_slugify(thread.sender_name)}_{thread.sender_id}"
    folder_name = _slugify(folder_name)
    folder_path = os.path.join(tickets_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    lines = [
        f"# Ticket de soporte — {group_name}",
        "",
        f"**Remitente:** {thread.sender_name} ({thread.sender_id})",
        f"**Grupo:** {group_name} ({thread.group_id})",
        f"**Generado:** {now.isoformat()}",
        "",
        "## Resumen",
        decision.summary,
        "",
        "## Descripcion del problema",
        decision.problem_description,
        "",
        "## Mensajes originales",
    ]
    for message in thread.messages:
        lines.append(f"- [{message.timestamp}] {message.text}")

    media_messages = [m for m in thread.messages if m.media]
    if media_messages:
        lines.append("")
        lines.append("## Adjuntos")

    with open(os.path.join(folder_path, "ticket.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    for index, message in enumerate(media_messages, start=1):
        media_url = message.media["url"]
        data = waha_client.download_media(media_url)
        extension = os.path.splitext(media_url)[1] or ".bin"
        media_filename = f"adjunto_{index}{extension}"
        with open(os.path.join(folder_path, media_filename), "wb") as f:
            f.write(data)

    return folder_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tickets.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/tickets.py tests/test_tickets.py
git commit -m "feat: add ticket writer with markdown output and media download"
```

---

### Task 10: Scheduler (process due threads)

**Files:**
- Create: `src/monitor/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `get_due_threads`, `mark_ticketed`, `mark_needs_review`, `reset_deadline` (Task 5); `deep_evaluate` (Task 7); `fetch_context` (Task 8); `write_ticket` (Task 9); `is_excluded`, `list_groups` (Task 4, used to resolve group name).
- Produces: `process_due_threads(conn, config, waha_client, llm, group_name_lookup: dict[str, str], now: datetime) -> int` — returns number of threads processed; runs deep evaluation on every due thread and either writes a ticket, resets the deadline (not ticket-worthy, keep waiting), or marks `needs_review` on repeated LLM failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler.py
from datetime import datetime, timezone

from monitor.db import get_connection, init_db
from monitor.evaluator import TicketDecision
from monitor.scheduler import process_due_threads
from monitor.threads import Message, upsert_message


class FakeLLM:
    def generate(self, prompt: str) -> str:
        raise AssertionError("evaluator functions are patched directly in these tests")


class FakeWahaClient:
    def download_media(self, media_url: str) -> bytes:
        return b"data"


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_process_due_threads_writes_ticket_when_worthy(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema", None, now.isoformat()), now, inactivity_minutes=10)

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

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    assert processed == 1
    assert written_folders == ["Soporte Acme"]

    from monitor.threads import get_due_threads
    assert get_due_threads(conn, later) == []


def test_process_due_threads_resets_deadline_when_not_worthy(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(False, "", ""),
    )

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    assert processed == 1
    from monitor.threads import get_due_threads
    assert get_due_threads(conn, later) == []  # deadline was pushed out
    assert get_due_threads(conn, later + __import__("datetime").timedelta(minutes=11)) != []


def test_process_due_threads_marks_needs_review_on_evaluation_error(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")

    def boom(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("monitor.scheduler.deep_evaluate", boom)

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    assert processed == 1
    row = conn.execute(
        "SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.scheduler'`

- [ ] **Step 3: Implement `src/monitor/scheduler.py`**

```python
from datetime import datetime

from monitor.evaluator import deep_evaluate
from monitor.mcp_client import fetch_context
from monitor.threads import get_due_threads, mark_needs_review, mark_ticketed, reset_deadline
from monitor.tickets import write_ticket


def process_due_threads(conn, config, waha_client, llm, group_name_lookup: dict, now: datetime) -> int:
    due_threads = get_due_threads(conn, now)

    for thread in due_threads:
        try:
            mcp_context = fetch_context(config.mcp_url, config.mcp_api_key, thread.group_id, thread.sender_id)
            decision = deep_evaluate(llm, mcp_context, thread)
        except Exception:
            mark_needs_review(conn, thread.group_id, thread.sender_id)
            continue

        if decision.ticket_worthy:
            group_name = group_name_lookup.get(thread.group_id, thread.group_id)
            write_ticket(config.tickets_dir, group_name, thread, decision, waha_client, now)
            mark_ticketed(conn, thread.group_id, thread.sender_id)
        else:
            reset_deadline(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)

    return len(due_threads)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/scheduler.py tests/test_scheduler.py
git commit -m "feat: add scheduler to process due threads into tickets"
```

---

### Task 11: Webhook receiver (FastAPI)

**Files:**
- Create: `src/monitor/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: `upsert_message`, `Message` (Task 5); `quick_check` (Task 7); `is_excluded` (Task 4); `reset_deadline` (Task 5, used to shrink the deadline to "now" when the quick check says done, so the next scheduler tick picks it up immediately).
- Produces: `create_app(conn, config, llm) -> FastAPI` exposing `POST /webhook/waha` and `GET /health`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_webhook.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.groups import exclude_group, sync_groups
from monitor.webhook import create_app


class FakeLLM:
    def __init__(self, response="NO"):
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


class FakeWahaClient:
    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


class Config:
    default_inactivity_minutes = 10


def make_app(tmp_path, llm_response="NO"):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    sync_groups(conn, FakeWahaClient())
    app = create_app(conn, Config(), FakeLLM(llm_response))
    return app, conn


def waha_payload(message_id="m1", text="Hola, tengo un problema"):
    return {
        "event": "message",
        "payload": {
            "id": message_id,
            "from": "1@g.us",
            "participant": "521555@c.us",
            "participantName": "Juan Perez",
            "body": text,
            "timestamp": 1753099200,
        },
    }


def test_health_check(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_webhook_stores_message_for_known_group(tmp_path):
    app, conn = make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/webhook/waha", json=waha_payload())

    assert response.status_code == 200
    row = conn.execute(
        "SELECT sender_name FROM threads WHERE group_id = ? AND sender_id = ?",
        ("1@g.us", "521555@c.us"),
    ).fetchone()
    assert row[0] == "Juan Perez"


def test_webhook_ignores_excluded_group(tmp_path):
    app, conn = make_app(tmp_path)
    exclude_group(conn, "1@g.us")
    client = TestClient(app)

    response = client.post("/webhook/waha", json=waha_payload())

    assert response.status_code == 200
    row = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE group_id = ?", ("1@g.us",)
    ).fetchone()
    assert row[0] == 0


def test_webhook_deduplicates_repeated_message_id(tmp_path):
    app, conn = make_app(tmp_path)
    client = TestClient(app)

    client.post("/webhook/waha", json=waha_payload(message_id="m1"))
    client.post("/webhook/waha", json=waha_payload(message_id="m1"))

    row = conn.execute(
        "SELECT messages_json FROM threads WHERE group_id = ? AND sender_id = ?",
        ("1@g.us", "521555@c.us"),
    ).fetchone()
    import json
    assert len(json.loads(row[0])) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.webhook'`

- [ ] **Step 3: Implement `src/monitor/webhook.py`**

```python
from datetime import datetime, timezone

from fastapi import FastAPI

from monitor.evaluator import quick_check
from monitor.groups import is_excluded
from monitor.threads import Message, ThreadRecord, reset_deadline, upsert_message


def create_app(conn, config, llm) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhook/waha")
    def receive_webhook(event: dict):
        payload = event.get("payload", {})
        group_id = payload.get("from")
        sender_id = payload.get("participant")
        sender_name = payload.get("participantName") or sender_id

        if not group_id or not sender_id:
            return {"status": "ignored", "reason": "missing group or sender"}

        if is_excluded(conn, group_id):
            return {"status": "ignored", "reason": "group excluded"}

        message = Message(
            message_id=payload["id"],
            text=payload.get("body", ""),
            media=payload.get("media"),
            timestamp=datetime.fromtimestamp(payload.get("timestamp", 0), tz=timezone.utc).isoformat(),
        )

        now = datetime.now(timezone.utc)
        applied = upsert_message(conn, group_id, sender_id, sender_name, message, now, config.default_inactivity_minutes)
        if not applied:
            return {"status": "duplicate"}

        row = conn.execute(
            "SELECT messages_json FROM threads WHERE group_id = ? AND sender_id = ?",
            (group_id, sender_id),
        ).fetchone()
        import json

        messages = [Message(**m) for m in json.loads(row[0])]
        thread = ThreadRecord(group_id, sender_id, sender_name, messages, now.isoformat(), now.isoformat())

        if quick_check(llm, thread):
            reset_deadline(conn, group_id, sender_id, now, inactivity_minutes=0)

        return {"status": "accepted"}

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/webhook.py tests/test_webhook.py
git commit -m "feat: add FastAPI webhook receiver for WAHA message events"
```

---

### Task 12: CLI commands

**Files:**
- Create: `src/monitor/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `list_groups`, `exclude_group`, `include_group` (Task 4); `get_connection`, `init_db` (Task 2).
- Produces: `main(argv: list[str] | None = None) -> int`, invocable as `python -m monitor.cli groups list|exclude <id>|include <id>` and `needs-review list`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from monitor.cli import main
from monitor.db import get_connection, init_db
from monitor.groups import sync_groups


class FakeWahaClient:
    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


def test_groups_list_prints_groups(tmp_path, capsys, monkeypatch):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["groups", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Soporte Acme" in captured.out
    assert "1@g.us" in captured.out


def test_groups_exclude_marks_group_excluded(tmp_path, monkeypatch):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["groups", "exclude", "1@g.us"])
    assert exit_code == 0

    conn = get_connection(db_path)
    row = conn.execute("SELECT excluded FROM groups WHERE group_id = ?", ("1@g.us",)).fetchone()
    assert row[0] == 1


def test_needs_review_list_prints_flagged_threads(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from monitor.threads import Message, mark_needs_review, upsert_message

    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "1@g.us", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, 10)
    mark_needs_review(conn, "1@g.us", "s1")
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["needs-review", "list"])
    assert exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.cli'`

- [ ] **Step 3: Implement `src/monitor/cli.py`**

```python
import argparse
import os

from monitor.db import get_connection, init_db
from monitor.groups import exclude_group, include_group, list_groups


def _connect():
    db_path = os.environ.get("MONITOR_DB_PATH", "data/monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    groups_parser = subparsers.add_parser("groups")
    groups_sub = groups_parser.add_subparsers(dest="groups_command", required=True)
    groups_sub.add_parser("list")
    exclude_parser = groups_sub.add_parser("exclude")
    exclude_parser.add_argument("group_id")
    include_parser = groups_sub.add_parser("include")
    include_parser.add_argument("group_id")

    review_parser = subparsers.add_parser("needs-review")
    review_sub = review_parser.add_subparsers(dest="review_command", required=True)
    review_sub.add_parser("list")

    args = parser.parse_args(argv)
    conn = _connect()

    if args.command == "groups":
        if args.groups_command == "list":
            for group in list_groups(conn):
                status = "excluded" if group["excluded"] else "active"
                print(f"{group['group_id']}\t{group['name']}\t{status}")
        elif args.groups_command == "exclude":
            exclude_group(conn, args.group_id)
            print(f"Excluded {args.group_id}")
        elif args.groups_command == "include":
            include_group(conn, args.group_id)
            print(f"Included {args.group_id}")
        return 0

    if args.command == "needs-review":
        if args.review_command == "list":
            rows = conn.execute(
                "SELECT group_id, sender_id, sender_name FROM threads WHERE needs_review = 1"
            ).fetchall()
            for group_id, sender_id, sender_name in rows:
                print(f"{group_id}\t{sender_id}\t{sender_name}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/cli.py tests/test_cli.py
git commit -m "feat: add CLI for managing groups and needs-review threads"
```

---

### Task 13: Wiring, Docker packaging & manual prod verification notes

**Files:**
- Create: `src/monitor/main.py`
- Create: `Dockerfile`
- Create: `README.md`
- Test: `tests/test_main_smoke.py`

**Interfaces:**
- Consumes: everything from Tasks 1–12.
- Produces: `create_full_app(config_path: str) -> FastAPI` (wires config, db, waha client, llm, and starts the background scheduler thread on FastAPI startup); module-level `app` for `uvicorn monitor.main:app`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main_smoke.py
import textwrap

from fastapi.testclient import TestClient

from monitor.main import create_full_app


def test_create_full_app_health_check(tmp_path, monkeypatch):
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
            """
        )
    )

    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.main'`

- [ ] **Step 3: Implement `src/monitor/main.py`**

```python
import threading
import time
from datetime import datetime, timezone

from monitor.config import load_config
from monitor.db import get_connection, init_db
from monitor.groups import list_groups, sync_groups
from monitor.llm.factory import get_provider
from monitor.scheduler import process_due_threads
from monitor.waha_client import WahaClient
from monitor.webhook import create_app

SCHEDULER_INTERVAL_SECONDS = 30


def _run_scheduler_loop(conn, config, waha_client, llm, stop_event: threading.Event):
    while not stop_event.is_set():
        group_name_lookup = {g["group_id"]: g["name"] for g in list_groups(conn)}
        process_due_threads(conn, config, waha_client, llm, group_name_lookup, datetime.now(timezone.utc))
        sync_groups(conn, waha_client)
        stop_event.wait(SCHEDULER_INTERVAL_SECONDS)


def create_full_app(config_path: str, start_background_scheduler: bool = True):
    config = load_config(config_path)
    conn = get_connection(config.db_path)
    init_db(conn)

    waha_client = WahaClient(config.waha_base_url, config.waha_api_key)
    llm = get_provider(config)

    sync_groups(conn, waha_client)

    app = create_app(conn, config, llm)

    if start_background_scheduler:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_run_scheduler_loop,
            args=(conn, config, waha_client, llm, stop_event),
            daemon=True,
        )
        thread.start()
        app.state.scheduler_stop_event = stop_event

    return app


app = create_full_app("config.yaml") if __name__ != "__main__" and __name__ == "monitor.main" else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_smoke.py -v`
Expected: PASS (1 passed)

Note: the module-level `app = ...` line only triggers real config loading when imported as `monitor.main` by `uvicorn` — the smoke test imports `create_full_app` directly and never touches it, so it stays test-safe.

- [ ] **Step 5: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY config.example.yaml ./

ENV MONITOR_DB_PATH=/app/data/monitor.db

EXPOSE 8000

CMD ["uvicorn", "monitor.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 6: Write `README.md`**

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
git add src/monitor/main.py Dockerfile README.md tests/test_main_smoke.py
git commit -m "feat: wire full app, add Docker packaging and manual verification notes"
```

---

## Self-Review Notes

- **Spec coverage:** webhook receiver ✅ (Task 11), auto-discovery + opt-out ✅ (Task 4), per-sender segmentation ✅ (Task 5), quick check + inactivity fallback ✅ (Tasks 5, 7, 11), MCP context lookup ✅ (Task 8), pluggable LLM ✅ (Task 6), Spanish ticket + media output ✅ (Task 9), SQLite persistence for crash-safety ✅ (Task 2 + all state in Tasks 4/5), `needs_review` error path ✅ (Tasks 5, 10, 12), Docker packaging ✅ (Task 13), manual prod-connected verification ✅ (Task 13 README).
- **Type consistency checked:** `Message`/`ThreadRecord` (Task 5) reused identically in Tasks 7, 9, 10, 11. `TicketDecision` (Task 7) reused identically in Tasks 9, 10. `LLMProvider.generate(prompt: str) -> str` (Task 6) is the only shape used by `quick_check`/`deep_evaluate` (Task 7) and both fakes in later tests.
- **No placeholders remaining** — every step has runnable code; the one open item (exact MCP tool name) is called out explicitly as a manual verification step in Task 13, not left as a silent TODO.
