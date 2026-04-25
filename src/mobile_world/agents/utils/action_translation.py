"""Translate MAI-UI tool-call arguments into a flat action dict.

The MAI-UI agent emits actions inside ``<tool_call>`` blocks with coordinates
normalised to ``[0, SCALE_FACTOR]``. This module turns those into a flat dict
shaped like the keys ``JSONAction`` accepts, so callers can either construct
``JSONAction(**d)`` (the runtime path) or dispatch the dict directly to a
remote env executor (the RL/training path).
"""

from __future__ import annotations

from typing import Any

from mobile_world.agents.utils.helpers import reverse_swipe_direction
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
    SCALE_FACTOR,
    SCROLL,
    UNKNOWN,
    WAIT,
)

_SCROLL_DIRECTIONS = ("left", "right", "down", "up")


def _denorm_xy(coord: list[float], image_width: int, image_height: int) -> tuple[int, int]:
    """Convert a 0..SCALE_FACTOR coordinate (point or bbox) to pixel coords."""
    if len(coord) == 4:
        x1, y1, x2, y2 = coord
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    elif len(coord) == 2:
        cx, cy = float(coord[0]), float(coord[1])
    else:
        raise ValueError(f"Invalid coordinate length: {len(coord)}")
    return (
        int(cx / SCALE_FACTOR * image_width),
        int(cy / SCALE_FACTOR * image_height),
    )


def args_to_action_dict(
    args: dict[str, Any],
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Translate raw MAI-UI tool-call ``arguments`` into a flat action dict.

    ``args`` is the JSON object the model emitted inside ``<tool_call>``
    (``{"action": "click", "coordinate": [...], ...}``). Coordinates are
    expected to be normalised to ``[0, SCALE_FACTOR]`` and are denormalised
    here using the actual screenshot dimensions. The returned dict has keys
    ``JSONAction`` accepts (``action_type``, ``x``, ``y``, ``direction``,
    ``text``, …) and is suitable either for ``JSONAction(**d)`` construction
    or for direct dispatch as a flat action.

    Unrecognised actions, malformed coordinates, and invalid swipe directions
    return ``{"action_type": UNKNOWN, "text": <reason>}`` rather than raising,
    so callers stay resilient to LLM output variability.

    Args:
        args: The ``arguments`` object from a parsed ``<tool_call>``.
        image_width: Width of the screenshot the model actually saw.
        image_height: Height of the screenshot the model actually saw.
    """
    action = args.get("action", "")

    if action in ("click", "long_press", "double_click"):
        try:
            x, y = _denorm_xy(args.get("coordinate", []), image_width, image_height)
        except ValueError as exc:
            return {"action_type": UNKNOWN, "text": str(exc)}
        type_map = {"click": CLICK, "long_press": LONG_PRESS, "double_click": DOUBLE_TAP}
        return {"action_type": type_map[action], "x": x, "y": y}

    if action == "swipe":
        direction = reverse_swipe_direction(args.get("direction", "up"))
        if direction not in _SCROLL_DIRECTIONS:
            return {"action_type": UNKNOWN, "text": f"Invalid swipe direction: {direction}"}
        d: dict[str, Any] = {"action_type": SCROLL, "direction": direction}
        coord = args.get("coordinate")
        if coord:
            try:
                d["x"], d["y"] = _denorm_xy(coord, image_width, image_height)
            except ValueError as exc:
                return {"action_type": UNKNOWN, "text": str(exc)}
        return d

    if action == "drag":
        try:
            sx, sy = _denorm_xy(args.get("start_coordinate", [0, 0]), image_width, image_height)
            ex, ey = _denorm_xy(args.get("end_coordinate", [0, 0]), image_width, image_height)
        except ValueError as exc:
            return {"action_type": UNKNOWN, "text": str(exc)}
        return {
            "action_type": DRAG,
            "start_x": sx,
            "start_y": sy,
            "end_x": ex,
            "end_y": ey,
        }

    if action == "type":
        return {"action_type": INPUT_TEXT, "text": args.get("text", "")}

    if action == "open":
        return {"action_type": OPEN_APP, "app_name": args.get("text", "")}

    if action == "system_button":
        button = args.get("button", "").lower()
        button_map = {
            "back": NAVIGATE_BACK,
            "home": NAVIGATE_HOME,
            "enter": KEYBOARD_ENTER,
        }
        if button in button_map:
            return {"action_type": button_map[button]}
        return {"action_type": UNKNOWN, "text": f"Unknown button: {button}"}

    if action == "terminate":
        return {"action_type": FINISHED, "text": args.get("status", "success")}

    if action == "answer":
        return {"action_type": ANSWER, "text": args.get("text", "")}

    if action == "ask_user":
        return {"action_type": ASK_USER, "text": args.get("text", "")}

    if action == "wait":
        return {"action_type": WAIT}

    return {"action_type": UNKNOWN, "text": f"Unknown action: {action}"}
