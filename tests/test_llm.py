"""Request shape against docs/models.md.

The kit's stub answers any body, so a malformed request passes every local
check and fails in evaluation. These tests assert the shape instead:
`google-cloud/claude-opus-5-5` returns 400 if `temperature`, `top_p`, `top_k` or
a thinking budget is present, and Claude only caches at explicit breakpoints.
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm import Client                      # noqa: E402

CLAUDE = "google-cloud/claude-opus-5-5"
GEMINI = "google-cloud/gemini-4-argon"


def client(model_api: str) -> Client:
    return Client(model_api=model_api, base_url="http://proxy/v1", api_key="k")


class TestRequestShape(unittest.TestCase):
    def test_claude_never_sends_temperature(self):
        body = client(CLAUDE)._payload([{"role": "user", "content": "hi"}], None, 32000)
        for forbidden in ("temperature", "top_p", "top_k", "budget_tokens"):
            self.assertNotIn(forbidden, body, f"{forbidden} would 400 on Opus 5.5")

    def test_no_profile_sends_temperature_by_default(self):
        for model in (CLAUDE, GEMINI, "google-cloud/glm-5.2",
                      "google-cloud/gpt-oss-120b", "google-cloud/gemma-4-26b"):
            with self.subTest(model=model):
                body = client(model)._payload([{"role": "user", "content": "x"}], None, 8000)
                self.assertNotIn("temperature", body)

    def test_claude_marks_system_prompt_for_caching(self):
        body = client(CLAUDE)._payload(
            [{"role": "system", "content": "sys"},
             {"role": "user", "content": "hi"}], None, 32000)
        system = body["messages"][0]["content"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})

    def test_claude_marks_the_newest_conversational_message(self):
        body = client(CLAUDE)._payload(
            [{"role": "system", "content": "sys"},
             {"role": "assistant", "content": "a"},
             {"role": "user", "content": "newest"}], None, 32000)
        self.assertIsInstance(body["messages"][-1]["content"], list)

    def test_tool_messages_are_left_as_strings(self):
        body = client(CLAUDE)._payload(
            [{"role": "system", "content": "sys"},
             {"role": "user", "content": "go"},
             {"role": "assistant", "content": "calling"},
             {"role": "tool", "content": "result"}], None, 32000)
        self.assertIsInstance(body["messages"][-1]["content"], str)

    def test_other_models_are_not_marked(self):
        body = client(GEMINI)._payload(
            [{"role": "system", "content": "sys"},
             {"role": "user", "content": "hi"}], None, 32000)
        self.assertIsInstance(body["messages"][0]["content"], str)

    def test_max_tokens_follows_the_profile(self):
        # models.md recommends 32000 for Opus 5.5; the Overview warns that
        # open-weight models have lower context limits, so they get 4096.
        self.assertIsNone(inspect.signature(Client.complete).parameters["max_tokens"].default)
        self.assertEqual(client(CLAUDE).profile.default_max_tokens, 32000)
        self.assertEqual(client("google-cloud/llama-4-maverick").profile.default_max_tokens, 4096)
        self.assertEqual(client("google-cloud/gpt-oss-120b").profile.default_max_tokens, 4096)

    def test_tool_choice_is_auto(self):
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        body = client(CLAUDE)._payload([{"role": "user", "content": "x"}], tools, 32000)
        self.assertEqual(body["tool_choice"], "auto")

    def test_arguments_always_coerced_to_a_string(self):
        self.assertEqual(Client._coerce_arguments({"a": 1}), json.dumps({"a": 1}))
        self.assertEqual(Client._coerce_arguments("{}"), "{}")
        self.assertEqual(Client._coerce_arguments(None), "{}")


if __name__ == "__main__":
    unittest.main()
