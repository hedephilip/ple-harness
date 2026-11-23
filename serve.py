"""WebSocket entrypoint.

Binds 0.0.0.0:$PORT with no keepalive pings — the protocol spec requires
`ping_interval=None`, because an evaluator that pauses reading (waiting on the
8-request limit) would otherwise trip a ping timeout and drop the connection.

Every task ends with exactly one `done` or `error`. A run that times out or
crashes without either frame scores 0.0, and loses the work already written to
the container.
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
from protocol import MAX_FRAME_BYTES, Task, TaskCancelled, TaskChannel
from telemetry import Telemetry

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
LOG = logging.getLogger("ple-harness")

MAX_FIX_ROUNDS = int(os.environ.get("MAX_FIX_ROUNDS", "3"))


async def handle(websocket, *_args) -> None:
    session = "unknown"
    channel: TaskChannel | None = None
    try:
        task = Task.from_frame(json.loads(await websocket.recv()))
        session = task.session or "unknown"
        LOG.info("task %s timeout=%s mcp_servers=%d", session,
                 task.agent_timeout_sec, len(task.mcp_servers))

        channel = TaskChannel(websocket, task)
        await channel.start()

        enrich = os.environ.get("PLE_GATE_MODE", "on").strip().lower() != "off"
        descent = os.environ.get("PLE_OBJECTIVE_DESCENT", "on").strip().lower() != "off"
        harness = GatedHarness(Client(), Playbook(), Telemetry(),
                               max_fix_rounds=MAX_FIX_ROUNDS, enforce=enrich,
                               optimize_descent=descent)
        passed, message = await harness.run(channel, task)
        LOG.info("task %s passed=%s", session, passed)
        await channel.done(message)

    except TaskCancelled:
        try:
            if channel is not None:
                await channel.done("Time limit reached; deliverables already written.")
        except Exception:
            pass
    except Exception as exc:
        LOG.exception("task %s failed", session)
        frame = json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        try:
            await websocket.send(frame)
        except Exception:
            pass
    finally:
        if channel is not None:
            await channel.close()


async def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    assert_registered()
    LOG.info("gates per discipline: %s",
             {name: len(fns) for name, fns in gate_index().items()})
    async with websockets.serve(handle, "0.0.0.0", port,
                                max_size=MAX_FRAME_BYTES, ping_interval=None):
        LOG.info("listening on 0.0.0.0:%s model_api=%s", port,
                 os.environ.get("MODEL_API"))
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
