"""Tests for ``mobile_world.agents.utils.message_utils.hide_history_images``."""

from __future__ import annotations

from mobile_world.agents.utils.message_utils import hide_history_images


def _img(label: str) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{label}"}}
        ],
    }


def _text(role: str, text: str) -> dict:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def test_keeps_recent_images() -> None:
    msgs = [
        _text("system", "sys"),
        _text("user", "instruction"),
        _img("a"),
        _text("assistant", "r1"),
        _img("b"),
        _text("assistant", "r2"),
        _img("c"),
    ]
    out = hide_history_images(msgs, retention=2)
    # Should drop the oldest image ("a") but keep "b" and "c".
    image_urls = [
        m["content"][0]["image_url"]["url"]
        for m in out
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and m["content"]
        and isinstance(m["content"][0], dict)
        and m["content"][0].get("type") == "image_url"
    ]
    assert image_urls == [
        "data:image/png;base64,b",
        "data:image/png;base64,c",
    ]


def test_does_not_mutate_input() -> None:
    msgs = [_img("a"), _img("b"), _img("c")]
    original = [m["content"][0]["image_url"]["url"] for m in msgs]
    _ = hide_history_images(msgs, retention=1)
    after = [m["content"][0]["image_url"]["url"] for m in msgs]
    # Caller's list should be untouched (deepcopy semantics).
    assert original == after


def test_zero_retention_drops_all_images() -> None:
    msgs = [_text("system", "sys"), _img("a"), _img("b")]
    out = hide_history_images(msgs, retention=0)
    assert all(
        m["content"][0].get("type") != "image_url"
        for m in out
        if m.get("role") == "user" and isinstance(m.get("content"), list)
    )


def test_text_only_user_turns_are_preserved() -> None:
    msgs = [
        _text("system", "sys"),
        _text("user", "instruction"),  # text-only — must survive
        _img("a"),
        _text("user", "tool result"),  # text-only — must survive
        _img("b"),
    ]
    out = hide_history_images(msgs, retention=1)
    user_text_count = sum(
        1
        for m in out
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and m["content"]
        and isinstance(m["content"][0], dict)
        and m["content"][0].get("type") == "text"
    )
    assert user_text_count == 2


def test_high_retention_keeps_all() -> None:
    msgs = [_img("a"), _img("b")]
    out = hide_history_images(msgs, retention=99)
    assert len(out) == 2
