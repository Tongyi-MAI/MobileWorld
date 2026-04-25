"""Tests for ``mobile_world.agents.utils.action_translation.args_to_action_dict``.

The function denormalises model-emitted [0, 999] coordinates into pixel coords
and produces a flat dict shaped like the keys ``JSONAction`` accepts. These
tests pin every action variant the MAI-UI prompt enumerates and a few
malformed inputs.
"""

from __future__ import annotations

import pytest

from mobile_world.agents.utils.action_translation import args_to_action_dict
from mobile_world.runtime.utils.models import (
    ANSWER,
    ASK_USER,
    CLICK,
    DOUBLE_TAP,
    DRAG,
    FINISHED,
    INPUT_TEXT,
    KEYBOARD_ENTER,
    LONG_PRESS,
    NAVIGATE_BACK,
    NAVIGATE_HOME,
    OPEN_APP,
    SCROLL,
    UNKNOWN,
    WAIT,
    JSONAction,
)

W, H = 1000, 2000


def test_click() -> None:
    d = args_to_action_dict({"action": "click", "coordinate": [500, 999]}, W, H)
    assert d == {"action_type": CLICK, "x": 500, "y": 2000}


def test_long_press() -> None:
    d = args_to_action_dict({"action": "long_press", "coordinate": [999, 0]}, W, H)
    assert d["action_type"] == LONG_PRESS
    assert d["x"] == 1000 and d["y"] == 0


def test_double_click() -> None:
    d = args_to_action_dict({"action": "double_click", "coordinate": [100, 200]}, W, H)
    assert d["action_type"] == DOUBLE_TAP


def test_swipe_reverses_vertical_direction() -> None:
    d = args_to_action_dict(
        {"action": "swipe", "direction": "up", "coordinate": [500, 500]}, W, H,
    )
    # Content "up" → finger "down".
    assert d["action_type"] == SCROLL
    assert d["direction"] == "down"
    assert "x" in d and "y" in d


def test_swipe_left_unchanged() -> None:
    d = args_to_action_dict({"action": "swipe", "direction": "left"}, W, H)
    assert d == {"action_type": SCROLL, "direction": "left"}


def test_swipe_invalid_direction_is_unknown() -> None:
    d = args_to_action_dict({"action": "swipe", "direction": "diagonal"}, W, H)
    assert d["action_type"] == UNKNOWN


def test_drag_corners() -> None:
    d = args_to_action_dict(
        {
            "action": "drag",
            "start_coordinate": [0, 0],
            "end_coordinate": [999, 999],
        },
        W,
        H,
    )
    assert d == {
        "action_type": DRAG,
        "start_x": 0, "start_y": 0,
        "end_x": 1000, "end_y": 2000,
    }


def test_type() -> None:
    d = args_to_action_dict({"action": "type", "text": "hello"}, W, H)
    assert d == {"action_type": INPUT_TEXT, "text": "hello"}


def test_open_app() -> None:
    d = args_to_action_dict({"action": "open", "text": "Chrome"}, W, H)
    assert d == {"action_type": OPEN_APP, "app_name": "Chrome"}


@pytest.mark.parametrize(
    ("button", "expected"),
    [
        ("back", NAVIGATE_BACK),
        ("home", NAVIGATE_HOME),
        ("enter", KEYBOARD_ENTER),
    ],
)
def test_system_button(button: str, expected: str) -> None:
    d = args_to_action_dict({"action": "system_button", "button": button}, W, H)
    assert d == {"action_type": expected}


def test_system_button_menu_is_unknown() -> None:
    d = args_to_action_dict({"action": "system_button", "button": "menu"}, W, H)
    assert d["action_type"] == UNKNOWN


def test_terminate_success() -> None:
    d = args_to_action_dict({"action": "terminate", "status": "success"}, W, H)
    assert d == {"action_type": FINISHED, "text": "success"}


def test_answer() -> None:
    d = args_to_action_dict({"action": "answer", "text": "42"}, W, H)
    assert d == {"action_type": ANSWER, "text": "42"}


def test_ask_user() -> None:
    d = args_to_action_dict({"action": "ask_user", "text": "Which app?"}, W, H)
    assert d == {"action_type": ASK_USER, "text": "Which app?"}


def test_wait() -> None:
    d = args_to_action_dict({"action": "wait"}, W, H)
    assert d == {"action_type": WAIT}


def test_unknown_action() -> None:
    d = args_to_action_dict({"action": "frobnicate"}, W, H)
    assert d["action_type"] == UNKNOWN


def test_bbox_coordinate_uses_centre() -> None:
    d = args_to_action_dict(
        {"action": "click", "coordinate": [0, 0, 999, 999]}, W, H,
    )
    # Centre of the bbox at (499.5, 499.5) → (500, 1000) px.
    assert d["x"] == 500
    assert d["y"] == 1000


def test_invalid_coordinate_length_is_unknown() -> None:
    d = args_to_action_dict({"action": "click", "coordinate": [1, 2, 3]}, W, H)
    assert d["action_type"] == UNKNOWN


def test_result_is_jsonaction_constructible() -> None:
    """The dict shape must be valid input for ``JSONAction(**d)``."""
    for args in [
        {"action": "click", "coordinate": [500, 500]},
        {"action": "swipe", "direction": "down"},
        {"action": "drag", "start_coordinate": [0, 0], "end_coordinate": [999, 999]},
        {"action": "type", "text": "hi"},
        {"action": "open", "text": "Chrome"},
        {"action": "system_button", "button": "back"},
        {"action": "terminate", "status": "success"},
        {"action": "answer", "text": "ok"},
        {"action": "ask_user", "text": "?"},
        {"action": "wait"},
    ]:
        d = args_to_action_dict(args, W, H)
        # Should not raise.
        JSONAction(**d)
