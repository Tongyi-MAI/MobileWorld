"""A None completion must not crash, and must not burn the retry budget."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from mobile_world.agents.base import BaseAgent


class _Agent(BaseAgent):
    def __init__(self):
        self.openai_client = MagicMock()
        self._log_openai_usage = MagicMock()

    def predict(self, *a, **k):
        raise NotImplementedError


def _truncated(reasoning=None):
    msg = SimpleNamespace(content=None, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="length")], usage=None)


def test_none_content_returns_empty_without_retrying():
    agent = _Agent()
    agent.openai_client.chat.completions.create.return_value = _truncated()

    out = agent.openai_chat_completions_create(model="some-model", messages=[], retry_times=3)

    assert out == ""
    # Previously .strip() raised, was caught as an API error, and retried
    # three times for a request that cannot succeed on retry.
    assert agent.openai_client.chat.completions.create.call_count == 1


def test_none_content_keeps_reasoning_for_kimi():
    agent = _Agent()
    agent.openai_client.chat.completions.create.return_value = _truncated(reasoning="thinking...")

    out = agent.openai_chat_completions_create(model="moonshotai/kimi-k2.5", messages=[])

    assert out == "<think>thinking...</think>\n"
