"""One OpenAI-compatible client, plus per-provider capability flags.

All eight sponsored models are reachable through an OpenAI-compatible
endpoint (`MODEL_BASE_URL` / `OPENAI_BASE_URL`). Writing three adapters
would have produced three code paths to debug for no functional gain, so
provider differences live here as flags instead:

  - `tool_stream`      GLM needs ``extra_body={"tool_stream": true}`` or it
                       silently returns no tool_calls at all. This is the
                       single most expensive flag to get wrong.
  - `strict_tool_args` Always parse ``arguments`` as a JSON string. Never
                       assume a dict; providers differ.

Stdlib only — no `openai` package, no `requests`. That keeps the install
image small against the 2 GiB /opt/harness cap.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    tool_stream: bool = False
    # The Overview warns that open-weight models have lower context limits, so
    # the output ceiling follows the profile instead of being one global number.
    default_max_tokens: int = 32000
    # None means "do not send the field". docs/models.md: Claude Opus 5.5
    # returns 400 if temperature, top_p, top_k or a thinking budget is set, so
    # the field must be absent rather than defaulted.
    temperature: float | None = None
    notes: str = ""


def profile_for(model_api: str) -> ProviderProfile:
    key = (model_api or "").lower()
    if "glm" in key:
        return ProviderProfile("glm", tool_stream=True,
                               notes="extra_body.tool_stream is mandatory")
    if "gemini" in key:
        return ProviderProfile("gemini", notes="OpenAI-compatible shim")
    if "claude" in key:
        return ProviderProfile("claude", notes="OpenAI-compatible shim over native endpoint")
    if "gemma" in key or "gpt-oss" in key or "llama" in key:
        return ProviderProfile("open-weight", default_max_tokens=4096,
                            notes="open weights; lower context limits")
    return ProviderProfile("openai-compatible")


@dataclass
class Completion:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls
        return message


class LLMError(RuntimeError):
    pass


class Client:
    def __init__(self, model_api: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, model_name: str | None = None,
                 timeout: float = 600.0) -> None:
        self.model_api = model_api or os.environ.get("MODEL_API", "")
        self.base_url = (base_url or os.environ.get("MODEL_BASE_URL")
                         or os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
        self.api_key = (api_key or os.environ.get("MODEL_API_KEY")
                        or os.environ.get("OPENAI_API_KEY") or "")
        self.model_name = model_name or os.environ.get("MODEL_NAME") or self.model_api
        self.profile = profile_for(self.model_api)
        self.timeout = timeout

    def _payload(self, messages: list[dict], tools: list[dict] | None,
                 max_tokens: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._marked(messages),
            "max_tokens": max_tokens,
        }
        if self.profile.temperature is not None:
            body["temperature"] = self.profile.temperature
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self.profile.tool_stream:
            body["extra_body"] = {"tool_stream": True}
            body["tool_stream"] = True     # some gateways read the top-level key
        return body

    def _marked(self, messages: list[dict]) -> list[dict]:
        """Put Claude's cache breakpoints where they actually help.

        Claude only caches at explicit `cache_control` points, so without these
        every turn re-processes the whole conversation — expensive and slow on a
        six-hour task. Mark the system prompt and the newest conversational
        message; tool messages are left as plain strings because their content
        must stay a string on the OpenAI-compatible shim.
        """
        if self.profile.name != "claude" or not messages:
            return messages
        cache = {"type": "ephemeral"}
        out = [dict(m) for m in messages]

        def mark(index: int) -> None:
            message = out[index]
            content = message.get("content")
            if message.get("role") == "tool" or not isinstance(content, str) or not content:
                return
            message["content"] = [{"type": "text", "text": content,
                                   "cache_control": cache}]

        mark(0)
        for index in range(len(out) - 1, 0, -1):
            if out[index].get("role") in ("user", "assistant"):
                mark(index)
                break
        return out

    def complete(self, messages: list[dict], tools: list[dict] | None = None,
                 max_tokens: int | None = None, retries: int = 3) -> Completion:
        if not self.base_url:
            raise LLMError("MODEL_BASE_URL is not set")
        url = f"{self.base_url}/chat/completions"
        if max_tokens is None:
            max_tokens = self.profile.default_max_tokens
        payload = json.dumps(self._payload(messages, tools, max_tokens)).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last: Exception | None = None
        for attempt in range(retries + 1):
            request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode())
                choice = (data.get("choices") or [{}])[0].get("message") or {}
                calls = []
                for call in choice.get("tool_calls") or []:
                    function = call.get("function") or {}
                    calls.append({
                        "id": call.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": function.get("name", ""),
                            "arguments": self._coerce_arguments(function.get("arguments")),
                        },
                    })
                usage = data.get("usage") or {}
                return Completion(
                    content=choice.get("content") or "",
                    tool_calls=calls,
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    raw=data,
                )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:400]
                last = LLMError(f"HTTP {exc.code}: {body}")
                if exc.code in (400, 401, 403, 404):   # not transient
                    break
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and retry_after.isdigit():
                    time.sleep(min(int(retry_after), 30))
                    continue
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
            time.sleep(min(2 ** attempt, 8))
        raise LLMError(str(last))

    @staticmethod
    def _coerce_arguments(arguments: Any) -> str:
        """Always hand back a JSON *string*; the loop parses it."""
        if arguments is None:
            return "{}"
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments)

    @staticmethod
    def parse_arguments(call: dict[str, Any]) -> dict[str, Any]:
        raw = (call.get("function") or {}).get("arguments") or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
