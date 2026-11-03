"""extra_body supplied by a caller must survive the kimi-k thinking default."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from mobile_world.agents.base import BaseAgent


class _Agent(BaseAgent):
    def __init__(self):
        # Bypass BaseAgent.__init__: only the client is needed here.
        self.openai_client = MagicMock()

    def predict(self, *a, **k):  # abstract in BaseAgent
        raise NotImplementedError


def _response(text="ok"):
    msg = SimpleNamespace(content=text, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)


def _sent_kwargs(agent):
    return agent.openai_client.chat.completions.create.call_args.kwargs


def test_caller_extra_body_is_preserved_for_kimi():
    agent = _Agent()
    agent.openai_client.chat.completions.create.return_value = _response()
    agent._log_openai_usage = MagicMock()

    routing = {"provider": {"only": ["some-provider"], "allow_fallbacks": False}}
    agent.openai_chat_completions_create(
        model="moonshotai/kimi-k2.5", messages=[], extra_body=routing
    )

    sent = _sent_kwargs(agent)["extra_body"]
    assert sent["provider"] == routing["provider"], "caller's routing was dropped"
    assert sent["enable_thinking"] is True, "thinking default was lost"


def test_caller_can_disable_thinking():
    agent = _Agent()
    agent.openai_client.chat.completions.create.return_value = _response()
    agent._log_openai_usage = MagicMock()

    agent.openai_chat_completions_create(
        model="moonshotai/kimi-k2.5", messages=[], extra_body={"enable_thinking": False}
    )
    assert _sent_kwargs(agent)["extra_body"]["enable_thinking"] is False


def test_no_extra_body_still_enables_thinking():
    agent = _Agent()
    agent.openai_client.chat.completions.create.return_value = _response()
    agent._log_openai_usage = MagicMock()

    agent.openai_chat_completions_create(model="moonshotai/kimi-k2.5", messages=[])
    assert _sent_kwargs(agent)["extra_body"] == {"enable_thinking": True}
