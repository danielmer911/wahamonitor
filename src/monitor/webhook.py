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

        message_id = payload.get("id")
        if not message_id:
            return {"status": "ignored", "reason": "missing message id"}

        if is_excluded(conn, group_id):
            return {"status": "ignored", "reason": "group excluded"}

        message = Message(
            message_id=message_id,
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
