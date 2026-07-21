import httpx


class WahaClient:
    def __init__(self, base_url: str, api_key: str, session: str = "default"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key}

    def list_groups(self) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/api/{self.session}/groups",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def download_media(self, media_url: str) -> bytes:
        response = httpx.get(media_url, headers=self._headers(), timeout=60)
        response.raise_for_status()
        return response.content
