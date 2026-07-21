import httpx


class MCPError(Exception):
    pass


class MCPClient:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self._request_id = 0

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def call_tool(self, name: str, arguments: dict) -> str:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = httpx.post(self.base_url, json=payload, headers=self._headers(), timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise MCPError(data["error"].get("message", "MCP error"))

        content = data["result"].get("content", [])
        return "\n".join(part.get("text", "") for part in content if part.get("type") == "text")


def fetch_context(mcp_url: str, api_key: str | None, group_id: str, sender_id: str) -> str:
    client = MCPClient(mcp_url, api_key)
    return client.call_tool("get_chat_messages", {"chatId": group_id, "limit": 50, "senderId": sender_id})
