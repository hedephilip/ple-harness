"""Gateway responses the harness must not mistake for a finished turn.

A 200 response can still carry an error envelope or no choices at all. Treating
that as an empty completion ends the task as if the model had answered, so the
run is graded on work it never did. `retries=0` keeps these tests fast.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm import Client, LLMError        # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def client() -> Client:
    return Client(model_api="google-cloud/llama-4-maverick",
                  base_url="http://proxy/v1", api_key="k")


class TestResponseValidation(unittest.TestCase):
    def _call_with(self, payload: dict):
        raw = json.dumps(payload).encode()
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(raw)):
            return client().complete([{"role": "user", "content": "go"}],
                                     tools=None, retries=0)

    def test_error_envelope_is_raised(self):
        with self.assertRaises(LLMError) as ctx:
            self._call_with({"error": {"message": "upstream overloaded"}})
        self.assertIn("provider error", str(ctx.exception))

    def test_missing_choices_is_raised(self):
        with self.assertRaises(LLMError):
            self._call_with({"choices": []})

    def test_empty_message_is_raised(self):
        with self.assertRaises(LLMError):
            self._call_with({"choices": [{"message": {"content": ""},
                                          "finish_reason": "stop"}]})

    def test_a_real_answer_still_parses(self):
        result = self._call_with({
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        })
        self.assertEqual(result.content, "hello")
        self.assertEqual(result.prompt_tokens, 11)


if __name__ == "__main__":
    unittest.main()
