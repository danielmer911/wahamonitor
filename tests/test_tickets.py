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
