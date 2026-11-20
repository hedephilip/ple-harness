"""WebSocket task protocol, version 1.

Implements docs/protocol.md from github.com/google-research/ple verbatim.

Earlier revisions of this file were a reconstruction from the competition
guide's prose and were wrong on nearly every field: the task carries
`instruction` (not `prompt`), exec takes `command` (not `cmd`), the result
carries a combined `output` (not `stdout`/`stderr`), and completion sends
`done` with `final_message` (not `summary`). There are also two frames that
had no equivalent at all: `cancel` (sent on timeout) and `usage` (token
accounting, which Stage 2 costs are computed from).

Verified against the reference implementation, not inferred.
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_CONCURRENT = 8
MAX_WRITE_BYTES = 10_000_000

_ID_SEQ = itertools.count(1)


@dataclass
class ExecResult:
    """`exit_code` is 124 and `timed_out` True when the command timed out."""

    output: str = ""
    exit_code: int = 0
    truncated: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class Task:
    """The first frame the evaluator sends."""

    instruction: str = ""
    workdir: str = "/app"
    session: str = ""
    protocol: int = 1
    limits: dict[str, Any] = field(default_factory=dict)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_frame(cls, message: dict[str, Any]) -> "Task":
        if message.get("type") != "task":
            raise ProtocolError(f"expected a task frame, got {message.get('type')!r}")
        return cls(
            instruction=str(message.get("instruction", "")),
            workdir=str(message.get("workdir", "/app")),
            session=str(message.get("session", "")),
            protocol=int(message.get("protocol", 1)),
            limits=message.get("limits") or {},
            mcp_servers=message.get("mcp_servers") or [],
        )

    @property
    def agent_timeout_sec(self) -> float | None:
        value = self.limits.get("agent_timeout_sec")
        return None if value is None else float(value)


class ProtocolError(RuntimeError):
    pass


class TaskCancelled(RuntimeError):
    """Raised when the evaluator sends `cancel` because the task time is up."""


class TaskChannel:
    """One WebSocket session per task; multiplexes up to 8 requests."""

    def __init__(self, ws: Any, task: Task) -> None:
        self.ws = ws
        self.task = task
        self.cancelled = asyncio.Event()
        self._pending: dict[str, asyncio.Future] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._reader: asyncio.Task | None = None

    # -- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader and not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                if isinstance(raw, str) and len(raw.encode()) > MAX_FRAME_BYTES:
                    continue
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                kind = message.get("type")
                if kind == "cancel":
                    self.cancelled.set()
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(TaskCancelled("time is up"))
                    continue
                if kind != "result":
                    continue
                future = self._pending.pop(str(message.get("id")), None)
                if future is not None and not future.done():
                    future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ProtocolError("channel closed"))
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ProtocolError("channel closed"))

    # -- request/response -------------------------------------------------
    async def _request(self, frame: dict[str, Any]) -> dict[str, Any]:
        if self.cancelled.is_set():
            raise TaskCancelled("time is up")
        async with self._semaphore:
            request_id = str(next(_ID_SEQ))
            future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            try:
                await self.ws.send(json.dumps({**frame, "id": request_id}))
                return await future
            finally:
                self._pending.pop(request_id, None)

    # -- file and shell access --------------------------------------------
    async def exec(self, command: str, timeout_sec: float | None = None) -> ExecResult:
        frame: dict[str, Any] = {"type": "exec", "command": command}
        if timeout_sec is not None:
            frame["timeout_sec"] = int(max(1, timeout_sec))
        result = await self._request(frame)
        if result.get("ok") is False:
            return ExecResult(output=str(result.get("error", "")), exit_code=1)
        return ExecResult(
            output=str(result.get("output", "")),
            exit_code=int(result.get("exit_code", 0) or 0),
            truncated=bool(result.get("truncated", False)),
            timed_out=bool(result.get("timed_out", False)),
        )

    async def read_file(self, path: str) -> bytes:
        result = await self._request({"type": "read_file", "path": path})
        if not result.get("ok", False):
            raise FileNotFoundError(f"{path}: {result.get('error', 'read failed')}")
        if result.get("truncated"):
            # Protocol section 2: a read returns at most 10 MB. Verifying a
            # truncated artifact would mean judging half a file as whole.
            raise ValueError(f"{path}: read truncated at the 10 MB cap")
        return base64.b64decode(result.get("content_b64") or "")

    async def read_text(self, path: str) -> str:
        return (await self.read_file(path)).decode("utf-8", errors="replace")

    async def write_file(self, path: str, data: bytes | str, append: bool = False) -> int:
        raw = data.encode() if isinstance(data, str) else data
        if len(raw) > MAX_WRITE_BYTES:
            raise ProtocolError(f"{path}: {len(raw)} bytes exceeds the 10 MB write limit")
        result = await self._request({
            "type": "write_file",
            "path": path,
            "content_b64": base64.b64encode(raw).decode(),
            "append": append,
        })
        if not result.get("ok", True):
            raise ProtocolError(f"{path}: {result.get('error', 'write failed')}")
        return int(result.get("size", len(raw)))

    async def http(self, url: str, method: str = "POST",
                   headers: dict[str, str] | None = None,
                   body: bytes | str | None = None) -> dict[str, Any]:
        frame: dict[str, Any] = {"type": "http", "url": url, "method": method}
        if headers:
            frame["headers"] = headers
        if body is not None:
            raw = body.encode() if isinstance(body, str) else body
            frame["body_b64"] = base64.b64encode(raw).decode()
        return await self._request(frame)

    # -- one-way messages (no reply, no slot) ------------------------------
    async def log(self, text: str) -> None:
        await self.ws.send(json.dumps({"type": "log", "text": text[:4000]}))

    async def usage(self, model: str, input_tokens: int,
                    output_tokens: int, cache_read_tokens: int = 0) -> None:
        """Token accounting. Stage 2 cost is computed from these frames."""
        await self.ws.send(json.dumps({
            "type": "usage",
            "model": model,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cache_read_tokens": int(cache_read_tokens),
        }))

    async def wait_cancelled(self) -> None:
        """Resolve when the evaluator sends `cancel`."""
        await self.cancelled.wait()

    async def done(self, final_message: str) -> None:
        await self.ws.send(json.dumps({"type": "done", "final_message": final_message}))

    async def error(self, message: str) -> None:
        await self.ws.send(json.dumps({"type": "error", "message": message[:4000]}))


# --------------------------------------------------------------------------
# Task inspection. The protocol carries no deliverable list, so paths and the
# discipline are recovered from the instruction text. This is a heuristic and
# should be validated on the dev set before it is trusted.
# --------------------------------------------------------------------------

# Deliverable extensions seen in eval/dev_set.yaml and docs/artifacts.md:
# md/txt/csv/json/yaml reports, xlsx schedules, docx memos, pdf sheets, dxf/ifc
# models, and the two the first version missed: `submission.zip` packages and
# `solution.py` scripts. A directory deliverable is written with a trailing "/".
_DELIVERABLE_EXT = (r"md|txt|csv|json|ya?ml|xlsx|docx|pptx|pdf|dxf|dwg|ifc"
                    r"|zip|py|html?|xml")
_PATH_RE = re.compile(
    r"/[^\s`'\"]*(?:\.(?:" + _DELIVERABLE_EXT + r")\b|/)"
    r"|[\w.\-]+\.(?:" + _DELIVERABLE_EXT + r")\b",
    re.IGNORECASE,
)

_DISCIPLINES = ("structural", "civil", "electrical", "mechanical")


def deliverables_of(task: Task) -> list[str]:
    """Paths the prompt asks for.

    Absolute paths stay absolute. The previous version ran `.strip("./")`, which
    ate the leading slash, so `/filesystem/.../submission.zip` was read as a path
    relative to the workdir and never resolved.
    """
    seen: list[str] = []
    for match in _PATH_RE.finditer(task.instruction):
        path = match.group(0).rstrip(",.;:)")
        if path.startswith("./"):
            path = path[2:]
        if path and path not in seen:
            seen.append(path)
    return seen


def discipline_of(task: Task) -> str:
    text = task.instruction.lower()
    for name in _DISCIPLINES:
        if name in text:
            return name
    aliases = {
        "mechanical": ("hvac", "pump", "piping", "cooling", "chiller", "duct"),
        "electrical": ("circuit", "feeder", "voltage", "ampacity", "switchboard"),
        "civil": ("grading", "stormwater", "earthwork", "settlement", "footing"),
        "structural": ("beam", "joist", "deflection", "shear wall", "roof deck"),
    }
    for name, words in aliases.items():
        if any(word in text for word in words):
            return name
    return "unknown"
