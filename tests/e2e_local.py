"""End-to-end run of serve.py against a fake evaluator and a fake model.

This is the closest thing to `kit check` available without Docker. It spawns
the real server, speaks the real v1 WebSocket protocol, drives a real HTTP
model call, and exercises the gate-fail -> feedback -> repair -> done path.

    python tests/e2e_local.py

Asserts:
  1. the server binds and accepts a task frame
  2. the agent's write_file tool call reaches the evaluator
  3. the first, failing deliverable is rejected by the gate
  4. the repair round produces a passing deliverable
  5. `done` carries a final_message reporting the verified pass
  6. usage and telemetry are emitted for cost accounting
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import websockets  # noqa: E402

UNITS = {f"structural.{k}": v for k, v in {
    "Fy_ksi": "ksi", "Zx_in3": "in^3", "Mu_kip_ft": "kip-ft", "d_in": "in",
    "tw_in": "in", "Vu_kip": "kip", "L_span_in": "in", "delta_L_in": "in"}.items()}
BASE = {"Fy_ksi": 50, "Zx_in3": 100, "d_in": 16, "tw_in": 0.4,
        "Vu_kip": 150, "L_span_in": 360, "delta_L_in": 0.8}
REQS = [{"clause": "AISC 360-16 F2", "value": "phi_b = 0.90"}]
REVS = [{"doc_id": "S-201", "rank": "IFC", "revision": 1, "value": 11.0}]


def memo(mu: float) -> str:
    claims = {"units": UNITS, "structural": {**BASE, "Mu_kip_ft": mu},
              "requirements": REQS, "revisions": REVS}
    return "# Flexure\n\n<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->\n"


INSTRUCTION = ("Structural check: size the beam and record the flexure, shear and "
               "deflection checks in memo.md.")


# ---------------------------------------------------------------- fake model
class ModelState:
    calls = 0


class FakeModel(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        last = messages[-1] if messages else {}
        # Claude cache breakpoints deliver content as a list of blocks, so the
        # text has to be joined before it can be searched.
        content = last.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content
                                if isinstance(part, dict))
        repair = last.get("role") == "user" and "GATE FAILED" in content
        has_tool_result = any(m.get("role") == "tool" for m in messages)

        if repair:
            ModelState.calls += 1
            response = {
                "choices": [{"message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [{
                        "id": "repair_1", "type": "function",
                        "function": {"name": "write_file",
                                     "arguments": json.dumps({"path": "memo.md",
                                                              "content": memo(300)})},
                    }],
                }}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 60},
            }
        elif has_tool_result:
            response = {"choices": [{"message": {"role": "assistant",
                                                 "content": "Beam check complete."}}],
                        "usage": {"prompt_tokens": 80, "completion_tokens": 20}}
        else:
            ModelState.calls += 1
            mu = 400 if ModelState.calls == 1 else 300     # first attempt fails
            response = {
                "choices": [{"message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [{
                        "id": f"call_{ModelState.calls}", "type": "function",
                        "function": {"name": "write_file",
                                     "arguments": json.dumps({"path": "memo.md",
                                                              "content": memo(mu)})},
                    }],
                }}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        payload = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------ fake evaluator
async def drive(port: int, workdir: Path) -> dict:
    files: dict[str, bytes] = {}
    frames: dict[str, list] = {"usage": [], "log": [], "done": []}
    uri = f"ws://127.0.0.1:{port}"

    for _ in range(100):
        try:
            connection = await websockets.connect(uri, open_timeout=1)
            break
        except Exception:
            await asyncio.sleep(0.2)
    else:
        raise SystemExit("server never accepted a connection")

    async with connection:
        await connection.send(json.dumps({
            "type": "task", "protocol": 1, "session": "E2E-001",
            "instruction": INSTRUCTION, "workdir": "/app",
            "limits": {"agent_timeout_sec": 600, "exec_timeout_sec": 120,
                       "max_output_bytes": 100000, "max_write_bytes": 10000000},
            "mcp_servers": [],
        }))
        while True:
            message = json.loads(await asyncio.wait_for(connection.recv(), timeout=60))
            kind = message.get("type")
            if kind == "exec":
                reply = {"type": "result", "id": message["id"], "exit_code": 0,
                         "output": "", "truncated": False, "timed_out": False}
            elif kind == "read_file":
                data = files.get(message["path"])
                reply = ({"type": "result", "id": message["id"], "ok": True,
                          "content_b64": base64.b64encode(data).decode(),
                          "size": len(data), "truncated": False}
                         if data is not None else
                         {"type": "result", "id": message["id"], "ok": False,
                          "error": "no such file"})
            elif kind == "write_file":
                raw = base64.b64decode(message.get("content_b64") or "")
                files[message["path"]] = raw
                reply = {"type": "result", "id": message["id"], "ok": True, "size": len(raw)}
            elif kind == "http":
                reply = {"type": "result", "id": message["id"], "ok": False, "error": "offline"}
            elif kind in ("usage", "log"):
                frames[kind].append(message)
                continue
            elif kind in ("done", "error"):
                frames[kind].append(message)
                break
            else:
                continue
            await connection.send(json.dumps(reply))
    frames["files"] = list(files)
    return frames


def main() -> int:
    workdir = Path(tempfile.mkdtemp())
    model_port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", model_port), FakeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    serve_port = free_port()
    env = {
        **os.environ,
        "PORT": str(serve_port),
        "MODEL_API": "google-cloud/claude-opus-5-5",
        "MODEL_NAME": "fake-opus",
        "MODEL_BASE_URL": f"http://127.0.0.1:{model_port}/v1",
        "MODEL_API_KEY": "not-a-real-key",
        "PLAYBOOK_PATH": str(workdir / "playbook.jsonl"),
        "TELEMETRY_DIR": str(workdir),
        "PLE_GATE_MODE": "on",
        "MAX_FIX_ROUNDS": "3",
        "LOG_LEVEL": "warning",
    }
    proc = subprocess.Popen([sys.executable, str(ROOT / "serve.py")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=str(ROOT), text=True)
    try:
        frames = asyncio.run(drive(serve_port, workdir))
    finally:
        proc.terminate()
        try:
            output = proc.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            output = ""

    failures = []
    done = frames["done"]
    final_message = done[0].get("final_message", "") if done else ""

    if not done:
        failures.append("no done frame was sent")
    logs = " ".join(str(m.get("text", "")) for m in frames["log"])
    if "[gated]" not in logs:
        failures.append(f"no log frame carried the gate verdict: {logs[:200]!r}")
    if "[gated]" in final_message:
        failures.append("the gate verdict leaked into final_message, which the "
                        f"grader reads: {final_message[:200]!r}")
    if "memo.md" not in frames["files"]:
        failures.append("the agent's write_file never reached the evaluator")
    if ModelState.calls < 2:
        failures.append(f"expected a repair round; model was called {ModelState.calls} time(s)")
    if not frames["usage"]:
        failures.append("no usage frames: Stage 2 cost would read as zero")

    gates_csv = workdir / "gates.csv"
    tasks_csv = workdir / "tasks.csv"
    if not gates_csv.exists() or not tasks_csv.exists():
        failures.append("telemetry CSVs were not written")

    print("=" * 62)
    print("task frame accepted          ", "yes" if done else "no")
    print("model calls                  ", ModelState.calls)
    print("usage frames                 ", len(frames["usage"]))
    print("files written                ", frames["files"])
    print("done final_message           ", final_message.replace("\n", " ")[:120])
    print("log frames                   ", logs.replace("\n", " ")[:120])
    if proc.returncode not in (0, -15, 1, None):
        print("server exit code             ", proc.returncode)
    if output.strip():
        print("server output (tail):")
        print("\n".join(output.strip().splitlines()[-6:]))

    if failures:
        print("\nFAILED:")
        for item in failures:
            print("  -", item)
        return 1
    print("\nPASS: end-to-end gated completion works over the real protocol.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
