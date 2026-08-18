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
