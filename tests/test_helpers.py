"""Tests for ``mobile_world.agents.utils.helpers``."""

from __future__ import annotations

from mobile_world.agents.utils.helpers import reverse_swipe_direction


def test_reverse_up() -> None:
    assert reverse_swipe_direction("up") == "down"


def test_reverse_down() -> None:
    assert reverse_swipe_direction("down") == "up"


def test_left_unchanged() -> None:
    assert reverse_swipe_direction("left") == "left"


def test_right_unchanged() -> None:
    assert reverse_swipe_direction("right") == "right"


def test_unknown_passes_through() -> None:
    # Lenient: callers decide whether to treat as malformed (e.g. UNKNOWN).
    assert reverse_swipe_direction("diagonal") == "diagonal"
    assert reverse_swipe_direction("") == ""
