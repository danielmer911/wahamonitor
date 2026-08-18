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
