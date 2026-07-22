# Dan's Beacon — Frontend Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the auth/tickets API additions on the existing FastAPI backend, plus a React dashboard (login, ticket list, ticket detail with a status/resolution panel, admin user management), shipped as one Docker image.

**Architecture:** The existing FastAPI backend (`src/monitor/main.py`) gains three new routers (`auth`, `admin`, `tickets`) backed by two new SQLite tables (`users`, `ticket_status` + `ticket_status_history`) and a filesystem parser that reads the `tickets/` folder the backend already writes. A separate `frontend/` React + Vite app talks to these `/api/*` routes and is built into static files that the same FastAPI process serves at `/`. A multi-stage Dockerfile produces one image containing both.

**Tech Stack:** Python 3.11+ / FastAPI (existing), PyJWT (new dependency) for auth tokens, stdlib `hashlib` for password hashing, React + Vite + react-router-dom, Vitest + React Testing Library.

## Global Constraints

- Auth uses a JWT in an httpOnly cookie named `beacon_token` (not server-side sessions) — `SameSite=Lax`, expiry driven by config's `jwt_expiry_minutes` (default 1440 = 24h).
- Password hashing uses stdlib `hashlib.pbkdf2_hmac` with a random per-user salt — no new hashing dependency.
- `ticket_status` defaults to `"pendiente"` with empty `causa_raiz`/`solucion` for any ticket with no row yet — rows are created lazily on first status change, never backfilled.
- Moving a ticket's status to `"resuelto"` requires both `causa_raiz` and `solucion` to be non-empty; other transitions have no such requirement.
- A `ticket_status_history` row is inserted only when `status` actually changes, not on every field edit.
- All ticket/media endpoints require any authenticated user; only `/api/admin/users` requires `role == "admin"`.
- Ticket IDs are ticket folder names (opaque strings) — any endpoint taking a `ticket_id` or media `filename` must reject path-traversal attempts (`/` or `..`) rather than trusting the input directly against the filesystem.
- Existing dict-based request bodies (not Pydantic models) match the codebase's established webhook.py style — keep using plain `dict` params for consistency, no new modeling library.
- Frontend visual identity (already validated): Diner Americana palette (`#e8a33d` mustard / `#2b2420` charcoal / `#f4e3c1` cream / `#c97b2e` brown), Bebas Neue for the wordmark/headers, sidebar + table for the ticket list, single-column top-to-bottom for ticket detail.

---

## File Structure

```
WahaMonitor/
  pyproject.toml                       # Modify: add pyjwt dependency
  config.example.yaml                   # Modify: add auth: section
  Dockerfile                             # Modify: multi-stage, build frontend
  README.md                               # Modify: setup + bootstrap admin
  src/monitor/
    config.py                             # Modify: jwt_secret, jwt_expiry_minutes
    db.py                                  # Modify: users, ticket_status, ticket_status_history tables
    cli.py                                  # Modify: `users create` bootstrap command
    auth.py                                  # Task 2 (new)
    users.py                                  # Task 3 (new)
    ticket_status.py                          # Task 4 (new)
    tickets_reader.py                          # Task 5 (new)
    api/
      __init__.py                               # Task 6 (new)
      dependencies.py                            # Task 6 (new)
      auth_routes.py                             # Task 6 (new)
      admin_routes.py                             # Task 7 (new)
      tickets_routes.py                            # Task 8 (new)
    main.py                                        # Task 9 (modify: wire routers + static files)
  tests/
    test_config.py                                 # Modify (Task 1)
    test_db.py                                      # Modify (Task 1)
    test_cli.py                                      # Modify (Task 3)
    test_auth.py                                      # Task 2 (new)
    test_users.py                                      # Task 3 (new)
    test_ticket_status.py                               # Task 4 (new)
    test_tickets_reader.py                               # Task 5 (new)
    test_api_auth.py                                      # Task 6 (new)
    test_api_admin.py                                      # Task 7 (new)
    test_api_tickets.py                                     # Task 8 (new)
    test_main_smoke.py                                       # Modify (Task 9)
  frontend/
    package.json, vite.config.js, index.html               # Task 10 (new)
    src/main.jsx, App.jsx                                    # Task 10 (new)
    src/api/client.js                                         # Task 10 (new)
    src/auth/AuthContext.jsx, RequireAuth.jsx, RequireAdmin.jsx  # Task 10 (new)
    src/pages/LoginPage.jsx                                     # Task 11 (new)
    src/components/Sidebar.jsx                                  # Task 12 (new)
    src/pages/TicketListPage.jsx                                # Task 12 (new)
    src/pages/TicketDetailPage.jsx                              # Task 13 (new)
    src/components/ResolutionPanel.jsx, HistoryModal.jsx        # Task 14 (new)
    src/pages/AdminUsersPage.jsx                                # Task 15 (new)
    src/styles/theme.css, layout.css                            # Task 16 (new)
```

---

### Task 1: Config & schema extensions for auth and ticket status

**Files:**
- Modify: `src/monitor/config.py`
- Modify: `config.example.yaml`
- Modify: `src/monitor/db.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config` gains fields `jwt_secret: str`, `jwt_expiry_minutes: int`. `SCHEMA` gains tables `users(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL)`, `ticket_status(ticket_id TEXT PRIMARY KEY, status TEXT NOT NULL, causa_raiz TEXT NOT NULL DEFAULT '', solucion TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)`, `ticket_status_history(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, status TEXT NOT NULL, changed_by TEXT NOT NULL, changed_at TEXT NOT NULL)`.

- [ ] **Step 1: Write the failing test for config**

Add to `tests/test_config.py` (extend the existing fixture YAML and assertions — do not remove the existing test bodies, just add the new section/fields):

```python
def test_load_config_reads_auth_fields(tmp_path):
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
            auth:
              jwt_secret: "test-secret"
              jwt_expiry_minutes: 1440
            """
        )
    )

    config = load_config(str(config_path))

    assert config.jwt_secret == "test-secret"
    assert config.jwt_expiry_minutes == 1440
```

Also add `auth:\n  jwt_secret: "test-secret"\n  jwt_expiry_minutes: 1440` to the YAML fixture used by the existing `test_load_config_reads_all_fields` test (it will now fail with a `KeyError` otherwise, since the loader will require the section).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `test_load_config_reads_auth_fields` fails with `AttributeError` (no `jwt_secret` field yet); `test_load_config_reads_all_fields` fails with `KeyError: 'auth'` once its fixture YAML is updated but the loader isn't.

- [ ] **Step 3: Implement the config change**

In `src/monitor/config.py`, add to the `Config` dataclass (after `tickets_dir`):

```python
    jwt_secret: str
    jwt_expiry_minutes: int
```

And in `load_config`, add to the `Config(...)` construction:

```python
        jwt_secret=raw["auth"]["jwt_secret"],
        jwt_expiry_minutes=raw["auth"]["jwt_expiry_minutes"],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all tests, including the two updated/added ones)

- [ ] **Step 5: Write the failing test for the schema**

Add to `tests/test_db.py`:

```python
def test_init_db_creates_auth_and_status_tables(tmp_path):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}

    assert {"users", "ticket_status", "ticket_status_history"} <= tables


def test_users_table_enforces_unique_email(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("a@example.com", "hash1", "user", "2026-07-22T00:00:00"),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            ("a@example.com", "hash2", "user", "2026-07-22T00:00:00"),
        )
