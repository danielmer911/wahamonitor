import logging
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

logger = logging.getLogger(__name__)


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
        # Accepted residual risk (see design spec's Error Handling section): if the
        # process crashes between create_ticket succeeding and record_kappa_ticket's
        # commit below, nothing is recorded locally. On restart this thread looks
        # never-ticketed and create_ticket would be called again, creating a real
        # duplicate ticket in Kappa. No automated retry/idempotency mechanism is in
        # scope for this handoff-only integration — this is a known tradeoff, not a
        # guarantee that duplicates can't happen.
        result = kappa_client.create_ticket(fields, files)
    except Exception:
        _write_local_fallback(conn, config, waha_client, group_name_lookup, thread, decision, now)
        mark_needs_review(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)
        return

    try:
        record_kappa_ticket(
            conn, thread.group_id, thread.sender_id, last_message_id, result["id"], result.get("token"), now
        )
    except Exception:
        # The Kappa ticket genuinely exists now (create_ticket already succeeded) —
        # writing a local fallback file here would duplicate/confuse, not help.
        # Mark the thread ticketed (the handoff did succeed) but also flag it for
        # human review, and log the orphaned Kappa ticket's id/token so it can be
        # reconciled manually instead of silently losing track of it.
        logger.error(
            "Kappa ticket id=%s token=%s was created for group_id=%s sender_id=%s but "
            "local bookkeeping (record_kappa_ticket) failed; this ticket is orphaned "
            "from local tracking and needs manual reconciliation.",
            result.get("id"), result.get("token"), thread.group_id, thread.sender_id,
        )
        mark_ticketed(conn, thread.group_id, thread.sender_id)
        mark_needs_review(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)
        return

    mark_ticketed(conn, thread.group_id, thread.sender_id)


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
