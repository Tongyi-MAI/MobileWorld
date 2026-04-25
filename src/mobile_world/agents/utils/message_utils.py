"""Shared message-list helpers for chat-completion agents."""

from __future__ import annotations

import copy
from typing import Any


def hide_history_images(
    messages: list[dict[str, Any]],
    retention: int,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with older image user-turns removed.

    Keeps only the most recent ``retention`` user messages whose first content
    block is an ``image_url``. Text-only user turns (e.g. tool-call results,
    ask-user responses, plain instructions) are preserved.

    Args:
        messages: Chat-completion messages.
        retention: How many recent image turns to keep.

    Returns:
        A deepcopy of ``messages`` with surplus image turns removed.
    """
    out = copy.deepcopy(messages)
    image_indices: list[int] = []
    for i in range(len(out) - 1, -1, -1):
        msg = out[i]
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if (
            isinstance(content, list)
            and content
            and isinstance(content[0], dict)
            and content[0].get("type") == "image_url"
        ):
            image_indices.append(i)
    for idx in sorted(image_indices[retention:], reverse=True):
        del out[idx]
    return out