```

Add `import pytest` and `import sqlite3` to the top of `tests/test_db.py` if not already present.

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — the two new tests fail because `users`/`ticket_status`/`ticket_status_history` don't exist yet.

- [ ] **Step 7: Implement the schema change**

In `src/monitor/db.py`, extend `SCHEMA`:

```python
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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_status (
    ticket_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    causa_raiz TEXT NOT NULL DEFAULT '',
    solucion TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    status TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
"""
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_db.py tests/test_config.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Update `config.example.yaml`**

Add this section to `config.example.yaml` (anywhere after `storage:`):

```yaml
auth:
  jwt_secret: "REPLACE_ME_WITH_A_LONG_RANDOM_SECRET"
  jwt_expiry_minutes: 1440
```

- [ ] **Step 10: Add PyJWT to dependencies**

In `pyproject.toml`, add `"pyjwt>=2.8"` to the `dependencies` list (alongside `fastapi`, `httpx`, etc.).

Run: `pip install -e ".[dev]"` to install it.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml config.example.yaml src/monitor/config.py src/monitor/db.py tests/test_config.py tests/test_db.py
git commit -m "feat: add auth/ticket-status config fields and schema"
```

---

### Task 2: Password hashing & JWT helpers

**Files:**
- Create: `src/monitor/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone crypto helpers).
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, stored_hash: str) -> bool`, `class AuthError(Exception)`, `create_access_token(user_id: int, email: str, role: str, secret: str, expiry_minutes: int) -> str`, `decode_access_token(token: str, secret: str) -> dict` (dict has keys `user_id`, `email`, `role`; raises `AuthError` on invalid/expired token).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import time

import jwt
import pytest

from monitor.auth import (
    AuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_verifiable_hash():
    hashed = hash_password("correct-horse")

    assert verify_password("correct-horse", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_uses_distinct_salts():
    hash1 = hash_password("same-password")
    hash2 = hash_password("same-password")

    assert hash1 != hash2
    assert verify_password("same-password", hash1) is True
    assert verify_password("same-password", hash2) is True


def test_create_and_decode_access_token_roundtrip():
    token = create_access_token(42, "user@example.com", "admin", "secret123", 60)

    payload = decode_access_token(token, "secret123")

    assert payload["user_id"] == 42
    assert payload["email"] == "user@example.com"
    assert payload["role"] == "admin"


def test_decode_access_token_rejects_wrong_secret():
    token = create_access_token(1, "a@b.com", "user", "secret123", 60)

    with pytest.raises(AuthError):
        decode_access_token(token, "wrong-secret")


def test_decode_access_token_rejects_expired_token():
    token = jwt.encode(
        {"user_id": 1, "email": "a@b.com", "role": "user", "exp": time.time() - 10},
        "secret123",
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        decode_access_token(token, "secret123")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.auth'`

- [ ] **Step 3: Implement `src/monitor/auth.py`**

```python
import hashlib
import os
import time

import jwt


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    salt_hex, digest_hex = stored_hash.split("$", 1)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return actual == expected


def create_access_token(user_id: int, email: str, role: str, secret: str, expiry_minutes: int) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": time.time() + expiry_minutes * 60,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/auth.py tests/test_auth.py
git commit -m "feat: add password hashing and JWT helpers"
```

---

### Task 3: User management

**Files:**
- Create: `src/monitor/users.py`
- Modify: `src/monitor/cli.py`
- Test: `tests/test_users.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `get_connection`/`init_db` (Task 1's schema), `hash_password` (Task 2).
- Produces: `create_user(conn, email: str, password: str, role: str) -> int` (raises `ValueError` if email already registered or role not in `{"admin", "user"}`), `get_user_by_email(conn, email: str) -> dict | None` (dict has `id, email, password_hash, role, created_at`), `get_user_by_id(conn, user_id: int) -> dict | None` (same shape), `list_users(conn) -> list[dict]` (dicts have `id, email, role, created_at` — no `password_hash`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_users.py
import pytest

from monitor.db import get_connection, init_db
from monitor.users import create_user, get_user_by_email, get_user_by_id, list_users


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_create_user_and_fetch_by_email(tmp_path):
    conn = make_conn(tmp_path)

    user_id = create_user(conn, "agent@example.com", "s3cret", "user")

    user = get_user_by_email(conn, "agent@example.com")
    assert user["id"] == user_id
    assert user["email"] == "agent@example.com"
    assert user["role"] == "user"
    assert user["password_hash"] != "s3cret"


def test_create_user_rejects_duplicate_email(tmp_path):
    conn = make_conn(tmp_path)
    create_user(conn, "agent@example.com", "s3cret", "user")

    with pytest.raises(ValueError, match="already"):
        create_user(conn, "agent@example.com", "other", "admin")


def test_create_user_rejects_invalid_role(tmp_path):
    conn = make_conn(tmp_path)

    with pytest.raises(ValueError, match="role"):
        create_user(conn, "agent@example.com", "s3cret", "superuser")


def test_get_user_by_id_returns_none_for_unknown(tmp_path):
    conn = make_conn(tmp_path)
    assert get_user_by_id(conn, 999) is None


def test_list_users_excludes_password_hash(tmp_path):
    conn = make_conn(tmp_path)
    create_user(conn, "a@example.com", "pw1", "admin")
    create_user(conn, "b@example.com", "pw2", "user")

    users = list_users(conn)

    assert len(users) == 2
    emails = {u["email"] for u in users}
    assert emails == {"a@example.com", "b@example.com"}
    for u in users:
        assert "password_hash" not in u
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_users.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.users'`

- [ ] **Step 3: Implement `src/monitor/users.py`**

```python
from datetime import datetime, timezone

from monitor.auth import hash_password

VALID_ROLES = {"admin", "user"}


def create_user(conn, email: str, password: str, role: str) -> int:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}' (must be one of {sorted(VALID_ROLES)})")

    existing = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise ValueError(f"A user with email '{email}' already exists")

    password_hash = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
        (email, password_hash, role, now),
    )
    conn.commit()
    return cursor.lastrowid


def _row_to_full_dict(row) -> dict:
    return {
        "id": row[0],
        "email": row[1],
        "password_hash": row[2],
        "role": row[3],
        "created_at": row[4],
    }


def get_user_by_email(conn, email: str) -> dict | None:
    row = conn.execute(
        "SELECT id, email, password_hash, role, created_at FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    return _row_to_full_dict(row) if row else None


def get_user_by_id(conn, user_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, email, password_hash, role, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return _row_to_full_dict(row) if row else None


def list_users(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, email, role, created_at FROM users ORDER BY email"
    ).fetchall()
    return [
        {"id": r[0], "email": r[1], "role": r[2], "created_at": r[3]} for r in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_users.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Add a CLI bootstrap command for the first admin account**

This solves the chicken-and-egg problem: the admin-creation API endpoint (Task 7) requires an existing admin to call it, so the very first account must be created another way.

Add to `tests/test_cli.py`:

```python
def test_users_create_creates_account(tmp_path, monkeypatch):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["users", "create", "admin@example.com", "s3cret", "admin"])
    assert exit_code == 0

    conn = get_connection(db_path)
    from monitor.users import get_user_by_email
    user = get_user_by_email(conn, "admin@example.com")
    assert user is not None
    assert user["role"] == "admin"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `argparse.ArgumentError` / `SystemExit(2)` because the `users` subcommand doesn't exist yet.

- [ ] **Step 7: Implement the CLI addition**

In `src/monitor/cli.py`, add the import:

```python
from monitor.users import create_user
```

Add a new subparser (alongside the existing `groups`/`needs-review` subparsers):

```python
    users_parser = subparsers.add_parser("users")
    users_sub = users_parser.add_subparsers(dest="users_command", required=True)
    create_parser = users_sub.add_parser("create")
    create_parser.add_argument("email")
    create_parser.add_argument("password")
    create_parser.add_argument("role", choices=["admin", "user"])
```

And handle it in `main()` (alongside the existing `if args.command == "groups":` / `"needs-review":` blocks):

```python
    if args.command == "users":
        if args.users_command == "create":
            try:
                create_user(conn, args.email, args.password, args.role)
                print(f"Created user {args.email} ({args.role})")
            except ValueError as e:
                print(f"Error: {e}")
                return 1
        return 0
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (all cli tests)

- [ ] **Step 9: Run the full suite**

Run: `pytest -v`
Expected: all tests passing (baseline + new)

- [ ] **Step 10: Commit**

```bash
git add src/monitor/users.py src/monitor/cli.py tests/test_users.py tests/test_cli.py
git commit -m "feat: add user management and CLI bootstrap for first admin account"
```

---

### Task 4: Ticket status tracking

**Files:**
- Create: `src/monitor/ticket_status.py`
- Test: `tests/test_ticket_status.py`

**Interfaces:**
- Consumes: `get_connection`/`init_db` (Task 1's schema).
- Produces: `VALID_STATUSES = {"pendiente", "en_progreso", "resuelto"}`, `get_status(conn, ticket_id: str) -> dict` (keys `status, causa_raiz, solucion, updated_at`; defaults to `{"status": "pendiente", "causa_raiz": "", "solucion": "", "updated_at": None}` if no row exists), `get_history(conn, ticket_id: str) -> list[dict]` (each dict has `status, changed_by, changed_at`, ordered oldest-first), `set_status(conn, ticket_id: str, status: str, causa_raiz: str, solucion: str, changed_by: str, now: datetime) -> dict` (returns the same shape as `get_status`; raises `ValueError` if `status` isn't in `VALID_STATUSES`, or if `status == "resuelto"` and either `causa_raiz` or `solucion` is blank).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ticket_status.py
from datetime import datetime, timezone

import pytest

from monitor.db import get_connection, init_db
from monitor.ticket_status import get_history, get_status, set_status


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_get_status_defaults_to_pendiente_for_unknown_ticket(tmp_path):
    conn = make_conn(tmp_path)

    status = get_status(conn, "unknown-ticket")

    assert status == {"status": "pendiente", "causa_raiz": "", "solucion": "", "updated_at": None}


def test_set_status_updates_and_persists(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    result = set_status(conn, "t1", "en_progreso", "", "", "agent@example.com", now)

    assert result["status"] == "en_progreso"
    assert get_status(conn, "t1")["status"] == "en_progreso"


def test_set_status_resuelto_requires_causa_raiz_and_solucion(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="causa_raiz"):
        set_status(conn, "t1", "resuelto", "", "", "agent@example.com", now)

    with pytest.raises(ValueError, match="solucion"):
        set_status(conn, "t1", "resuelto", "algo paso", "", "agent@example.com", now)


def test_set_status_resuelto_succeeds_with_both_fields(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    result = set_status(conn, "t1", "resuelto", "Factura mal calculada", "Se corrigio el monto", "agent@example.com", now)

    assert result["status"] == "resuelto"
    assert result["causa_raiz"] == "Factura mal calculada"
    assert result["solucion"] == "Se corrigio el monto"


def test_set_status_rejects_invalid_status(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="status"):
        set_status(conn, "t1", "bogus", "", "", "agent@example.com", now)


def test_set_status_appends_history_only_on_status_change(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    set_status(conn, "t1", "pendiente", "", "", "agent@example.com", now)
    set_status(conn, "t1", "pendiente", "nota", "", "agent@example.com", now)  # same status, different fields
    set_status(conn, "t1", "en_progreso", "nota", "", "agent2@example.com", now)

    history = get_history(conn, "t1")

    assert [h["status"] for h in history] == ["pendiente", "en_progreso"]
    assert history[0]["changed_by"] == "agent@example.com"
    assert history[1]["changed_by"] == "agent2@example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ticket_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.ticket_status'`

- [ ] **Step 3: Implement `src/monitor/ticket_status.py`**

```python
from datetime import datetime

VALID_STATUSES = {"pendiente", "en_progreso", "resuelto"}


def get_status(conn, ticket_id: str) -> dict:
    row = conn.execute(
        "SELECT status, causa_raiz, solucion, updated_at FROM ticket_status WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    if row is None:
        return {"status": "pendiente", "causa_raiz": "", "solucion": "", "updated_at": None}
    return {"status": row[0], "causa_raiz": row[1], "solucion": row[2], "updated_at": row[3]}


def get_history(conn, ticket_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT status, changed_by, changed_at FROM ticket_status_history "
        "WHERE ticket_id = ? ORDER BY id ASC",
        (ticket_id,),
    ).fetchall()
    return [{"status": r[0], "changed_by": r[1], "changed_at": r[2]} for r in rows]


def set_status(
    conn,
    ticket_id: str,
    status: str,
    causa_raiz: str,
    solucion: str,
    changed_by: str,
    now: datetime,
) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}' (must be one of {sorted(VALID_STATUSES)})")
    if status == "resuelto":
        if not causa_raiz.strip():
            raise ValueError("causa_raiz is required to mark a ticket as resuelto")
        if not solucion.strip():
            raise ValueError("solucion is required to mark a ticket as resuelto")

    previous = get_status(conn, ticket_id)
    now_str = now.isoformat()

    conn.execute(
        """
        INSERT INTO ticket_status (ticket_id, status, causa_raiz, solucion, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
            status = excluded.status,
            causa_raiz = excluded.causa_raiz,
            solucion = excluded.solucion,
            updated_at = excluded.updated_at
        """,
        (ticket_id, status, causa_raiz, solucion, now_str),
    )

    if status != previous["status"]:
        conn.execute(
            "INSERT INTO ticket_status_history (ticket_id, status, changed_by, changed_at) VALUES (?, ?, ?, ?)",
            (ticket_id, status, changed_by, now_str),
        )

    conn.commit()
    return get_status(conn, ticket_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ticket_status.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/ticket_status.py tests/test_ticket_status.py
git commit -m "feat: add ticket status tracking with history"
```

---

### Task 5: Ticket file parser

**Files:**
- Create: `src/monitor/tickets_reader.py`
- Test: `tests/test_tickets_reader.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (reads the `ticket.md` format that `src/monitor/tickets.py`'s `write_ticket` already produces — see that file for the exact template).
- Produces: `parse_ticket(folder_path: str) -> dict` (raises `ValueError` if `ticket.md` is missing or missing required fields; returned dict has keys `ticket_id, group_name, group_id, sender_name, sender_id, generated_at, summary, problem_description, messages` (list of `{"timestamp": str, "text": str}`), `media_filenames` (list of str, sorted)), `list_tickets(tickets_dir: str, group: str | None = None, date_from: str | None = None, date_to: str | None = None, q: str | None = None) -> list[dict]` (same shape as `parse_ticket`, newest folder name first, skips unparseable folders), `get_ticket(tickets_dir: str, ticket_id: str) -> dict | None` (returns `None` for unknown/invalid/path-traversal `ticket_id`), `safe_media_path(tickets_dir: str, ticket_id: str, filename: str) -> str | None` (returns the resolved file path if it exists and both `ticket_id`/`filename` are safe, else `None`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tickets_reader.py
import os

from monitor.tickets_reader import get_ticket, list_tickets, parse_ticket, safe_media_path


TICKET_MD = """# Ticket de soporte — Soporte Acme

**Remitente:** Juan Perez (521555@c.us)
**Grupo:** Soporte Acme (1@g.us)
**Generado:** 2026-07-21T10:05:00+00:00

## Resumen
Cliente reporta factura incorrecta con foto adjunta.

## Descripcion del problema
La factura de julio llego con el monto equivocado.

## Mensajes originales
- [2026-07-21T10:00:00+00:00] Mi factura llego mal
- [2026-07-21T10:01:00+00:00] Aqui la foto

## Adjuntos
"""


def make_ticket_folder(tmp_path, name="2026-07-21-soporte-acme-juan-perez-521555-c-us-m2", with_media=True):
    tickets_dir = tmp_path / "tickets"
    folder = tickets_dir / name
    folder.mkdir(parents=True)
    (folder / "ticket.md").write_text(TICKET_MD, encoding="utf-8")
    if with_media:
        (folder / "adjunto_1.jpg").write_bytes(b"fake-image-bytes")
    return str(tickets_dir), name


def test_parse_ticket_extracts_all_fields(tmp_path):
    tickets_dir, name = make_ticket_folder(tmp_path)

    ticket = parse_ticket(os.path.join(tickets_dir, name))

    assert ticket["ticket_id"] == name
    assert ticket["group_name"] == "Soporte Acme"
    assert ticket["group_id"] == "1@g.us"
    assert ticket["sender_name"] == "Juan Perez"
    assert ticket["sender_id"] == "521555@c.us"
    assert ticket["generated_at"] == "2026-07-21T10:05:00+00:00"
    assert ticket["summary"] == "Cliente reporta factura incorrecta con foto adjunta."
    assert ticket["problem_description"] == "La factura de julio llego con el monto equivocado."
    assert ticket["messages"] == [
        {"timestamp": "2026-07-21T10:00:00+00:00", "text": "Mi factura llego mal"},
        {"timestamp": "2026-07-21T10:01:00+00:00", "text": "Aqui la foto"},
    ]
    assert ticket["media_filenames"] == ["adjunto_1.jpg"]


def test_parse_ticket_raises_on_missing_file(tmp_path):
    import pytest

    empty_dir = tmp_path / "empty-ticket"
    empty_dir.mkdir()

    with pytest.raises(ValueError):
        parse_ticket(str(empty_dir))


def test_list_tickets_skips_malformed_folder(tmp_path):
    tickets_dir, good_name = make_ticket_folder(tmp_path)
    bad_folder = os.path.join(tickets_dir, "malformed-ticket")
    os.makedirs(bad_folder)
    with open(os.path.join(bad_folder, "ticket.md"), "w") as f:
        f.write("not a real ticket file")

    tickets = list_tickets(tickets_dir)

    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == good_name


def test_list_tickets_filters_by_group_and_query(tmp_path):
    tickets_dir, _ = make_ticket_folder(tmp_path)

    assert len(list_tickets(tickets_dir, group="Soporte Acme")) == 1
    assert len(list_tickets(tickets_dir, group="Soporte Beta")) == 0
    assert len(list_tickets(tickets_dir, q="factura incorrecta")) == 1
    assert len(list_tickets(tickets_dir, q="nada que ver")) == 0


def test_get_ticket_returns_none_for_path_traversal(tmp_path):
    tickets_dir, name = make_ticket_folder(tmp_path)

    assert get_ticket(tickets_dir, "../../etc/passwd") is None
    assert get_ticket(tickets_dir, "unknown-ticket") is None
    assert get_ticket(tickets_dir, name) is not None


def test_safe_media_path_returns_none_for_traversal_and_missing_file(tmp_path):
    tickets_dir, name = make_ticket_folder(tmp_path)

    assert safe_media_path(tickets_dir, name, "../../etc/passwd") is None
    assert safe_media_path(tickets_dir, name, "does-not-exist.jpg") is None
    assert safe_media_path(tickets_dir, "../escape", "adjunto_1.jpg") is None

    path = safe_media_path(tickets_dir, name, "adjunto_1.jpg")
    assert path is not None
    assert os.path.isfile(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tickets_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.tickets_reader'`

- [ ] **Step 3: Implement `src/monitor/tickets_reader.py`**

```python
import logging
import os
import re

logger = logging.getLogger(__name__)


def _is_safe_path_component(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


def parse_ticket(folder_path: str) -> dict:
    ticket_md_path = os.path.join(folder_path, "ticket.md")
    if not os.path.isfile(ticket_md_path):
        raise ValueError(f"No ticket.md found in {folder_path}")

    with open(ticket_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    group_name = None
    group_id = None
    sender_name = None
    sender_id = None
    generated_at = None
    summary_lines = []
    problem_lines = []
    messages = []
    section = None

    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "## Resumen":
            section = "resumen"
            continue
        if stripped == "## Descripcion del problema":
            section = "problema"
            continue
        if stripped == "## Mensajes originales":
            section = "mensajes"
            continue
        if stripped == "## Adjuntos":
            section = "adjuntos"
            continue

        remitente_match = re.match(r"\*\*Remitente:\*\* (.+) \((.+)\)$", stripped)
        if remitente_match:
            sender_name, sender_id = remitente_match.group(1), remitente_match.group(2)
            continue

        grupo_match = re.match(r"\*\*Grupo:\*\* (.+) \((.+)\)$", stripped)
        if grupo_match:
            group_name, group_id = grupo_match.group(1), grupo_match.group(2)
            continue

        if stripped.startswith("**Generado:**"):
            generated_at = stripped.split("**Generado:**", 1)[1].strip()
            continue

        if section == "resumen" and stripped:
            summary_lines.append(stripped)
        elif section == "problema" and stripped:
            problem_lines.append(stripped)
        elif section == "mensajes":
            message_match = re.match(r"^- \[(.+?)\] (.*)$", stripped)
            if message_match:
                messages.append({"timestamp": message_match.group(1), "text": message_match.group(2)})

    if group_name is None or sender_name is None:
        raise ValueError(f"Malformed ticket.md in {folder_path}: missing Remitente/Grupo fields")

    media_filenames = sorted(
        name for name in os.listdir(folder_path) if name != "ticket.md"
    )

    return {
        "ticket_id": os.path.basename(os.path.normpath(folder_path)),
        "group_name": group_name,
        "group_id": group_id,
        "sender_name": sender_name,
        "sender_id": sender_id,
        "generated_at": generated_at,
        "summary": " ".join(summary_lines),
        "problem_description": " ".join(problem_lines),
        "messages": messages,
        "media_filenames": media_filenames,
    }


def list_tickets(
    tickets_dir: str,
    group: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
) -> list[dict]:
    if not os.path.isdir(tickets_dir):
        return []

    results = []
    for name in sorted(os.listdir(tickets_dir), reverse=True):
        folder_path = os.path.join(tickets_dir, name)
        if not os.path.isdir(folder_path):
            continue
        try:
            ticket = parse_ticket(folder_path)
        except ValueError as exc:
            logger.warning("Skipping malformed ticket folder %s: %s", name, exc)
            continue

        if group and ticket["group_name"] != group:
            continue
        if date_from and (ticket["generated_at"] or "") < date_from:
            continue
        if date_to and (ticket["generated_at"] or "") > date_to:
            continue
        if q:
            haystack = f"{ticket['summary']} {ticket['problem_description']}".lower()
            if q.lower() not in haystack:
                continue

        results.append(ticket)

    return results


def get_ticket(tickets_dir: str, ticket_id: str) -> dict | None:
    if not _is_safe_path_component(ticket_id):
        return None
    folder_path = os.path.join(tickets_dir, ticket_id)
    if not os.path.isdir(folder_path):
        return None
    try:
        return parse_ticket(folder_path)
    except ValueError:
        return None


def safe_media_path(tickets_dir: str, ticket_id: str, filename: str) -> str | None:
    if not _is_safe_path_component(ticket_id) or not _is_safe_path_component(filename):
        return None
    file_path = os.path.join(tickets_dir, ticket_id, filename)
    if not os.path.isfile(file_path):
        return None
    return file_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tickets_reader.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tests passing

- [ ] **Step 6: Commit**

```bash
git add src/monitor/tickets_reader.py tests/test_tickets_reader.py
git commit -m "feat: add ticket folder parser with filtering and path-safety guards"
```

---

### Task 6: Auth dependencies & auth routes

**Files:**
- Create: `src/monitor/api/__init__.py`
- Create: `src/monitor/api/dependencies.py`
- Create: `src/monitor/api/auth_routes.py`
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `hash_password`/`verify_password` are NOT called directly here (only via `users.py`); `create_access_token`/`decode_access_token`/`AuthError` (Task 2); `get_user_by_email`/`get_user_by_id` (Task 3).
- Produces: `COOKIE_NAME = "beacon_token"` (module constant in `dependencies.py`); `make_dependencies(conn, jwt_secret: str) -> tuple[Callable, Callable]` returning `(get_current_user, require_admin)` — both are FastAPI-`Depends`-compatible callables; `get_current_user(request: Request) -> dict` raises `HTTPException(401)` if the cookie is missing/invalid/expired or the user no longer exists, otherwise returns the user dict (`id, email, role, created_at` — no `password_hash`, stripped before returning); `require_admin(user: dict = Depends(get_current_user)) -> dict` raises `HTTPException(403)` if `user["role"] != "admin"`. `create_auth_router(conn, config, get_current_user) -> APIRouter` with `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.

- [ ] **Step 1: Create `src/monitor/api/__init__.py`**

```python
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_api_auth.py
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.users import create_user
from monitor.api.dependencies import COOKIE_NAME, make_dependencies
from monitor.api.auth_routes import create_auth_router


class Config:
    jwt_secret = "test-secret"
    jwt_expiry_minutes = 60


def make_app(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"), check_same_thread=False)
    init_db(conn)
    create_user(conn, "agent@example.com", "s3cret", "user")

    get_current_user, require_admin = make_dependencies(conn, Config.jwt_secret)
    app = FastAPI()
    app.include_router(create_auth_router(conn, Config(), get_current_user))

    @app.get("/protected")
    def protected(user: dict = Depends(get_current_user)):
        return {"email": user["email"]}

    return app, conn


def test_login_sets_cookie_and_returns_user(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"email": "agent@example.com", "password": "s3cret"})

    assert response.status_code == 200
    assert response.json() == {"email": "agent@example.com", "role": "user"}
    assert COOKIE_NAME in response.cookies


def test_login_rejects_wrong_password(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"email": "agent@example.com", "password": "wrong"})

    assert response.status_code == 401


def test_me_requires_valid_cookie(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    unauthenticated = client.get("/api/auth/me")
    assert unauthenticated.status_code == 401

    client.post("/api/auth/login", json={"email": "agent@example.com", "password": "s3cret"})
    authenticated = client.get("/api/auth/me")
    assert authenticated.status_code == 200
    assert authenticated.json() == {"email": "agent@example.com", "role": "user"}


def test_logout_clears_cookie_and_blocks_further_access(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    client.post("/api/auth/login", json={"email": "agent@example.com", "password": "s3cret"})

    client.post("/api/auth/logout")
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_protected_route_uses_get_current_user_dependency(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    client.post("/api/auth/login", json={"email": "agent@example.com", "password": "s3cret"})

    response = client.get("/protected")

    assert response.status_code == 200
    assert response.json() == {"email": "agent@example.com"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_api_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.api.dependencies'`

- [ ] **Step 4: Implement `src/monitor/api/dependencies.py`**

```python
from fastapi import Depends, HTTPException, Request

from monitor.auth import AuthError, decode_access_token
from monitor.users import get_user_by_id

COOKIE_NAME = "beacon_token"


def make_dependencies(conn, jwt_secret: str):
    def get_current_user(request: Request) -> dict:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")

        try:
            payload = decode_access_token(token, jwt_secret)
        except AuthError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user = get_user_by_id(conn, payload["user_id"])
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")

        return {"id": user["id"], "email": user["email"], "role": user["role"], "created_at": user["created_at"]}

    def require_admin(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return user

    return get_current_user, require_admin
```

- [ ] **Step 5: Implement `src/monitor/api/auth_routes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response

from monitor.auth import create_access_token, verify_password
from monitor.users import get_user_by_email

from .dependencies import COOKIE_NAME


def create_auth_router(conn, config, get_current_user) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    @router.post("/login")
    def login(credentials: dict, response: Response):
        email = credentials.get("email", "")
        password = credentials.get("password", "")

        user = get_user_by_email(conn, email)
        if user is None or not verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        token = create_access_token(
            user["id"], user["email"], user["role"], config.jwt_secret, config.jwt_expiry_minutes
        )
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=config.jwt_expiry_minutes * 60,
        )
        return {"email": user["email"], "role": user["role"]}

    @router.post("/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME)
        return {"status": "ok"}

    @router.get("/me")
    def me(user: dict = Depends(get_current_user)):
        return {"email": user["email"], "role": user["role"]}

    return router
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_api_auth.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add src/monitor/api/__init__.py src/monitor/api/dependencies.py src/monitor/api/auth_routes.py tests/test_api_auth.py
git commit -m "feat: add auth dependencies and login/logout/me routes"
```

---

### Task 7: Admin routes (user management)

**Files:**
- Create: `src/monitor/api/admin_routes.py`
- Test: `tests/test_api_admin.py`

**Interfaces:**
- Consumes: `create_user`/`list_users` (Task 3), `require_admin` (Task 6).
- Produces: `create_admin_router(conn, require_admin) -> APIRouter` with `GET /api/admin/users` and `POST /api/admin/users`, both admin-only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_admin.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.users import create_user
from monitor.api.dependencies import make_dependencies
from monitor.api.auth_routes import create_auth_router
from monitor.api.admin_routes import create_admin_router


class Config:
    jwt_secret = "test-secret"
    jwt_expiry_minutes = 60


def make_app(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"), check_same_thread=False)
    init_db(conn)
    create_user(conn, "admin@example.com", "adminpw", "admin")
    create_user(conn, "agent@example.com", "agentpw", "user")

    get_current_user, require_admin = make_dependencies(conn, Config.jwt_secret)
    app = FastAPI()
    app.include_router(create_auth_router(conn, Config(), get_current_user))
    app.include_router(create_admin_router(conn, require_admin))
    return app, conn


def login(client, email, password):
    client.post("/api/auth/login", json={"email": email, "password": password})


def test_admin_can_list_users(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    login(client, "admin@example.com", "adminpw")

    response = client.get("/api/admin/users")

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert emails == {"admin@example.com", "agent@example.com"}


def test_non_admin_cannot_list_users(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    login(client, "agent@example.com", "agentpw")

    response = client.get("/api/admin/users")

    assert response.status_code == 403


def test_admin_can_create_user(tmp_path):
    app, conn = make_app(tmp_path)
    client = TestClient(app)
    login(client, "admin@example.com", "adminpw")

    response = client.post(
        "/api/admin/users", json={"email": "new@example.com", "password": "newpw", "role": "user"}
    )

    assert response.status_code == 200
    from monitor.users import get_user_by_email
    assert get_user_by_email(conn, "new@example.com") is not None


def test_admin_create_user_rejects_duplicate_email(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    login(client, "admin@example.com", "adminpw")

    response = client.post(
        "/api/admin/users", json={"email": "agent@example.com", "password": "x", "role": "user"}
    )

    assert response.status_code == 400


def test_non_admin_cannot_create_user(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    login(client, "agent@example.com", "agentpw")

    response = client.post(
        "/api/admin/users", json={"email": "new@example.com", "password": "x", "role": "user"}
    )

    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_admin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.api.admin_routes'`

- [ ] **Step 3: Implement `src/monitor/api/admin_routes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException

from monitor.users import create_user, list_users


def create_admin_router(conn, require_admin) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    @router.get("/users")
    def get_users(admin: dict = Depends(require_admin)):
        return list_users(conn)

    @router.post("/users")
    def post_user(payload: dict, admin: dict = Depends(require_admin)):
        email = payload.get("email", "")
        password = payload.get("password", "")
        role = payload.get("role", "user")

        try:
            user_id = create_user(conn, email, password, role)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return {"id": user_id, "email": email, "role": role}

    return router
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_admin.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/api/admin_routes.py tests/test_api_admin.py
git commit -m "feat: add admin-only user list/create routes"
```

---

### Task 8: Tickets routes

**Files:**
- Create: `src/monitor/api/tickets_routes.py`
- Test: `tests/test_api_tickets.py`

**Interfaces:**
- Consumes: `list_tickets`/`get_ticket`/`safe_media_path` (Task 5), `get_status`/`get_history`/`set_status` (Task 4), `get_current_user` (Task 6).
- Produces: `create_tickets_router(tickets_dir, conn, get_current_user) -> APIRouter` with `GET /api/tickets`, `GET /api/tickets/{ticket_id}`, `GET /api/tickets/{ticket_id}/media/{filename}`, `PUT /api/tickets/{ticket_id}/status`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_tickets.py
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.users import create_user
from monitor.api.dependencies import make_dependencies
from monitor.api.auth_routes import create_auth_router
from monitor.api.tickets_routes import create_tickets_router


class Config:
    jwt_secret = "test-secret"
    jwt_expiry_minutes = 60


TICKET_MD = """# Ticket de soporte — Soporte Acme

**Remitente:** Juan Perez (521555@c.us)
**Grupo:** Soporte Acme (1@g.us)
**Generado:** 2026-07-21T10:05:00+00:00

## Resumen
Cliente reporta factura incorrecta con foto adjunta.

## Descripcion del problema
La factura de julio llego con el monto equivocado.

## Mensajes originales
- [2026-07-21T10:00:00+00:00] Mi factura llego mal
"""


def make_ticket(tickets_dir, name="2026-07-21-soporte-acme-juan-perez-521555-c-us-m1"):
    folder = os.path.join(tickets_dir, name)
    os.makedirs(folder)
    with open(os.path.join(folder, "ticket.md"), "w", encoding="utf-8") as f:
        f.write(TICKET_MD)
    with open(os.path.join(folder, "adjunto_1.jpg"), "wb") as f:
        f.write(b"fake-bytes")
    return name


def make_app(tmp_path):
    tickets_dir = str(tmp_path / "tickets")
    os.makedirs(tickets_dir)
    conn = get_connection(str(tmp_path / "monitor.db"), check_same_thread=False)
    init_db(conn)
    create_user(conn, "agent@example.com", "s3cret", "user")

    get_current_user, _ = make_dependencies(conn, Config.jwt_secret)
    app = FastAPI()
    app.include_router(create_auth_router(conn, Config(), get_current_user))
    app.include_router(create_tickets_router(tickets_dir, conn, get_current_user))
    return app, conn, tickets_dir


def login(client):
    client.post("/api/auth/login", json={"email": "agent@example.com", "password": "s3cret"})


def test_list_tickets_requires_auth(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    make_ticket(tickets_dir)
    client = TestClient(app)

    response = client.get("/api/tickets")

    assert response.status_code == 401


def test_list_tickets_returns_parsed_tickets(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    name = make_ticket(tickets_dir)
    client = TestClient(app)
    login(client)

    response = client.get("/api/tickets")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticket_id"] == name
    assert body[0]["group_name"] == "Soporte Acme"


def test_get_ticket_detail_includes_status_and_history(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    name = make_ticket(tickets_dir)
    client = TestClient(app)
    login(client)

    response = client.get(f"/api/tickets/{name}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pendiente"
    assert body["causa_raiz"] == ""
    assert body["history"] == []
    assert body["media_filenames"] == ["adjunto_1.jpg"]


def test_get_ticket_detail_404_for_unknown_ticket(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    client = TestClient(app)
    login(client)

    response = client.get("/api/tickets/does-not-exist")

    assert response.status_code == 404


def test_get_ticket_media_serves_file(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    name = make_ticket(tickets_dir)
    client = TestClient(app)
    login(client)

    response = client.get(f"/api/tickets/{name}/media/adjunto_1.jpg")

    assert response.status_code == 200
    assert response.content == b"fake-bytes"


def test_get_ticket_media_rejects_path_traversal(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    name = make_ticket(tickets_dir)
    client = TestClient(app)
    login(client)

    response = client.get(f"/api/tickets/{name}/media/..%2F..%2Fticket.md")

    assert response.status_code == 404


def test_put_status_updates_and_appears_in_next_get(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    name = make_ticket(tickets_dir)
    client = TestClient(app)
    login(client)

    response = client.put(f"/api/tickets/{name}/status", json={"status": "en_progreso", "causa_raiz": "", "solucion": ""})
    assert response.status_code == 200
    assert response.json()["status"] == "en_progreso"

    detail = client.get(f"/api/tickets/{name}").json()
    assert detail["status"] == "en_progreso"
    assert len(detail["history"]) == 1


def test_put_status_resuelto_without_fields_returns_400(tmp_path):
    app, _, tickets_dir = make_app(tmp_path)
    name = make_ticket(tickets_dir)
    client = TestClient(app)
    login(client)

    response = client.put(f"/api/tickets/{name}/status", json={"status": "resuelto", "causa_raiz": "", "solucion": ""})

    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_tickets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.api.tickets_routes'`

- [ ] **Step 3: Implement `src/monitor/api/tickets_routes.py`**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from monitor.ticket_status import get_history, get_status, set_status
from monitor.tickets_reader import get_ticket, list_tickets, safe_media_path


def create_tickets_router(tickets_dir, conn, get_current_user) -> APIRouter:
    router = APIRouter(prefix="/api/tickets")

    @router.get("")
    def get_tickets_list(
        group: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        user: dict = Depends(get_current_user),
    ):
        return list_tickets(tickets_dir, group=group, date_from=date_from, date_to=date_to, q=q)

    @router.get("/{ticket_id}")
    def get_ticket_detail(ticket_id: str, user: dict = Depends(get_current_user)):
        ticket = get_ticket(tickets_dir, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="Ticket not found")

        status = get_status(conn, ticket_id)
        history = get_history(conn, ticket_id)
        return {
            **ticket,
            "status": status["status"],
            "causa_raiz": status["causa_raiz"],
            "solucion": status["solucion"],
            "history": history,
        }

    @router.get("/{ticket_id}/media/{filename}")
    def get_ticket_media(ticket_id: str, filename: str, user: dict = Depends(get_current_user)):
        file_path = safe_media_path(tickets_dir, ticket_id, filename)
        if file_path is None:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(file_path)

    @router.put("/{ticket_id}/status")
    def put_ticket_status(ticket_id: str, payload: dict, user: dict = Depends(get_current_user)):
        status = payload.get("status", "")
        causa_raiz = payload.get("causa_raiz", "")
        solucion = payload.get("solucion", "")

        try:
            result = set_status(
                conn, ticket_id, status, causa_raiz, solucion, user["email"], datetime.now(timezone.utc)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return result

    return router
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_tickets.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/monitor/api/tickets_routes.py tests/test_api_tickets.py
git commit -m "feat: add tickets list/detail/media/status routes"
```

---

### Task 9: Wire routers and static frontend into main.py

**Files:**
- Modify: `src/monitor/main.py`
- Modify: `tests/test_main_smoke.py`

**Interfaces:**
- Consumes: `make_dependencies` (Task 6), `create_auth_router` (Task 6), `create_admin_router` (Task 7), `create_tickets_router` (Task 8).
- Produces: `create_full_app` now returns an app with `/api/auth/*`, `/api/admin/*`, `/api/tickets/*` routes in addition to the existing `/webhook/waha` and `/health`, plus (when present) the built frontend served as static files at `/`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_smoke.py` (keep the existing `test_create_full_app_health_check` and `test_create_full_app_honors_monitor_db_path_env_override` tests as-is):

```python
def test_create_full_app_wires_new_api_routes(tmp_path, monkeypatch):
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
            auth:
              jwt_secret: "test-secret"
              jwt_expiry_minutes: 1440
            """
        )
    )

    from monitor.main import create_full_app
    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    unauthenticated = client.get("/api/auth/me")
    assert unauthenticated.status_code == 401

    tickets_response = client.get("/api/tickets")
    assert tickets_response.status_code == 401
