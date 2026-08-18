import httpx
import respx

from monitor.waha_client import WahaClient


@respx.mock
def test_list_groups_returns_id_and_name():
    # Real WAHA /api/{session}/groups responses wrap each group in
    # "groupMetadata", with a nested "id" object (whose "_serialized"
    # field is the flat WhatsApp group id) and the display name under
    # "subject", not "name". This fixture mirrors that real shape,
    # confirmed against the production API.
    respx.get("https://waha.example.com/api/default/groups").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "groupMetadata": {
                        "id": {
                            "server": "g.us",
                            "user": "1",
                            "_serialized": "1@g.us",
                        },
                        "subject": "Soporte Acme",
                    }
                },
                {
                    "groupMetadata": {
                        "id": {
                            "server": "g.us",
                            "user": "2",
                            "_serialized": "2@g.us",
                        },
                        "subject": "Soporte Beta",
                    }
                },
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
