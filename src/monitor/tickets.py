import mimetypes
import os
import re
from datetime import datetime

from monitor.evaluator import TicketDecision
from monitor.threads import ThreadRecord


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


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


def write_ticket(
    tickets_dir: str,
    group_name: str,
    thread: ThreadRecord,
    decision: TicketDecision,
    waha_client,
    now: datetime,
) -> str:
    date_str = now.strftime("%Y-%m-%d")
    last_message_id = thread.messages[-1].message_id if thread.messages else ""
    folder_name = f"{date_str}_{_slugify(group_name)}_{_slugify(thread.sender_name)}_{thread.sender_id}_{last_message_id}"
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
        extension = guess_media_extension(message.media, media_url)

        media_filename = f"adjunto_{index}{extension}"
        with open(os.path.join(folder_path, media_filename), "wb") as f:
            f.write(data)

    return folder_path