```

(`TestClient` and `create_full_app`'s existing import setup are already at the top of this file from earlier tasks — reuse them, don't duplicate imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_smoke.py -v`
Expected: FAIL — `404 Not Found` for `/api/auth/me` and `/api/tickets` since the routers aren't wired yet.

- [ ] **Step 3: Implement the wiring in `src/monitor/main.py`**

Add imports at the top:

```python
from monitor.api.admin_routes import create_admin_router
from monitor.api.auth_routes import create_auth_router
from monitor.api.dependencies import make_dependencies
from monitor.api.tickets_routes import create_tickets_router
```

In `create_full_app`, after `app = create_app(conn, config, llm)` and before the `if start_background_scheduler:` block, add:

```python
    get_current_user, require_admin = make_dependencies(conn, config.jwt_secret)
    app.include_router(create_auth_router(conn, config, get_current_user))
    app.include_router(create_admin_router(conn, require_admin))
    app.include_router(create_tickets_router(config.tickets_dir, conn, get_current_user))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_smoke.py -v`
Expected: PASS (all smoke tests)

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -v`
Expected: all tests passing (this is the last backend-only task before the frontend begins)

- [ ] **Step 6: Commit**

```bash
git add src/monitor/main.py tests/test_main_smoke.py
git commit -m "feat: wire auth/admin/tickets routers into the full app"
```

Note: static file serving for the built frontend is added in Task 16 (Docker/deployment task), once the frontend actually exists to build and serve — wiring it here would reference a directory (`frontend/dist`) that doesn't exist until Task 10+.

---

### Task 10: Frontend scaffolding (Vite + React + router + API client + auth context)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/vitest.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.jsx`
- Create: `frontend/src/App.jsx`
- Create: `frontend/src/api/client.js`
- Create: `frontend/src/auth/AuthContext.jsx`
- Create: `frontend/src/auth/RequireAuth.jsx`
- Create: `frontend/src/auth/RequireAdmin.jsx`
- Create: `frontend/src/test/setup.js`
- Test: `frontend/src/api/client.test.js`
- Test: `frontend/src/auth/AuthContext.test.jsx`

