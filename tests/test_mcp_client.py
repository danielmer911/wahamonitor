import httpx
import respx

from monitor.mcp_client import MCPClient, fetch_context


@respx.mock
def test_call_tool_sends_jsonrpc_request_and_extracts_text():
    route = respx.post("https://waha.example.com/mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "mensajes recientes del grupo"}]},
            },
        )
    )
    client = MCPClient("https://waha.example.com/mcp", api_key="mcp-key")

    result = client.call_tool("get_chat_messages", {"chatId": "g1", "limit": 50})

    assert result == "mensajes recientes del grupo"
    request_body = route.calls.last.request.content
    assert b"get_chat_messages" in request_body
    assert route.calls.last.request.headers["Authorization"] == "Bearer mcp-key"


@respx.mock
def test_call_tool_raises_on_jsonrpc_error():
    respx.post("https://waha.example.com/mcp").mock(
        return_value=httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "boom"}},
        )
    )
    client = MCPClient("https://waha.example.com/mcp", api_key=None)

    try:
        client.call_tool("get_chat_messages", {})
        assert False, "expected MCPError"
    except Exception as exc:
        assert "boom" in str(exc)


@respx.mock
def test_fetch_context_calls_get_chat_messages(tmp_path):
    respx.post("https://waha.example.com/mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "contexto del grupo"}]},
            },
        )
    )

    context = fetch_context("https://waha.example.com/mcp", "mcp-key", "g1", "s1")

    assert context == "contexto del grupo"
