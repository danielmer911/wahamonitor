import httpx
import respx

from monitor.kappa_client import KappaClient


@respx.mock
def test_create_ticket_sends_multipart_with_api_key_and_fields():
    route = respx.post("https://kappa.example.com/api/helpdesk/create-ordo/").mock(
        return_value=httpx.Response(201, json={"id": 203, "token": "abc-123"})
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    result = client.create_ticket({"description": "Factura incorrecta", "client": 1}, [])

    assert result == {"id": 203, "token": "abc-123"}
    request = route.calls.last.request
    assert b'name="api_key"' in request.content
    assert b"test-key" in request.content
    assert b'name="description"' in request.content
    assert request.headers["content-type"].startswith("multipart/form-data")


@respx.mock
def test_create_ticket_attaches_files():
    route = respx.post("https://kappa.example.com/api/helpdesk/create-ordo/").mock(
        return_value=httpx.Response(201, json={"id": 204, "token": "def-456"})
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    client.create_ticket({"description": "Con foto"}, [("foto.jpg", b"fake-image-bytes", "image/jpeg")])

    request = route.calls.last.request
    assert b'name="files"; filename="foto.jpg"' in request.content
    assert b"fake-image-bytes" in request.content


@respx.mock
def test_list_clients_paginates_and_extracts_trade_name():
    respx.get("https://kappa.example.com/api/clients-all-ordo/?page=2").mock(
        return_value=httpx.Response(
            200,
            json={"count": 2, "next": None, "previous": None, "results": [{"id": 60, "trade_name": "EURO SUPERMERCADOS"}]},
        )
    )
    respx.get("https://kappa.example.com/api/clients-all-ordo/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": "https://kappa.example.com/api/clients-all-ordo/?page=2",
                "previous": None,
                "results": [{"id": 1, "trade_name": "Lambda Analytics", "other_field": "ignored"}],
            },
        )
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    clients = client.list_clients()

    assert clients == [
        {"id": 1, "trade_name": "Lambda Analytics"},
        {"id": 60, "trade_name": "EURO SUPERMERCADOS"},
    ]


@respx.mock
def test_list_projects_uses_initiative_name_not_trade_name():
    respx.get("https://kappa.example.com/api/initiatives-all-ordo/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 4, "trade_name": "Lambda Analytics", "initiative_name": "KAPPA"}],
            },
        )
    )
    client = KappaClient("https://kappa.example.com", "test-key")

    projects = client.list_projects()

    assert projects == [{"id": 4, "name": "KAPPA", "client_trade_name": "Lambda Analytics"}]
