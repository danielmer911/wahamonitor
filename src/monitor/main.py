import threading
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
    conn = get_connection(config.db_path, check_same_thread=False)
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


def app_factory():
    """Factory function for uvicorn to instantiate the FastAPI app.

    This ensures the app is only created when explicitly requested by uvicorn,
    not as a side effect of importing this module. This prevents unintended
    side effects (real HTTP calls, DB writes) during test collection or other
    import-time operations.
    """
    return create_full_app("config.yaml")
