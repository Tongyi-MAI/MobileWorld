#!/usr/bin/env python3
"""Bundle traj.json + result.txt from a trajectory directory into a single .json.gz for the site."""

import argparse
import gzip
import json
import os
import sys


def bundle(traj_dir: str, output: str) -> None:
    combined = {}
    for task_name in sorted(os.listdir(traj_dir)):
        task_path = os.path.join(traj_dir, task_name)
        if not os.path.isdir(task_path) or "_backup_" in task_name:
            continue
        traj_file = os.path.join(task_path, "traj.json")
        if not os.path.exists(traj_file):
            continue

        with open(traj_file) as f:
            traj_data = json.load(f)

        entry = traj_data.get("0", traj_data)

        result = None
        result_file = os.path.join(task_path, "result.txt")
        if os.path.exists(result_file):
            with open(result_file) as f:
                result = f.read().strip()

        combined[task_name] = {
            "traj": entry.get("traj", []),
            "token_usage": entry.get("token_usage", {}),
            "result": result,
        }

    json_bytes = json.dumps(combined, ensure_ascii=False).encode("utf-8")
    with gzip.open(output, "wb") as f:
        f.write(json_bytes)

    gz_size = os.path.getsize(output)
    print(f"{len(combined)} tasks | {len(json_bytes)/1024:.0f} KB raw | {gz_size/1024:.0f} KB gzipped -> {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traj_dir", help="Path to the trajectory logs directory (e.g. traj_logs/k26_general_3)")
    parser.add_argument("-o", "--output", help="Output path (default: site/trajs/<dirname>.json.gz)")
    args = parser.parse_args()

    if not os.path.isdir(args.traj_dir):
        sys.exit(f"Error: {args.traj_dir} is not a directory")

    output = args.output or os.path.join("site", "trajs", os.path.basename(args.traj_dir.rstrip("/")) + ".json.gz")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    bundle(args.traj_dir, output)
