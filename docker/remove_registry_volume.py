#!/usr/bin/env python3
"""Clone an OCI registry tag while removing one inherited Config.Volumes key."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request


MANIFEST_TYPES = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req) as response:
        return response.read(), dict(response.headers.items())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="http://127.0.0.1:5000")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--target-tag", required=True)
    parser.add_argument("--volume", default="/var/lib/docker")
    args = parser.parse_args()

    base = f"{args.registry.rstrip('/')}/v2/{args.repository}"
    manifest_url = f"{base}/manifests/{args.source_tag}"
    manifest_bytes, manifest_headers = request(
        manifest_url, headers={"Accept": MANIFEST_TYPES}
    )
    manifest = json.loads(manifest_bytes)
    if "config" not in manifest:
        raise SystemExit("source tag did not resolve to a single-platform image manifest")

    config_digest = manifest["config"]["digest"]
    config_bytes, _ = request(f"{base}/blobs/{config_digest}")
    config = json.loads(config_bytes)
    volumes = config.get("config", {}).get("Volumes") or {}
    if args.volume not in volumes:
        raise SystemExit(f"volume {args.volume!r} is not present in source config")
    del volumes[args.volume]
    if volumes:
        config["config"]["Volumes"] = volumes
    else:
        config["config"].pop("Volumes", None)

    new_config = json.dumps(config, separators=(",", ":"), sort_keys=True).encode()
    new_digest = "sha256:" + hashlib.sha256(new_config).hexdigest()

    _, upload_headers = request(f"{base}/blobs/uploads/", method="POST", data=b"")
    location = upload_headers["Location"]
    upload_url = urllib.parse.urljoin(args.registry, location)
    separator = "&" if "?" in upload_url else "?"
    request(
        f"{upload_url}{separator}digest={urllib.parse.quote(new_digest, safe=':')}",
        method="PUT",
        data=new_config,
        headers={"Content-Type": "application/octet-stream"},
    )

    manifest["config"]["digest"] = new_digest
    manifest["config"]["size"] = len(new_config)
    new_manifest = json.dumps(manifest, separators=(",", ":")).encode()
    media_type = manifest.get("mediaType") or manifest_headers.get(
        "Content-Type", "application/vnd.oci.image.manifest.v1+json"
    )
    request(
        f"{base}/manifests/{args.target_tag}",
        method="PUT",
        data=new_manifest,
        headers={"Content-Type": media_type},
    )

    print(f"source_config={config_digest}")
    print(f"target_config={new_digest}")
    print(f"removed_volume={args.volume}")


if __name__ == "__main__":
    main()
