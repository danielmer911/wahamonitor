import os
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


def test_write_ticket_same_day_different_thread_produces_different_folders(tmp_path):
    """Test that two different threads for the same sender/group/day create separate ticket folders."""
    decision = TicketDecision(True, "resumen", "problema")
    now = datetime(2026, 7, 21, 10, 5, tzinfo=timezone.utc)

    # First thread with message m1
    thread1 = ThreadRecord(
        group_id="1@g.us",
        sender_id="521555@c.us",
        sender_name="Juan Perez",
        messages=[
            Message("m1", "First complaint", None, "2026-07-21T10:00:00+00:00"),
        ],
        last_activity_at="2026-07-21T10:00:00+00:00",
        deadline_at="2026-07-21T10:10:00+00:00",
    )

    # Second thread with message m2 (same sender/group, but different first message_id)
    thread2 = ThreadRecord(
        group_id="1@g.us",
        sender_id="521555@c.us",
        sender_name="Juan Perez",
        messages=[
            Message("m2", "Second separate complaint", None, "2026-07-21T10:30:00+00:00"),
        ],
        last_activity_at="2026-07-21T10:30:00+00:00",
        deadline_at="2026-07-21T10:40:00+00:00",
    )

    folder1 = write_ticket(str(tmp_path), "Soporte Acme", thread1, decision, FakeWahaClient(), now)
    folder2 = write_ticket(str(tmp_path), "Soporte Acme", thread2, decision, FakeWahaClient(), now)

    # Both folders should exist and be different
    assert folder1 != folder2
    assert os.path.isfile(os.path.join(folder1, "ticket.md"))
    assert os.path.isfile(os.path.join(folder2, "ticket.md"))

    # Check content is different
    with open(os.path.join(folder1, "ticket.md"), "r", encoding="utf-8") as f:
        content1 = f.read()
    with open(os.path.join(folder2, "ticket.md"), "r", encoding="utf-8") as f:
        content2 = f.read()

    assert "First complaint" in content1
    assert "Second separate complaint" in content2


def test_write_ticket_media_extension_from_mimetype_not_url(tmp_path):
    """Test that media extension is derived from mimetype even when URL has no extension or query string."""
    thread = ThreadRecord(
        group_id="1@g.us",
        sender_id="521555@c.us",
        sender_name="Juan Perez",
        messages=[
            Message("m1", "Aqui la foto", None, "2026-07-21T10:00:00+00:00"),
            Message(
                "m2",
                "Ver adjunto",
                # URL has no extension and a query string, but mimetype is image/png
                {"url": "https://waha.example.com/files/abc123?token=xyz", "mimetype": "image/png"},
                "2026-07-21T10:01:00+00:00",
            ),
        ],
        last_activity_at="2026-07-21T10:01:00+00:00",
        deadline_at="2026-07-21T10:11:00+00:00",
    )
    decision = TicketDecision(True, "resumen", "problema")
    now = datetime(2026, 7, 21, 10, 5, tzinfo=timezone.utc)

    folder = write_ticket(str(tmp_path), "Soporte Acme", thread, decision, FakeWahaClient(), now)

    # List media files (excluding ticket.md)
    media_files = [f for f in os.listdir(folder) if f != "ticket.md"]
    assert len(media_files) == 1

    # Should have .png extension from mimetype, not garbage from query string
    assert media_files[0].endswith(".png"), f"Expected .png extension, got {media_files[0]}"
    assert not media_files[0].endswith("?token=xyz")
    assert not media_files[0].endswith(".bin")
