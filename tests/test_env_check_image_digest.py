"""`mw env check` must not report an up-to-date image as outdated."""

import json
import subprocess
from unittest.mock import patch

import mobile_world.core.api.env as env_api

IMAGE = "ghcr.io/tongyi-mai/mobile_world:latest"
# Digests of ghcr.io/tongyi-mai/mobile_world:latest on 2026-11-17.
MANIFEST_DIGEST = "b680380eac98a7ad064707f9653772af18554d201a3e6e7cf8f15d58cdc73240"
CONFIG_DIGEST = "aa743a95daef5cd25c54fc37626c2521c03b9c9d8d1aac4cc287f3643a3e23f3"


def _fake_docker(local_manifest_digest):
    """Mimic the docker CLI for one single-platform image."""
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"digest": f"sha256:{CONFIG_DIGEST}"},
        "layers": [],
    }

    def run(cmd, **kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            out = f"ghcr.io/tongyi-mai/mobile_world@sha256:{local_manifest_digest}\n"
        elif cmd[:3] == ["docker", "manifest", "inspect"]:
            if "--verbose" in cmd:
                out = json.dumps(
                    {
                        "Ref": IMAGE,
                        "Descriptor": {"digest": f"sha256:{MANIFEST_DIGEST}"},
                        "SchemaV2Manifest": manifest,
                    }
                )
            else:
                out = json.dumps(manifest)
        else:
            raise AssertionError(cmd)
        return subprocess.CompletedProcess(cmd, 0, out, "")

    return run


def test_current_image_is_not_reported_outdated():
    with patch.object(env_api.subprocess, "run", side_effect=_fake_docker(MANIFEST_DIGEST)):
        status = env_api.check_image_status(IMAGE)
    assert status.local_digest == status.remote_digest == MANIFEST_DIGEST
    assert status.needs_update is False


def test_older_local_image_is_reported_outdated():
    with patch.object(env_api.subprocess, "run", side_effect=_fake_docker("0" * 64)):
        status = env_api.check_image_status(IMAGE)
    assert status.needs_update is True
