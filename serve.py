"""WebSocket entrypoint.

Binds 0.0.0.0:$PORT (must happen within 120 s of container start), accepts
one task per connection, runs the gated loop, and ends with a `done` frame.

A task that dies still has to send `done` — a timed-out or crashed run
without a `done` or `error` frame scores 0.0, which is the worst possible
outcome and is entirely avoidable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import websockets

from gates import assert_registered, gate_index
from harness import GatedHarness
from llm import Client
from playbook import Playbook
from protocol import TaskChannel, frame_task
from telemetry import Telemetry

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
LOG = logging.getLogger("ple-harness")

MAX_FIX_ROUNDS = int(os.environ.get("MAX_FIX_ROUNDS", "3"))


async def handle(websocket, *_args) -> None:
    task_id = "unknown"
    channel: TaskChannel | None = None
    try:
        raw = await websocket.recv()
        task = frame_task(raw)
        task_id = str(task.get("task_id") or task.get("id") or "unknown")

        channel = TaskChannel(websocket, task)
        await channel.start()

        client = Client()
        playbook = Playbook()
        telemetry = Telemetry()
        enforce = os.environ.get("PLE_GATE_MODE", "on").strip().lower() != "off"
        harness = GatedHarness(client, playbook, telemetry,
                               max_fix_rounds=MAX_FIX_ROUNDS, enforce=enforce)

        LOG.info("task %s discipline-gates=%s", task_id, len(assert_index()))
        passed, summary = await harness.run(channel, task)
        LOG.info("task %s passed=%s ", task_id, passed)
        await channel.done(summary)
    except Exception as exc:
        LOG.exception("task %s failed: %s", task_id, exc)
        frame = json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        try:
            await websocket.send(frame)
            await websocket.send(json.dumps({"type": "done",
                                             "summary": "harness error; see error frame"}))
        except Exception:
            pass
    finally:
        if channel is not None:
            await channel.close()


def assert_index() -> dict:
    assert_registered()
    return gate_index()


async def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    index = assert_index()
    LOG.info("gate index: %s", {k: len(v) for k, v in index.items()})
    async with websockets.serve(handle, "0.0.0.0", port, max_size=16 * 1024 * 1024):
        LOG.info("listening on 0.0.0.0:%s model_api=%s", port, os.environ.get("MODEL_API"))
        await asyncio.Future()          # run forever


if __name__ == "__main__":
    asyncio.run(main())
