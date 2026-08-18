import httpx


class KappaClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def create_ticket(self, fields: dict, files: list[tuple[str, bytes, str]]) -> dict:
        # Build multipart form data: fields as regular form fields, files as file uploads
        form_data = [
            ("api_key", (None, self.api_key)),
            *[(key, (None, str(value))) for key, value in fields.items()],
            *[("files", (name, content, mimetype)) for name, content, mimetype in files],
        ]
        response = httpx.post(
            f"{self.base_url}/api/helpdesk/create-ordo/",
            files=form_data,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def list_clients(self) -> list[dict]:
        items = self._get_all_pages(f"{self.base_url}/api/clients-all-ordo/")
        return [{"id": item["id"], "trade_name": item["trade_name"]} for item in items]

    def list_projects(self) -> list[dict]:
        items = self._get_all_pages(f"{self.base_url}/api/initiatives-all-ordo/")
        return [
            {"id": item["id"], "name": item["initiative_name"], "client_trade_name": item["trade_name"]}
            for item in items
        ]

    def _get_all_pages(self, url: str) -> list[dict]:
        results = []
        next_url = url
        while next_url:
            response = httpx.request("GET", next_url, json={"api_key": self.api_key}, timeout=30)
            response.raise_for_status()
            data = response.json()
            results.extend(data["results"])
            next_url = data.get("next")
        return results
