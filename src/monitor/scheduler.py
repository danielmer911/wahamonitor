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
            if decision.ticket_worthy:
                group_name = group_name_lookup.get(thread.group_id, thread.group_id)
                write_ticket(config.tickets_dir, group_name, thread, decision, waha_client, now)
                mark_ticketed(conn, thread.group_id, thread.sender_id)
            else:
                reset_deadline(conn, thread.group_id, thread.sender_id, now, config.default_inactivity_minutes)
        except Exception:
            mark_needs_review(conn, thread.group_id, thread.sender_id)
            continue

    return len(due_threads)
