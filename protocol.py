"""WebSocket task protocol.

STATUS: reconstructed from ple-bench.com/competition/guide. The documented
frame vocabulary is `task` -> `exec` / `read_file` / `write_file` / `http`
-> `result` -> `done`, UTF-8 JSON, <=16 MiB frames, <=8 concurrent
requests, base64 file payloads. The *field names* inside `exec` and
`result` are not published.

Before submitting, diff this file against `sample_submissions/pi-opus`
from github.com/google-research/ple. Only this module should need to
change; nothing above it knows the wire format.
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
from dataclasses import dataclass
from typing import Any

MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_CONCURRENT = 8


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ProtocolError(RuntimeError):
    pass


class TaskChannel:
    """One WebSocket session per task; multiplexes requests by id."""

    def __init__(self, ws: Any, task: dict[str, Any], timeout: float = 600.0) -> None:
        self.ws = ws
        self.task = task
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader and not self._reader.done():
            self._reader.cancel()

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                if len(raw) > MAX_FRAME_BYTES:
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if message.get("type") != "result":
                    continue
                future = self._pending.pop(message.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ProtocolError("channel closed"))
            self._pending.clear()

    async def _request(self, frame_type: str, **payload: Any) -> dict[str, Any]:
        async with self._semaphore:
            request_id = next(self._ids)
            future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            await self.ws.send(json.dumps({"type": frame_type, "id": request_id, **payload}))
            try:
                return await asyncio.wait_for(future, timeout=self.timeout)
            finally:
                self._pending.pop(request_id, None)

    # -- task operations --------------------------------------------------
    async def exec(self, command: str, workdir: str | None = None,
                   timeout: float | None = None) -> ExecResult:
        payload: dict[str, Any] = {"cmd": command}
        if workdir:
            payload["workdir"] = workdir
        if timeout:
            payload["timeout"] = timeout
        result = await self._request("exec", **payload)
        return ExecResult(
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            exit_code=int(result.get("exit_code", result.get("returncode", 1))),
        )

    async def read_file(self, path: str) -> bytes:
        result = await self._request("read_file", path=path)
        blob = result.get("content_b64") or result.get("content") or ""
        try:
            return base64.b64decode(blob)
        except Exception as exc:
            raise ProtocolError(f"read_file({path}): not base64") from exc

    async def read_text(self, path: str) -> str:
        return (await self.read_file(path)).decode("utf-8", errors="replace")

    async def write_file(self, path: str, data: bytes | str) -> None:
        raw = data.encode() if isinstance(data, str) else data
        await self._request("write_file", path=path,
                            content_b64=base64.b64encode(raw).decode())

    async def http(self, url: str, method: str = "GET",
                   body: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url, "method": method}
        if body is not None:
            payload["body"] = body
        return await self._request("http", **payload)

    async def done(self, summary: str) -> None:
        await self.ws.send(json.dumps({"type": "done", "summary": summary}))


def frame_task(raw: str) -> dict[str, Any]:
    message = json.loads(raw)
    if message.get("type") != "task":
        raise ProtocolError(f"expected a task frame, got {message.get('type')!r}")
    return message


def deliverables_of(task: dict[str, Any]) -> list[str]:
    """Every path the task asked us to produce."""
    for key in ("deliverables", "output_files", "expected_files"):
        value = task.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    return []


def discipline_of(task: dict[str, Any]) -> str:
    for key in ("discipline", "task_type", "category"):
        value = task.get(key)
        if isinstance(value, str):
            normalised = value.strip().lower()
            for known in ("structural", "civil", "electrical", "mechanical"):
                if known in normalised:
                    return known
    prompt = str(task.get("prompt", "")).lower()
    for known in ("structural", "civil", "electrical", "mechanical"):
        if known in prompt:
            return known
    return "unknown"
