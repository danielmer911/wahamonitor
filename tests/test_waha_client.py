import httpx
import respx

from monitor.waha_client import WahaClient


@respx.mock
def test_list_groups_returns_id_and_name():
    respx.get("https://waha.example.com/api/default/groups").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "1@g.us", "name": "Soporte Acme"},
                {"id": "2@g.us", "name": "Soporte Beta"},
            ],
        )
    )
    client = WahaClient("https://waha.example.com", "test-key")

    groups = client.list_groups()

    assert groups == [
        {"id": "1@g.us", "name": "Soporte Acme"},
        {"id": "2@g.us", "name": "Soporte Beta"},
    ]


@respx.mock
def test_list_groups_sends_api_key_header():
    route = respx.get("https://waha.example.com/api/default/groups").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = WahaClient("https://waha.example.com", "test-key")

    client.list_groups()

    assert route.calls.last.request.headers["X-Api-Key"] == "test-key"


@respx.mock
def test_download_media_returns_bytes():
    respx.get("https://waha.example.com/files/photo.jpg").mock(
        return_value=httpx.Response(200, content=b"fake-image-bytes")
    )
    client = WahaClient("https://waha.example.com", "test-key")

    data = client.download_media("https://waha.example.com/files/photo.jpg")

    assert data == b"fake-image-bytes"
