"""Minimal MCP (Model Context Protocol) client over Streamable HTTP.

Implements just what the agent needs: initialize / tools/list / tools/call.
Both `application/json` and `text/event-stream` responses are supported.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

PROTOCOL_VERSION = "2025-06-18"


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(
        self,
        url: str,
        token: str | None = None,
        timeout: float = 15.0,
        client_name: str = "dataforensic-ai",
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.client_name = client_name
        self._session_id: str | None = None
        self._initialized = False
        self._tools: list[dict[str, Any]] = []
        self._request_id = 0
        self._client: httpx.AsyncClient | None = None

    # -- plumbing ---------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _parse_sse(body: str, content_type: str = "", status: int = 200) -> dict[str, Any]:
        """Pull the JSON-RPC reply out of an SSE body.

        Written defensively because the framing varies between gateways: data
        can span several lines within one event, comments and `event:` / `id:` /
        `retry:` lines are interleaved, and some servers emit a handshake event
        before the reply. Taking only the first `data:` line found the wrong
        thing, or nothing, and reported it as "no payload" without ever saying
        what had actually arrived.
        """
        events: list[str] = []
        current: list[str] = []

        for raw_line in body.splitlines():
            line = raw_line.rstrip("\r")
            if not line.strip():
                if current:
                    events.append("\n".join(current))
                    current = []
                continue
            if line.startswith(":"):  # comment / keep-alive
                continue
            if line.startswith("data:"):
                current.append(line[5:].lstrip())
        if current:
            events.append("\n".join(current))

        for payload in events:
            if not payload or payload == "[DONE]":
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            # A gateway may announce itself before answering; the reply is the
            # frame that carries a JSON-RPC envelope.
            if isinstance(parsed, dict) and (
                "jsonrpc" in parsed or "result" in parsed or "error" in parsed
            ):
                return parsed

        if not body.strip():
            raise MCPError(
                f"The MCP endpoint answered HTTP {status} with an empty body. "
                "This client expects the reply on the same response; a gateway "
                "that only delivers it on a separately opened stream is not "
                "supported."
            )
        preview = body.strip()[:300].replace("\n", " | ")
        raise MCPError(
            f"No JSON-RPC payload in the response (content-type: "
            f"{content_type or 'unknown'}, HTTP {status}). First bytes: {preview}"
        )

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        client = await self._http()
        body = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            body["params"] = params
        response = await client.post(self.url, json=body, headers=self._headers())
        if response.status_code >= 400:
            raise MCPError(f"MCP {method} failed: HTTP {response.status_code} {response.text[:200]}")
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        content_type = response.headers.get("content-type", "")
        payload = (
            self._parse_sse(response.text, content_type, response.status_code)
            if "text/event-stream" in content_type
            else response.json()
        )
        if isinstance(payload, dict) and payload.get("error"):
            raise MCPError(f"MCP {method} error: {payload['error']}")
        return payload.get("result") if isinstance(payload, dict) else payload

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        client = await self._http()
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        await client.post(self.url, json=body, headers=self._headers())

    # -- protocol ---------------------------------------------------------
    async def initialize(self) -> list[dict[str, Any]]:
        if self._initialized:
            return self._tools
        await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": self.client_name, "version": "0.1.0"},
            },
        )
        try:
            await self._notify("notifications/initialized")
        except Exception:  # noqa: BLE001 - some servers do not require it
            logger.debug("mcp_initialized_notification_skipped")
        self._initialized = True
        self._tools = await self.list_tools()
        return self._tools

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list")
        tools = (result or {}).get("tools", [])
        self._tools = tools
        return tools

    @property
    def tool_names(self) -> list[str]:
        return [t.get("name", "") for t in self._tools]

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names

    def resolve_tool(self, candidates: list[str]) -> str | None:
        """Pick the first available tool name, then try a fuzzy contains match."""
        names = self.tool_names
        for candidate in candidates:
            if candidate in names:
                return candidate
        for candidate in candidates:
            token = candidate.replace("_", "").lower()
            for name in names:
                if token in name.replace("_", "").lower():
                    return name
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            return result
        if result.get("isError"):
            raise MCPError(f"MCP tool {name} returned an error: {result}")
        if "structuredContent" in result and result["structuredContent"] is not None:
            return result["structuredContent"]
        chunks: list[str] = []
        for block in result.get("content", []) or []:
            if block.get("type") == "text":
                chunks.append(block.get("text", ""))
        joined = "\n".join(chunks).strip()
        if not joined:
            return result
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return {"text": joined}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
