"""MCP client over the task's Streamable HTTP transport.

The kit warns when a harness never issues an `http` request, and `protocol.md`
§2 exposes task apps only that way. These tests drive a scripted JSON-RPC server
through a fake channel, covering both reply encodings and the header the spec
requires to be echoed.
"""
from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import GatedHarness                       # noqa: E402
from mcp import McpClient, McpError, tool_alias         # noqa: E402
from playbook import Playbook                           # noqa: E402
from protocol import Task                               # noqa: E402
from telemetry import Telemetry                         # noqa: E402

TOOLS = [{"name": "write_document", "description": "Write a file",
          "inputSchema": {"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]}}]


class FakeChannel:
    """Answers JSON-RPC the way a Streamable HTTP server does."""

    def __init__(self, sse_for=("tools/list",), fail_status=None):
        self.calls: list[dict] = []
        self.sse_for = set(sse_for)
        self.fail_status = fail_status

    async def log(self, text: str) -> None:
        self.calls.append({"log": text})

    async def http(self, url, method="POST", headers=None, body=None):
        payload = json.loads(body.decode()) if body else {}
        self.calls.append({"url": url, "method": method,
                           "headers": dict(headers or {}), "payload": payload})
        if self.fail_status:
            return {"ok": True, "status": self.fail_status, "headers": {},
                    "body_b64": base64.b64encode(b"nope").decode()}
        method_name = payload.get("method")
        if method_name == "initialize":
            reply = {"jsonrpc": "2.0", "id": payload["id"],
                     "result": {"protocolVersion": "2025-06-18",
                                "capabilities": {}, "serverInfo": {"name": "stub"}}}
            return {"ok": True, "status": 200,
                    "headers": {"mcp-session-id": "SESSION-1",
                                "content-type": "application/json"},
                    "body_b64": base64.b64encode(json.dumps(reply).encode()).decode()}
        if method_name == "notifications/initialized":
            return {"ok": True, "status": 202, "headers": {}, "body_b64": ""}
        if method_name == "tools/list":
            reply = {"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": TOOLS}}
            raw = json.dumps(reply)
            if "tools/list" in self.sse_for:
                body = f"event: message\ndata: {raw}\n\n".encode()
                ctype = "text/event-stream"
            else:
                body, ctype = raw.encode(), "application/json"
            return {"ok": True, "status": 200, "headers": {"content-type": ctype},
                    "body_b64": base64.b64encode(body).decode()}
        if method_name == "tools/call":
            reply = {"jsonrpc": "2.0", "id": payload["id"],
                     "result": {"content": [{"type": "text", "text": "wrote 5 bytes"}]}}
            return {"ok": True, "status": 200, "headers": {"content-type": "application/json"},
                    "body_b64": base64.b64encode(json.dumps(reply).encode()).decode()}
        raise AssertionError(f"unexpected method {method_name!r}")


def run(coro):
    return asyncio.run(coro)


class TestAlias(unittest.TestCase):
    def test_sanitised(self):
        self.assertEqual(tool_alias("apps", "write doc/1"), "mcp__apps__write_doc_1")

    def test_capped_and_unique(self):
        long = "x" * 200
        a, b = tool_alias("s", long + "a"), tool_alias("s", long + "b")
        self.assertLessEqual(len(a), 60)
        self.assertNotEqual(a, b)


class TestClient(unittest.TestCase):
    def test_initialize_then_tools_list_over_sse(self):
        channel = FakeChannel()
        client = McpClient(channel, "apps", "http://127.0.0.1:8000/mcp/")
        run(client.initialize())
        self.assertEqual(client.session_id, "SESSION-1")
        self.assertEqual(client.protocol_version, "2025-06-18")

        tools = run(client.list_tools())
        self.assertEqual([t.name for t in tools], ["write_document"])
        self.assertEqual(tools[0].schema["required"], ["path"])

    def test_notification_carries_no_id(self):
        channel = FakeChannel()
        client = McpClient(channel, "apps", "http://x/mcp/")
        run(client.initialize())
        notification = [c for c in channel.calls
                        if c.get("payload", {}).get("method") == "notifications/initialized"]
        self.assertEqual(len(notification), 1)
        self.assertNotIn("id", notification[0]["payload"])

    def test_session_and_protocol_headers_echoed(self):
        channel = FakeChannel()
        client = McpClient(channel, "apps", "http://x/mcp/")
        run(client.initialize())
        run(client.list_tools())
        last = [c for c in channel.calls if c.get("payload", {}).get("method") == "tools/list"][-1]
        self.assertEqual(last["headers"]["Mcp-Session-Id"], "SESSION-1")
        self.assertEqual(last["headers"]["MCP-Protocol-Version"], "2025-06-18")
        self.assertIn("text/event-stream", last["headers"]["Accept"])

    def test_call_tool_returns_text(self):
        channel = FakeChannel()
        client = McpClient(channel, "apps", "http://x/mcp/")
        run(client.initialize())
        self.assertEqual(run(client.call_tool("write_document", {"path": "/app/x"})),
                         "wrote 5 bytes")

    def test_http_error_raises(self):
        channel = FakeChannel(fail_status=500)
        client = McpClient(channel, "apps", "http://x/mcp/")
        with self.assertRaises(McpError):
            run(client.initialize())


class TestHarnessWiring(unittest.TestCase):
    def _harness(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ple-mcp-"))
        return GatedHarness(client=object(), playbook=Playbook(tmp / "p.jsonl"),
                            telemetry=Telemetry(tmp, run_index=0, run_id="t"))

    def test_tools_exposed_and_dispatched(self):
        channel = FakeChannel()
        task = Task(instruction="use the app",
                    mcp_servers=[{"name": "apps", "url": "http://x/mcp/"}])
        harness = self._harness()
        specs = run(harness._connect_mcp(channel, task))

        self.assertEqual([s["function"]["name"] for s in specs],
                         ["mcp__apps__write_document"])
        self.assertIn("mcp__apps__write_document", harness._mcp)

        call = {"function": {"name": "mcp__apps__write_document",
                             "arguments": json.dumps({"path": "/app/x"})}}
        self.assertEqual(run(harness._execute(channel, call)), "wrote 5 bytes")

    def test_broken_server_is_skipped_not_fatal(self):
        channel = FakeChannel(fail_status=500)
        task = Task(instruction="use the app",
                    mcp_servers=[{"name": "apps", "url": "http://x/mcp/"}])
        harness = self._harness()
        self.assertEqual(run(harness._connect_mcp(channel, task)), [])
        logs = [c["log"] for c in channel.calls if "log" in c]
        self.assertTrue(any("unavailable" in line for line in logs), logs)


if __name__ == "__main__":
    unittest.main()
