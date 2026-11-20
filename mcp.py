"""MCP client over the task's Streamable HTTP transport.

`docs/protocol.md` §2 lets a harness reach the task's app servers only through
the `http` request, so everything here is built on `channel.http`: JSON-RPC 2.0
POSTs, the `Mcp-Session-Id` the server returns reused on later calls, and the
`MCP-Protocol-Version` negotiated at `initialize` echoed afterwards. Replies may
be JSON or `text/event-stream`, so both are parsed.

Why this exists: without it the harness can see a task's documents, mail and
spreadsheets only by shelling into the container. The kit's `mcp` stage warns
about exactly that, and held-out tasks that expose apps as MCP servers would be
half-served.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "gated-harness"
MAX_TOOL_NAME = 60


class McpError(RuntimeError):
    pass


def tool_alias(server: str, tool: str) -> str:
    """Model-facing tool name.

    Providers bound the name tightly and reject duplicates, so sanitise the
    server and tool into one identifier and cap it, keeping a hash suffix so two
    long names cannot collapse onto the same alias.
    """
    raw = f"mcp__{server}__{tool}"
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    if len(clean) <= MAX_TOOL_NAME:
        return clean
    digest = hashlib.sha1(clean.encode()).hexdigest()[:8]
    return f"{clean[: MAX_TOOL_NAME - 9]}_{digest}"


def _message_from(body: bytes, content_type: str, want_id: int | None) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    if "text/event-stream" in (content_type or ""):
        candidates = [line[5:].strip() for line in text.splitlines()
                      if line.startswith("data:")]
        candidates = [chunk for chunk in candidates if chunk and chunk != "[DONE]"]
    else:
        candidates = [text]
    for chunk in reversed(candidates):
        try:
            message = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and (want_id is None or message.get("id") == want_id):
            return message
    raise McpError(f"no JSON-RPC response for id={want_id} in "
                   f"{len(candidates)} chunk(s)")


@dataclass
class McpTool:
    name: str
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)


class McpClient:
    def __init__(self, channel: Any, server: str, url: str) -> None:
        self.channel = channel
        self.server = server
        self.url = url
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self._next_id = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    async def _post(self, payload: dict[str, Any],
                    expect_id: int | None) -> dict[str, Any]:
        reply = await self.channel.http(self.url, "POST", self._headers(),
                                        json.dumps(payload).encode())
        if reply.get("ok") is False:
            raise McpError(str(reply.get("error", "http request failed")))

        headers = {str(k).lower(): str(v) for k, v in (reply.get("headers") or {}).items()}
        if headers.get("mcp-session-id"):
            self.session_id = headers["mcp-session-id"]

        status = int(reply.get("status", 0) or 0)
        body = base64.b64decode(reply.get("body_b64") or "")
        if status >= 400:
            raise McpError(f"HTTP {status}: {body[:200].decode('utf-8', 'replace')}")
        if expect_id is None:
            return {}

        message = _message_from(body, headers.get("content-type", ""), expect_id)
        if message.get("error"):
            error = message["error"] or {}
            raise McpError(f"{error.get('code')}: {error.get('message')}")
        return message

    async def initialize(self) -> dict[str, Any]:
        self._next_id += 1
        message = await self._post({
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "1.0"},
            },
        }, self._next_id)
        result = message.get("result") or {}
        self.protocol_version = str(result.get("protocolVersion") or "") or None
        # Notification: no id, and the server may answer 202 with an empty body.
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized",
                          "params": {}}, None)
        return result

    async def list_tools(self) -> list[McpTool]:
        self._next_id += 1
        message = await self._post({"jsonrpc": "2.0", "id": self._next_id,
                                    "method": "tools/list", "params": {}},
                                   self._next_id)
        result = message.get("result") or {}
        tools: list[McpTool] = []
        for item in result.get("tools") or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            schema = item.get("inputSchema") or item.get("input_schema") or {}
            tools.append(McpTool(name=str(item["name"]),
                                 description=str(item.get("description") or ""),
                                 schema=schema if isinstance(schema, dict) else {}))
        return tools

    async def call_tool(self, tool: str, arguments: dict[str, Any]) -> str:
        self._next_id += 1
        message = await self._post({
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }, self._next_id)
        result = message.get("result") or {}
        parts: list[str] = []
        for item in result.get("content") or []:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type"):
                    parts.append(f"[{item.get('type')}]")
        text = "\n".join(p for p in parts if p)
        if result.get("isError"):
            raise McpError(text or "tool reported an error")
        return text[:20000] or "(no content)"