**Interfaces:**
- Consumes: the backend's `/api/auth/me`, `/api/auth/login`, `/api/auth/logout` endpoints (Task 6).
- Produces: `apiGet(path)`, `apiPost(path, body)`, `apiPut(path, body)` in `src/api/client.js` (all use `fetch` with `credentials: "include"`, throw an `Error` with the response status on non-2xx); `AuthProvider`, `useAuth()` (returns `{user, loading, login, logout}`) in `src/auth/AuthContext.jsx`; `RequireAuth`, `RequireAdmin` route-guard components (redirect to `/login` or `/` respectively when the condition isn't met).

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "dans-beacon-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.js`**

```javascript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

- [ ] **Step 3: Write `frontend/vitest.config.js`**

```javascript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    globals: true,
  },
});
```

- [ ] **Step 4: Write `frontend/src/test/setup.js`**

```javascript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <title>Dan's Beacon</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Write the failing test for the API client**

```javascript
// frontend/src/api/client.test.js
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost, apiPut } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiGet", () => {
  it("returns parsed JSON on success", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ hello: "world" }),
    });

    const result = await apiGet("/api/tickets");

    expect(result).toEqual({ hello: "world" });
    expect(global.fetch).toHaveBeenCalledWith("/api/tickets", expect.objectContaining({ credentials: "include" }));
  });

  it("throws on non-2xx response", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) });

    await expect(apiGet("/api/tickets")).rejects.toThrow("401");
  });
});

describe("apiPost", () => {
  it("sends a JSON body and returns parsed JSON", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });

    const result = await apiPost("/api/auth/login", { email: "a@b.com", password: "x" });

    expect(result).toEqual({ ok: true });
    const [, options] = global.fetch.mock.calls[0];
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ email: "a@b.com", password: "x" });
  });
});

describe("apiPut", () => {
  it("sends a PUT request with a JSON body", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "resuelto" }) });

    const result = await apiPut("/api/tickets/t1/status", { status: "resuelto" });

    expect(result).toEqual({ status: "resuelto" });
    const [, options] = global.fetch.mock.calls[0];
    expect(options.method).toBe("PUT");
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `Cannot find module './client'`

- [ ] **Step 8: Implement `frontend/src/api/client.js`**

```javascript
async function request(path, options = {}) {
  const response = await fetch(path, { credentials: "include", ...options });
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }
  return response.json();
}

