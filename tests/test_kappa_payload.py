from monitor.evaluator import TicketDecision
from monitor.kappa_payload import build_kappa_payload, collect_media_files
from monitor.threads import Message, ThreadRecord


def make_thread(messages=None):
    return ThreadRecord(
        group_id="1@g.us",
        sender_id="521555@c.us",
        sender_name="Juan Perez",
        messages=messages
        or [Message("m1", "Mi factura llego mal", None, "2026-08-12T10:00:00+00:00")],
        last_activity_at="2026-08-12T10:00:00+00:00",
        deadline_at="2026-08-12T10:10:00+00:00",
    )


def test_build_kappa_payload_maps_fixed_fields():
    thread = make_thread()
    decision = TicketDecision(
        ticket_worthy=True,
        summary="Cliente reporta factura incorrecta.",
        problem_description="La factura de julio llego con el monto equivocado.",
    )

    payload = build_kappa_payload(thread, decision, client_id=60, project_id=192)

    assert payload["tomador_nombre"] == "Juan Perez"
    assert payload["tomador_telefono"] == "521555"
    assert payload["description"] == (
        "Cliente reporta factura incorrecta.\n\nLa factura de julio llego con el monto equivocado."
    )
    assert payload["help_type"] == "Soporte"
    assert payload["severity"] == "3"
    assert payload["sla_classification"] == "NORMAL"
    assert payload["incident_date"] == "2026-08-12T10:00:00+00:00"
    assert payload["client"] == 60
    assert payload["project"] == 192


def test_build_kappa_payload_omits_project_when_none():
    thread = make_thread()
    decision = TicketDecision(True, "resumen", "problema")

    payload = build_kappa_payload(thread, decision, client_id=60, project_id=None)

    assert "project" not in payload
    assert payload["client"] == 60


class FakeWahaClient:
    def download_media(self, media_url: str) -> bytes:
        return b"fake-bytes-for-" + media_url.encode()


def test_collect_media_files_downloads_and_names_attachments():
    thread = make_thread(
        messages=[
            Message("m1", "Hola", None, "2026-08-12T10:00:00+00:00"),
            Message(
                "m2",
                "Foto",
                {"url": "https://waha.example.com/files/foto.jpg", "mimetype": "image/jpeg"},
                "2026-08-12T10:01:00+00:00",
            ),
        ]
    )

    files = collect_media_files(thread, FakeWahaClient())

    assert len(files) == 1
    filename, content, mimetype = files[0]
    assert filename == "adjunto_1.jpg"
    assert content == b"fake-bytes-for-https://waha.example.com/files/foto.jpg"
    assert mimetype == "image/jpeg"


def test_collect_media_files_returns_empty_list_when_no_media():
    thread = make_thread()
    assert collect_media_files(thread, FakeWahaClient()) == []
