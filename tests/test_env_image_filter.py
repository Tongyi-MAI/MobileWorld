"""Containers started from a pinned tag must still be found by default filters."""

from unittest.mock import patch

import mobile_world.core.api.env as env_api


PINNED = {"Names": "mobile_world_env_0", "Image": "ghcr.io/tongyi-mai/mobile_world:v1.4",
          "ID": "abc", "Status": "Up 5 minutes", "Ports": ""}


def test_default_filter_matches_a_pinned_tag():
    with patch("mobile_world.runtime.utils.docker.docker_ps", return_value=[PINNED]):
        found = env_api.list_containers()
    assert [c.name for c in found] == ["mobile_world_env_0"], (
        "a :v1.4 container was invisible to the default image filter")


def test_launch_default_still_carries_a_tag():
    from mobile_world.runtime.utils.models import DEFAULT_IMAGE, DEFAULT_IMAGE_FILTER
    assert ":" in DEFAULT_IMAGE.rsplit("/", 1)[-1], "launch default must name a concrete tag"
    assert DEFAULT_IMAGE.startswith(DEFAULT_IMAGE_FILTER)
    assert ":" not in DEFAULT_IMAGE_FILTER.rsplit("/", 1)[-1], "filter default must not pin a tag"