export function apiGet(path) {
  return request(path);
}

export function apiPost(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function apiPut(path, body) {
  return request(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npm test -- client.test.js`
Expected: PASS (4 passed)

- [ ] **Step 10: Write the failing test for AuthContext**

```javascript
// frontend/src/auth/AuthContext.test.jsx
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthContext";

vi.mock("../api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import { apiGet, apiPost } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

function Probe() {
  const { user, loading } = useAuth();
  if (loading) return <div>loading</div>;
  return <div>{user ? `logged in as ${user.email}` : "logged out"}</div>;
}

describe("AuthProvider", () => {
  it("loads the current user from /api/auth/me on mount", async () => {
    apiGet.mockResolvedValue({ email: "a@b.com", role: "user" });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await waitFor(() => screen.getByText("logged in as a@b.com"));
  });

  it("shows logged out when /api/auth/me fails", async () => {
    apiGet.mockRejectedValue(new Error("401"));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await waitFor(() => screen.getByText("logged out"));
  });

  it("login() calls apiPost and updates user state", async () => {
    apiGet.mockRejectedValue(new Error("401"));
    apiPost.mockResolvedValue({ email: "a@b.com", role: "admin" });

    function LoginProbe() {
      const { user, login } = useAuth();
      return (
        <div>
          <div>{user ? `logged in as ${user.email}` : "logged out"}</div>
          <button onClick={() => login("a@b.com", "pw")}>login</button>
        </div>
      );
    }

    render(
      <AuthProvider>
        <LoginProbe />
      </AuthProvider>
    );

    await waitFor(() => screen.getByText("logged out"));
    await act(async () => {
      screen.getByText("login").click();
    });

    await waitFor(() => screen.getByText("logged in as a@b.com"));
  });
});
```

- [ ] **Step 11: Run test to verify it fails**

Run: `cd frontend && npm test -- AuthContext.test.jsx`
Expected: FAIL — `Cannot find module './AuthContext'`

- [ ] **Step 12: Implement `frontend/src/auth/AuthContext.jsx`**

```jsx
import { createContext, useContext, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiGet("/api/auth/me")
      .then((data) => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(email, password) {
    const data = await apiPost("/api/auth/login", { email, password });
    setUser(data);
    return data;
  }

  async function logout() {
    await apiPost("/api/auth/logout", {});
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
```

- [ ] **Step 13: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 14: Implement route guards**

`frontend/src/auth/RequireAuth.jsx`:

```jsx
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
```

`frontend/src/auth/RequireAdmin.jsx`:

```jsx
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function RequireAdmin({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "admin") return <Navigate to="/" replace />;
  return children;
}
```

- [ ] **Step 15: Write `frontend/src/main.jsx`**

```jsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);
```

- [ ] **Step 16: Write a placeholder `frontend/src/App.jsx`**

(Real pages are added in Tasks 11-15; this placeholder just establishes the provider/router shell so the app builds.)

```jsx
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="*" element={<div>Dan's Beacon</div>} />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 17: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold React + Vite frontend with API client and auth context"
```

---

### Task 11: Login page

**Files:**
- Create: `frontend/src/pages/LoginPage.jsx`
- Test: `frontend/src/pages/LoginPage.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `useAuth()` (Task 10).
- Produces: `LoginPage` component, mounted at route `/login` in `App.jsx`.

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/pages/LoginPage.test.jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import LoginPage from "./LoginPage";

vi.mock("../api/client", () => ({
  apiGet: vi.fn().mockRejectedValue(new Error("401")),
  apiPost: vi.fn(),
}));

import { apiPost } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

function renderLoginPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("LoginPage", () => {
  it("submits email and password and shows an error on failure", async () => {
    apiPost.mockRejectedValue(new Error("401"));
    renderLoginPage();

    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /iniciar sesión/i }));

    await waitFor(() => screen.getByText(/correo o contraseña incorrectos/i));
  });

  it("calls login with the entered credentials", async () => {
    apiPost.mockResolvedValue({ email: "a@b.com", role: "user" });
    renderLoginPage();

    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: /iniciar sesión/i }));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith("/api/auth/login", { email: "a@b.com", password: "s3cret" });
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- LoginPage.test.jsx`
Expected: FAIL — `Cannot find module './LoginPage'`

- [ ] **Step 3: Implement `frontend/src/pages/LoginPage.jsx`**

```jsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      await login(email, password);
      navigate("/");
    } catch {
      setError("Correo o contraseña incorrectos.");
    }
  }

  return (
    <div className="login-page">
      <h1>DAN'S BEACON</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="email">Correo</label>
        <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />

        <label htmlFor="password">Contraseña</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error && <p role="alert">{error}</p>}

        <button type="submit">Iniciar sesión</button>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- LoginPage.test.jsx`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the route into `App.jsx`**

```jsx
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import LoginPage from "./pages/LoginPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<div>Dan's Beacon</div>} />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LoginPage.jsx frontend/src/pages/LoginPage.test.jsx frontend/src/App.jsx
git commit -m "feat: add login page"
```

---

### Task 12: Sidebar + ticket list page

**Files:**
- Create: `frontend/src/components/Sidebar.jsx`
- Create: `frontend/src/pages/TicketListPage.jsx`
- Test: `frontend/src/pages/TicketListPage.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `apiGet` (Task 10), `useAuth()` (Task 10), `RequireAuth` (Task 10).
- Produces: `Sidebar` component (nav links + wordmark, shows "Usuarios" link only for `role === "admin"`); `TicketListPage` component fetching `GET /api/tickets` with query params from filter state, mounted at route `/` (wrapped in `RequireAuth`).

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/pages/TicketListPage.test.jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import TicketListPage from "./TicketListPage";

vi.mock("../api/client", () => ({ apiGet: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { email: "a@b.com", role: "user" } }) }));

import { apiGet } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

const TICKETS = [
  { ticket_id: "t1", group_name: "Soporte Acme", sender_name: "Juan Perez", generated_at: "2026-07-21T10:05:00+00:00", summary: "Factura incorrecta" },
];

describe("TicketListPage", () => {
  it("renders a table row per ticket returned by the API", async () => {
    apiGet.mockResolvedValue(TICKETS);

    render(
      <MemoryRouter>
        <TicketListPage />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("Soporte Acme"));
    expect(screen.getByText("Juan Perez")).toBeInTheDocument();
    expect(screen.getByText("Factura incorrecta")).toBeInTheDocument();
  });

  it("re-fetches with a group filter when the group input changes", async () => {
    apiGet.mockResolvedValue(TICKETS);

    render(
      <MemoryRouter>
        <TicketListPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    apiGet.mockClear();

    fireEvent.change(screen.getByLabelText(/grupo/i), { target: { value: "Soporte Beta" } });

    await waitFor(() => {
      expect(apiGet).toHaveBeenCalledWith(expect.stringContaining("group=Soporte+Beta"));
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- TicketListPage.test.jsx`
Expected: FAIL — `Cannot find module './TicketListPage'`

- [ ] **Step 3: Implement `frontend/src/components/Sidebar.jsx`**

```jsx
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Sidebar() {
  const { user, logout } = useAuth();

  return (
    <nav className="sidebar">
      <div className="wordmark">DAN'S BEACON</div>
      <Link to="/">Tickets</Link>
      {user?.role === "admin" && <Link to="/admin/users">Usuarios</Link>}
      <button onClick={logout}>Cerrar sesión</button>
    </nav>
  );
}
```

- [ ] **Step 4: Implement `frontend/src/pages/TicketListPage.jsx`**

```jsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/client";
import { Sidebar } from "../components/Sidebar";

export default function TicketListPage() {
  const [tickets, setTickets] = useState([]);
  const [group, setGroup] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (group) params.set("group", group);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (q) params.set("q", q);
    const query = params.toString();

    apiGet(`/api/tickets${query ? `?${query}` : ""}`)
      .then(setTickets)
      .catch(() => setTickets([]));
  }, [group, dateFrom, dateTo, q]);

  return (
    <div className="app-layout">
      <Sidebar />
      <main>
        <div className="filters">
          <label htmlFor="group-filter">Grupo</label>
          <input id="group-filter" value={group} onChange={(e) => setGroup(e.target.value)} />

          <label htmlFor="date-from-filter">Desde</label>
          <input id="date-from-filter" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />

          <label htmlFor="date-to-filter">Hasta</label>
          <input id="date-to-filter" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />

          <label htmlFor="search-filter">Buscar</label>
          <input id="search-filter" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>

        {tickets.length === 0 ? (
          <p>No hay tickets.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Grupo</th>
                <th>Remitente</th>
                <th>Fecha</th>
                <th>Resumen</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((ticket) => (
                <tr key={ticket.ticket_id}>
                  <td>
                    <Link to={`/tickets/${ticket.ticket_id}`}>{ticket.group_name}</Link>
                  </td>
                  <td>{ticket.sender_name}</td>
                  <td>{ticket.generated_at}</td>
                  <td>{ticket.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- TicketListPage.test.jsx`
Expected: PASS (2 passed)

- [ ] **Step 6: Wire the route into `App.jsx`**

```jsx
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import LoginPage from "./pages/LoginPage";
import TicketListPage from "./pages/TicketListPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <TicketListPage />
            </RequireAuth>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Sidebar.jsx frontend/src/pages/TicketListPage.jsx frontend/src/pages/TicketListPage.test.jsx frontend/src/App.jsx
git commit -m "feat: add sidebar and ticket list page with filters"
```

---

### Task 13: Ticket detail page (without the resolution panel)

**Files:**
- Create: `frontend/src/pages/TicketDetailPage.jsx`
- Test: `frontend/src/pages/TicketDetailPage.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `apiGet` (Task 10), `Sidebar` (Task 12).
- Produces: `TicketDetailPage` component fetching `GET /api/tickets/{ticket_id}` by URL param, rendering resumen/problema/mensajes/adjuntos with inline media previews based on file extension; mounted at route `/tickets/:ticketId` (wrapped in `RequireAuth`). Does NOT yet include the resolution panel — that's Task 14, added into this same page.

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/pages/TicketDetailPage.test.jsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import TicketDetailPage from "./TicketDetailPage";

vi.mock("../api/client", () => ({ apiGet: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { email: "a@b.com", role: "user" } }) }));

import { apiGet } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

const TICKET = {
  ticket_id: "t1",
  group_name: "Soporte Acme",
  sender_name: "Juan Perez",
  generated_at: "2026-07-21T10:05:00+00:00",
  summary: "Cliente reporta factura incorrecta.",
  problem_description: "La factura llego con el monto equivocado.",
  messages: [{ timestamp: "2026-07-21T10:00:00+00:00", text: "Mi factura llego mal" }],
  media_filenames: ["adjunto_1.jpg", "adjunto_2.mp3", "adjunto_3.pdf"],
  status: "pendiente",
  causa_raiz: "",
  solucion: "",
  history: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/tickets/t1"]}>
      <Routes>
        <Route path="/tickets/:ticketId" element={<TicketDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("TicketDetailPage", () => {
  it("renders summary, problem description, messages, and media previews by type", async () => {
    apiGet.mockResolvedValue(TICKET);

    renderPage();

    await waitFor(() => screen.getByText("Cliente reporta factura incorrecta."));
    expect(screen.getByText("La factura llego con el monto equivocado.")).toBeInTheDocument();
    expect(screen.getByText(/Mi factura llego mal/)).toBeInTheDocument();

    expect(screen.getByAltText("adjunto_1.jpg")).toBeInTheDocument();
    expect(screen.getByTestId("audio-adjunto_2.mp3")).toBeInTheDocument();
    expect(screen.getByText("adjunto_3.pdf")).toBeInTheDocument();
  });

  it("fetches the ticket using the URL param", async () => {
    apiGet.mockResolvedValue(TICKET);

    renderPage();

    await waitFor(() => {
      expect(apiGet).toHaveBeenCalledWith("/api/tickets/t1");
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- TicketDetailPage.test.jsx`
Expected: FAIL — `Cannot find module './TicketDetailPage'`

- [ ] **Step 3: Implement `frontend/src/pages/TicketDetailPage.jsx`**

```jsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiGet } from "../api/client";
import { Sidebar } from "../components/Sidebar";

const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp"];
const AUDIO_EXTENSIONS = [".mp3", ".ogg", ".oga", ".wav", ".m4a"];

function extensionOf(filename) {
  const idx = filename.lastIndexOf(".");
  return idx === -1 ? "" : filename.slice(idx).toLowerCase();
}

function MediaPreview({ ticketId, filename }) {
  const url = `/api/tickets/${ticketId}/media/${filename}`;
  const ext = extensionOf(filename);

  if (IMAGE_EXTENSIONS.includes(ext)) {
    return <img src={url} alt={filename} />;
  }
  if (AUDIO_EXTENSIONS.includes(ext)) {
    return <audio data-testid={`audio-${filename}`} controls src={url} />;
  }
  return (
    <a href={url} download>
      {filename}
    </a>
  );
}

export default function TicketDetailPage() {
  const { ticketId } = useParams();
  const [ticket, setTicket] = useState(null);

  useEffect(() => {
    apiGet(`/api/tickets/${ticketId}`)
      .then(setTicket)
      .catch(() => setTicket(null));
  }, [ticketId]);

  if (!ticket) {
    return (
      <div className="app-layout">
        <Sidebar />
        <main>Cargando...</main>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <Sidebar />
      <main className="ticket-detail">
        <header>
          <h1>
            {ticket.group_name} · {ticket.sender_name} · {ticket.generated_at}
          </h1>
        </header>

        <section>
          <h2>Resumen</h2>
          <p>{ticket.summary}</p>
        </section>

        <section>
          <h2>Descripcion del problema</h2>
          <p>{ticket.problem_description}</p>
        </section>

        <section>
          <h2>Mensajes originales</h2>
          <ul>
            {ticket.messages.map((message, index) => (
              <li key={index}>
                [{message.timestamp}] {message.text}
              </li>
            ))}
          </ul>
        </section>

        {ticket.media_filenames.length > 0 && (
          <section>
            <h2>Adjuntos</h2>
            <div className="media-list">
              {ticket.media_filenames.map((filename) => (
                <MediaPreview key={filename} ticketId={ticket.ticket_id} filename={filename} />
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- TicketDetailPage.test.jsx`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the route into `App.jsx`**

```jsx
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import LoginPage from "./pages/LoginPage";
import TicketListPage from "./pages/TicketListPage";
import TicketDetailPage from "./pages/TicketDetailPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <TicketListPage />
            </RequireAuth>
          }
        />
        <Route
          path="/tickets/:ticketId"
          element={
            <RequireAuth>
              <TicketDetailPage />
            </RequireAuth>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TicketDetailPage.jsx frontend/src/pages/TicketDetailPage.test.jsx frontend/src/App.jsx
git commit -m "feat: add ticket detail page with inline media previews"
```

---

### Task 14: Resolution panel (status control, causa raíz/solución, compact timeline + history modal)

**Files:**
- Create: `frontend/src/components/ResolutionPanel.jsx`
- Create: `frontend/src/components/HistoryModal.jsx`
- Test: `frontend/src/components/ResolutionPanel.test.jsx`
- Modify: `frontend/src/pages/TicketDetailPage.jsx`
- Modify: `frontend/src/pages/TicketDetailPage.test.jsx`

**Interfaces:**
- Consumes: `apiPut` (Task 10).
- Produces: `ResolutionPanel({ ticketId, status, causaRaiz, solucion, history, onSaved })` — a three-way segmented control (Pendiente/En progreso/Resuelto), causa raíz/solución text inputs, a "Guardar" button that calls `PUT /api/tickets/{ticketId}/status`, client-side validation blocking submission when status is "resuelto" with either field empty, a compact dot timeline (last 3 history entries) that opens `HistoryModal` on click. `HistoryModal({ history, onClose })` — a full vertical list of all history entries, closable.

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/components/ResolutionPanel.test.jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResolutionPanel } from "./ResolutionPanel";

vi.mock("../api/client", () => ({ apiPut: vi.fn() }));

import { apiPut } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

const HISTORY = [
  { status: "pendiente", changed_by: "a@b.com", changed_at: "2026-07-21T10:00:00+00:00" },
  { status: "en_progreso", changed_by: "a@b.com", changed_at: "2026-07-21T14:00:00+00:00" },
];

describe("ResolutionPanel", () => {
  it("blocks submitting resuelto with empty causa raiz/solucion", async () => {
    render(
      <ResolutionPanel
        ticketId="t1"
        status="en_progreso"
        causaRaiz=""
        solucion=""
        history={HISTORY}
        onSaved={() => {}}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /resuelto/i }));
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));

    await waitFor(() => screen.getByText(/causa raíz y solución son obligatorias/i));
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("submits status + fields and calls onSaved on success", async () => {
    apiPut.mockResolvedValue({ status: "resuelto", causa_raiz: "Factura mal calculada", solucion: "Se corrigio", history: HISTORY });
    const onSaved = vi.fn();

    render(
      <ResolutionPanel
        ticketId="t1"
        status="en_progreso"
        causaRaiz=""
        solucion=""
        history={HISTORY}
        onSaved={onSaved}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /resuelto/i }));
    fireEvent.change(screen.getByLabelText(/causa raíz/i), { target: { value: "Factura mal calculada" } });
    fireEvent.change(screen.getByLabelText(/solución/i), { target: { value: "Se corrigio" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));

    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledWith("/api/tickets/t1/status", {
        status: "resuelto",
        causa_raiz: "Factura mal calculada",
        solucion: "Se corrigio",
      });
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("opens the history modal with all entries when the compact timeline is clicked", async () => {
    render(
      <ResolutionPanel
        ticketId="t1"
        status="en_progreso"
        causaRaiz=""
        solucion=""
        history={HISTORY}
        onSaved={() => {}}
      />
    );

    fireEvent.click(screen.getByTestId("compact-timeline"));

    await waitFor(() => screen.getByRole("dialog"));
    expect(screen.getAllByText(/pendiente|en_progreso/i).length).toBeGreaterThanOrEqual(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ResolutionPanel.test.jsx`
Expected: FAIL — `Cannot find module './ResolutionPanel'`

- [ ] **Step 3: Implement `frontend/src/components/HistoryModal.jsx`**

```jsx
export function HistoryModal({ history, onClose }) {
  return (
    <div role="dialog" aria-label="Historial de estado" className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Historial</h3>
        <ul>
          {history.map((entry, index) => (
            <li key={index}>
              {entry.status} — {entry.changed_by} — {entry.changed_at}
            </li>
          ))}
        </ul>
        <button onClick={onClose}>Cerrar</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement `frontend/src/components/ResolutionPanel.jsx`**

```jsx
import { useState } from "react";
import { apiPut } from "../api/client";
import { HistoryModal } from "./HistoryModal";

const STATUSES = [
  { value: "pendiente", label: "Pendiente" },
  { value: "en_progreso", label: "En progreso" },
  { value: "resuelto", label: "Resuelto" },
];

export function ResolutionPanel({ ticketId, status, causaRaiz, solucion, history, onSaved }) {
  const [selectedStatus, setSelectedStatus] = useState(status);
  const [causa, setCausa] = useState(causaRaiz);
  const [solucionValue, setSolucionValue] = useState(solucion);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);

  const recentHistory = history.slice(-3);

  async function handleSave() {
    setError("");
    if (selectedStatus === "resuelto" && (!causa.trim() || !solucionValue.trim())) {
      setError("Causa raíz y solución son obligatorias para marcar como resuelto.");
      return;
    }

    try {
      const result = await apiPut(`/api/tickets/${ticketId}/status`, {
        status: selectedStatus,
        causa_raiz: causa,
        solucion: solucionValue,
      });
      onSaved(result);
    } catch {
      setError("No se pudo guardar el estado.");
    }
  }

  return (
    <section className="resolution-panel">
      <div className="segmented-control">
        {STATUSES.map((s) => (
          <button
            key={s.value}
            type="button"
            aria-pressed={selectedStatus === s.value}
            onClick={() => setSelectedStatus(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <label htmlFor="causa-raiz">Causa raíz</label>
      <textarea id="causa-raiz" value={causa} onChange={(e) => setCausa(e.target.value)} />

      <label htmlFor="solucion">Solución</label>
      <textarea id="solucion" value={solucionValue} onChange={(e) => setSolucionValue(e.target.value)} />

      {error && <p role="alert">{error}</p>}

      <button type="button" onClick={handleSave}>
        Guardar
      </button>

      <div className="compact-timeline" data-testid="compact-timeline" onClick={() => setShowHistory(true)}>
        {recentHistory.map((entry, index) => (
          <span key={index} className="timeline-dot" title={`${entry.status} — ${entry.changed_at}`} />
        ))}
      </div>

      {showHistory && <HistoryModal history={history} onClose={() => setShowHistory(false)} />}
    </section>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- ResolutionPanel.test.jsx`
Expected: PASS (3 passed)

- [ ] **Step 6: Integrate the panel into `TicketDetailPage`**

Modify `frontend/src/pages/TicketDetailPage.jsx`: import `ResolutionPanel`, and add it as the last section, passing the ticket's status fields and a `refresh` callback that re-fetches the ticket:

```jsx
import { ResolutionPanel } from "../components/ResolutionPanel";
```

Replace the `useEffect` block with a reusable fetch function, and add the panel after the "Adjuntos" section:

```jsx
  function fetchTicket() {
    apiGet(`/api/tickets/${ticketId}`)
      .then(setTicket)
      .catch(() => setTicket(null));
  }

  useEffect(() => {
    fetchTicket();
  }, [ticketId]);
```

```jsx
        <ResolutionPanel
          ticketId={ticket.ticket_id}
          status={ticket.status}
          causaRaiz={ticket.causa_raiz}
          solucion={ticket.solucion}
          history={ticket.history}
          onSaved={fetchTicket}
        />
```

- [ ] **Step 7: Add a test for the integration in `TicketDetailPage.test.jsx`**

```jsx
it("renders the resolution panel with the ticket's current status", async () => {
  apiGet.mockResolvedValue(TICKET);

  renderPage();

  await waitFor(() => screen.getByText("Cliente reporta factura incorrecta."));
  expect(screen.getByRole("button", { name: /^pendiente$/i })).toHaveAttribute("aria-pressed", "true");
});
```

- [ ] **Step 8: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests passing

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ResolutionPanel.jsx frontend/src/components/HistoryModal.jsx frontend/src/components/ResolutionPanel.test.jsx frontend/src/pages/TicketDetailPage.jsx frontend/src/pages/TicketDetailPage.test.jsx
git commit -m "feat: add status/resolution panel with compact timeline and history modal"
```

---

### Task 15: Admin user-management page

**Files:**
- Create: `frontend/src/pages/AdminUsersPage.jsx`
- Test: `frontend/src/pages/AdminUsersPage.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `apiGet`/`apiPost` (Task 10), `RequireAdmin` (Task 10), `Sidebar` (Task 12).
- Produces: `AdminUsersPage` component listing users (`GET /api/admin/users`) and a create-user form (`POST /api/admin/users`); mounted at `/admin/users` wrapped in `RequireAdmin`.

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/pages/AdminUsersPage.test.jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminUsersPage from "./AdminUsersPage";

vi.mock("../api/client", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { email: "admin@b.com", role: "admin" }, logout: () => {} }) }));

import { apiGet, apiPost } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdminUsersPage", () => {
  it("lists existing users", async () => {
    apiGet.mockResolvedValue([{ id: 1, email: "a@b.com", role: "user", created_at: "2026-07-22T00:00:00" }]);

    render(<AdminUsersPage />);

    await waitFor(() => screen.getByText("a@b.com"));
  });

  it("creates a new user and refreshes the list", async () => {
    apiGet.mockResolvedValueOnce([]).mockResolvedValueOnce([
      { id: 2, email: "new@b.com", role: "user", created_at: "2026-07-22T00:00:00" },
    ]);
    apiPost.mockResolvedValue({ id: 2, email: "new@b.com", role: "user" });

    render(<AdminUsersPage />);
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "new@b.com" } });
    fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "pw123" } });
    fireEvent.click(screen.getByRole("button", { name: /crear usuario/i }));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith("/api/admin/users", { email: "new@b.com", password: "pw123", role: "user" });
    });
    await waitFor(() => screen.getByText("new@b.com"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- AdminUsersPage.test.jsx`
Expected: FAIL — `Cannot find module './AdminUsersPage'`

- [ ] **Step 3: Implement `frontend/src/pages/AdminUsersPage.jsx`**

```jsx
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { Sidebar } from "../components/Sidebar";

export default function AdminUsersPage() {
  const [users, setUsers] = useState([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [error, setError] = useState("");

  function fetchUsers() {
    apiGet("/api/admin/users")
      .then(setUsers)
      .catch(() => setUsers([]));
  }

  useEffect(() => {
    fetchUsers();
  }, []);

  async function handleCreate(event) {
    event.preventDefault();
    setError("");
    try {
      await apiPost("/api/admin/users", { email, password, role });
      setEmail("");
      setPassword("");
      setRole("user");
      fetchUsers();
    } catch {
      setError("No se pudo crear el usuario.");
    }
  }

  return (
    <div className="app-layout">
      <Sidebar />
      <main>
        <h1>Usuarios</h1>
        <table>
          <thead>
            <tr>
              <th>Correo</th>
              <th>Rol</th>
              <th>Creado</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>{user.email}</td>
                <td>{user.role}</td>
                <td>{user.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h2>Crear usuario</h2>
        <form onSubmit={handleCreate}>
          <label htmlFor="new-email">Correo</label>
          <input id="new-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />

          <label htmlFor="new-password">Contraseña</label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <label htmlFor="new-role">Rol</label>
          <select id="new-role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="user">Usuario</option>
            <option value="admin">Administrador</option>
          </select>

          {error && <p role="alert">{error}</p>}

          <button type="submit">Crear usuario</button>
        </form>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- AdminUsersPage.test.jsx`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the route into `App.jsx`**

```jsx
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { RequireAdmin } from "./auth/RequireAdmin";
import LoginPage from "./pages/LoginPage";
import TicketListPage from "./pages/TicketListPage";
import TicketDetailPage from "./pages/TicketDetailPage";
import AdminUsersPage from "./pages/AdminUsersPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <TicketListPage />
            </RequireAuth>
          }
        />
        <Route
          path="/tickets/:ticketId"
          element={
            <RequireAuth>
              <TicketDetailPage />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/users"
          element={
            <RequireAdmin>
              <AdminUsersPage />
            </RequireAdmin>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests passing

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/AdminUsersPage.jsx frontend/src/pages/AdminUsersPage.test.jsx frontend/src/App.jsx
git commit -m "feat: add admin user-management page"
```

---

### Task 16: Global styling — Diner Americana visual identity

**Files:**
- Create: `frontend/src/styles/theme.css`
- Create: `frontend/src/styles/layout.css`
- Modify: `frontend/src/main.jsx`
- Test: `frontend/src/styles/theme.test.js`

**Interfaces:**
- Consumes: the semantic class names already used by `Sidebar`, `TicketListPage`, `TicketDetailPage`, `ResolutionPanel`, `HistoryModal`, `LoginPage`, `AdminUsersPage` (Tasks 11-15): `.sidebar`, `.wordmark`, `.app-layout`, `.filters`, `.ticket-detail`, `.resolution-panel`, `.segmented-control`, `.compact-timeline`, `.timeline-dot`, `.modal-overlay`, `.modal`, `.login-page`, `.media-list`.
- Produces: no new JS interfaces — pure CSS implementing the validated visual design (palette, Bebas Neue wordmark/headers, sidebar+table layout, single-column detail layout, resolution panel/timeline/modal appearance).

This task isn't algorithmic, so its "test" is a content sanity-check
(the right palette values are actually present) rather than behavioral
TDD — CSS correctness here is ultimately a visual judgment call, checked
by running the dev server, not by an assertion.

- [ ] **Step 1: Write the failing test**

```javascript
// frontend/src/styles/theme.test.js
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("theme.css", () => {
  it("defines the Diner Americana palette as CSS custom properties", () => {
    const css = readFileSync(new URL("./theme.css", import.meta.url), "utf-8");

    expect(css).toContain("--color-accent: #e8a33d");
    expect(css).toContain("--color-dark: #2b2420");
    expect(css).toContain("--color-cream: #f4e3c1");
    expect(css).toContain("--color-brown: #c97b2e");
    expect(css).toContain("Bebas Neue");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- theme.test.js`
Expected: FAIL — `ENOENT: no such file or directory, open 'theme.css'`

- [ ] **Step 3: Implement `frontend/src/styles/theme.css`**

```css
@import url("https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap");

:root {
  --color-accent: #e8a33d;
  --color-accent-dark: #c97b2e;
  --color-dark: #2b2420;
  --color-dark-surface: #3a2f28;
  --color-dark-surface-2: #241f1a;
  --color-cream: #f4e3c1;
  --color-brown: #c97b2e;
  --color-text-muted: #8a7a60;
  --font-wordmark: "Bebas Neue", sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}

body {
  font-family: var(--font-body);
  background: var(--color-cream);
  color: var(--color-dark);
  margin: 0;
}

.wordmark {
  font-family: var(--font-wordmark);
  letter-spacing: 1px;
  color: var(--color-accent);
  font-size: 22px;
  text-transform: uppercase;
}

h1, h2, h3 {
  font-family: var(--font-wordmark);
  letter-spacing: 0.5px;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- theme.test.js`
Expected: PASS (1 passed)

- [ ] **Step 5: Implement `frontend/src/styles/layout.css`**

```css
.app-layout {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 200px;
  background: var(--color-dark);
  color: var(--color-cream);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 14px;
}

.sidebar a,
.sidebar button {
  color: var(--color-cream);
  text-decoration: none;
  background: none;
  border: none;
  text-align: left;
  font-size: 14px;
  cursor: pointer;
}

.app-layout main {
  flex: 1;
  padding: 24px 32px;
}

.filters {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  margin-bottom: 16px;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid #e0d0ac;
}

.ticket-detail section {
  margin-bottom: 20px;
}

.media-list {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.media-list img {
  max-width: 160px;
  border-radius: 4px;
}

.resolution-panel {
  border-top: 2px solid var(--color-accent);
  padding-top: 16px;
  margin-top: 24px;
}

.segmented-control {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.segmented-control button {
  flex: 1;
  padding: 8px;
  border: none;
  background: var(--color-dark-surface);
  color: var(--color-cream);
  cursor: pointer;
}

.segmented-control button[aria-pressed="true"] {
  background: var(--color-accent);
  color: var(--color-dark);
  font-weight: bold;
}

.compact-timeline {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 14px;
  cursor: pointer;
}

.timeline-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-accent);
  display: inline-block;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal {
  background: var(--color-dark);
  color: var(--color-cream);
  padding: 24px;
  border-radius: 6px;
  min-width: 280px;
}

.login-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 16px;
}
```

- [ ] **Step 6: Import both stylesheets in `frontend/src/main.jsx`**

Add at the top of the file (before the other imports):

```jsx
import "./styles/theme.css";
import "./styles/layout.css";
```

- [ ] **Step 7: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests passing (this is a pure-CSS addition, no component test should change)

- [ ] **Step 8: Manually verify in the browser**

Run: `cd frontend && npm run dev`, open the printed local URL, log in, and confirm the sidebar/wordmark/table/resolution panel visually match the validated mockups (mustard accent, charcoal sidebar, Bebas Neue headers).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/styles/ frontend/src/main.jsx
git commit -m "feat: apply Diner Americana palette and Bebas Neue typography"
```

---

### Task 17: Multi-stage Dockerfile, static file serving, and README updates

**Files:**
- Modify: `Dockerfile`
- Modify: `src/monitor/main.py`
- Modify: `README.md`
- Test: `tests/test_main_smoke.py`

**Interfaces:**
- Consumes: the built `frontend/dist/` directory (produced by `npm run build`, not itself a code interface).
- Produces: `create_full_app` mounts `StaticFiles` at `/` when a `frontend/dist` directory exists next to the running code, serving the built React app; a multi-stage `Dockerfile` that builds the frontend and bundles it into the backend image.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_smoke.py`:

```python
def test_create_full_app_serves_frontend_dist_when_present(tmp_path, monkeypatch):
    import textwrap

    monkeypatch.delenv("MONITOR_DB_PATH", raising=False)

    frontend_dist = tmp_path / "frontend_dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<html><body>Dan's Beacon UI</body></html>")

    monkeypatch.setenv("MONITOR_FRONTEND_DIST", str(frontend_dist))

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
            auth:
              jwt_secret: "test-secret"
              jwt_expiry_minutes: 1440
            """
        )
    )

    from monitor.main import create_full_app
    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Dan's Beacon UI" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_smoke.py -v`
Expected: FAIL — `GET /` returns 404 (nothing mounted at `/` yet)

- [ ] **Step 3: Implement static file serving in `src/monitor/main.py`**

Add the import:

```python
from fastapi.staticfiles import StaticFiles
```

At the end of `create_full_app`, right before `return app`:

```python
    frontend_dist = os.environ.get("MONITOR_FRONTEND_DIST", "frontend/dist")
    if os.path.isdir(frontend_dist):
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
```

(This must be the LAST thing mounted on `app` — `StaticFiles` at `/` is a catch-all, so any route registered after it would be unreachable. All the routers are already included earlier in the function.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_smoke.py -v`
Expected: PASS (all smoke tests, including the new one)

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -v`
Expected: all tests passing

- [ ] **Step 6: Write the multi-stage `Dockerfile`**

Replace the existing `Dockerfile` contents with:

```dockerfile
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY --from=frontend-build /frontend/dist ./frontend/dist

ENV MONITOR_DB_PATH=/app/data/monitor.db
ENV MONITOR_FRONTEND_DIST=/app/frontend/dist

EXPOSE 8000

CMD ["uvicorn", "monitor.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Update `README.md`**

Add a section documenting the frontend and the first-admin bootstrap step. Append after the existing "Manual production verification" section:

```markdown
## Frontend dashboard

The React dashboard lives in `frontend/`. In development, run it separately
from the backend:

1. `cd frontend && npm install`
2. `npm run dev` — starts a dev server on port 5173 that proxies `/api/*`
   requests to the backend running on `localhost:8000` (see
   `frontend/vite.config.js`).

In production (Docker), the frontend is built at image-build time and served
by the same FastAPI process at `/` — no separate frontend deployment step.

### Creating the first admin account

The dashboard has no public signup. Before anyone can log in, create the
first admin account via the CLI:

```bash
python -m monitor.cli users create admin@example.com <password> admin
```

Additional accounts (admin or regular) can then be created from the
dashboard's "Usuarios" page by any existing admin.
```

- [ ] **Step 8: Commit**

```bash
git add Dockerfile README.md src/monitor/main.py tests/test_main_smoke.py
git commit -m "feat: serve built frontend from the backend and add multi-stage Dockerfile"
```

---

## Self-Review Notes

- **Spec coverage:** users/roles + email-password login ✅ (Tasks 1-3, 6),
  admin-created accounts + first-admin bootstrap ✅ (Task 3's CLI
  addition), ticket status/causa raíz/solución with resuelto-requires-
  both-fields validation ✅ (Task 4, 8, 14), status history / timeline ✅
  (Task 4's `ticket_status_history` + Task 14's compact dots + modal),
  ticket list with group/date/search filters ✅ (Task 5, 8, 12), ticket
  detail with inline media by type ✅ (Task 13), admin user management
  page ✅ (Task 15), single Docker image serving both API and frontend ✅
  (Task 17), Diner Americana palette + Bebas Neue typography ✅ (Task 16
  — added during self-review; the original task list had semantic HTML
  and class names but no CSS actually implementing the validated visual
  design, which would have silently shipped an unstyled dashboard).
- **Placeholder scan:** no `TBD`/`TODO`/"implement later" found; every
  step has concrete, runnable code or an exact command.
- **Type/interface consistency checked:** `ResolutionPanel`'s props
  (`ticketId, status, causaRaiz, solucion, history, onSaved`) match
  exactly how `TicketDetailPage` (Task 14 Step 6) invokes it. The
  `/api/tickets/{ticket_id}` response shape from Task 8
  (`{...ticket, status, causa_raiz, solucion, history}`) matches what
  Task 13's and Task 14's test fixtures assume. `get_status`/`set_status`
  (Task 4) and the router (Task 8) agree on the dict shape
  (`status, causa_raiz, solucion, updated_at`). `make_dependencies`
  (Task 6) returns `(get_current_user, require_admin)` in that order,
  and every later task (7, 8, 9) destructures/uses them in that same
  order.
- **One known non-goal reminder for whoever executes this plan:** per
  the design spec, ticket status is intentionally the only new stateful
  concept added here — there is still no group-management UI (stays
  CLI-only) and no real-time updates (no polling/websockets), matching
  the spec's stated non-goals.
