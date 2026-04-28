#!/usr/bin/env python3
"""Bundle traj.json + result.txt (and optionally screenshots) from a trajectory directory into site assets.

Without --with-screenshots: produces a single .json.gz
With --with-screenshots:    produces .json.gz (with frame indices) + .mp4 (all screenshots as video frames)

To publish MP4 videos to MAI-UI-blog for GitHub Pages hosting:

  1. Generate .json.gz + .mp4:
     uv run python site/bundle_trajs.py <traj_dir> -o site/trajs/<model>.json.gz \
       --with-screenshots \
       --video-base-url https://tongyi-mai.github.io/MAI-UI-blog/MobileWorld/trajs

  2. Push .mp4 files to the asset repo:
     git clone --depth 1 git@github.com:Tongyi-MAI/MAI-UI-blog.git /tmp/mai-ui-blog
     cp site/trajs/*.mp4 /tmp/mai-ui-blog/site/MobileWorld/trajs/
     cd /tmp/mai-ui-blog && git add -A && git commit -m "Update MobileWorld trajectory videos" && git push
"""

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

SCREENSHOT_RESIZE_WIDTH = 270
VIDEO_FPS = 2
VIDEO_CRF = 30


def _find_screenshot(screenshots_dir: str, task_name: str, task_id: str, step: int) -> Optional[str]:
    """Return path to the screenshot for a given step, or None."""
    path = os.path.join(screenshots_dir, f"{task_name}-{task_id}-{step}.png")
    return path if os.path.exists(path) else None


def bundle(traj_dir: str, output: str, with_screenshots: bool = False, video_base_url: str = "") -> None:
    if with_screenshots:
        from PIL import Image  # noqa: F401

    combined = {}
    # frame_index → (screenshot_path, original_width, original_height)
    frames = []
    original_size = None

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
        steps = entry.get("traj", [])

        result = None
        result_file = os.path.join(task_path, "result.txt")
        if os.path.exists(result_file):
            with open(result_file) as f:
                result = f.read().strip()

        screenshots_dir = os.path.join(task_path, "screenshots")

        if with_screenshots and os.path.isdir(screenshots_dir):
            for step in steps:
                step_num = step.get("step", 0)
                img_path = _find_screenshot(screenshots_dir, task_name, "0", step_num)
                if img_path:
                    if original_size is None:
                        with Image.open(img_path) as img:
                            original_size = img.size
                    step["frame_index"] = len(frames)
                    frames.append(img_path)

        combined[task_name] = {
            "traj": steps,
            "token_usage": entry.get("token_usage", {}),
            "result": result,
        }

    video_ref = None
    if with_screenshots and frames:
        video_output = output.replace(".json.gz", ".mp4")
        video_basename = os.path.basename(video_output)
        _encode_video(frames, video_output, original_size)
        if video_base_url:
            video_ref = video_base_url.rstrip("/") + "/" + video_basename
        else:
            video_ref = video_basename

    if with_screenshots and original_size and frames:
        resize_h = int(SCREENSHOT_RESIZE_WIDTH * original_size[1] / original_size[0])
        combined["_meta"] = {
            "video_file": video_ref,
            "fps": VIDEO_FPS,
            "total_frames": len(frames),
            "original_width": original_size[0],
            "original_height": original_size[1],
            "display_width": SCREENSHOT_RESIZE_WIDTH,
            "display_height": resize_h,
        }

    json_bytes = json.dumps(combined, ensure_ascii=False).encode("utf-8")
    with gzip.open(output, "wb") as f:
        f.write(json_bytes)

    gz_size = os.path.getsize(output)
    print(f"{len(combined) - (1 if '_meta' in combined else 0)} tasks | {len(json_bytes)/1024:.0f} KB raw | {gz_size/1024:.0f} KB gzipped -> {output}")
    if video_ref:
        video_path = output.replace(".json.gz", ".mp4")
        print(f"{len(frames)} frames -> {os.path.getsize(video_path)/1024/1024:.1f} MB video -> {video_path}")
        if video_base_url:
            print(f"Video URL in JSON: {video_ref}")


def _encode_video(frame_paths, video_output, original_size) -> None:
    from PIL import Image

    tmpdir = tempfile.mkdtemp(prefix="mw_frames_")
    try:
        target_w = SCREENSHOT_RESIZE_WIDTH
        target_h = None
        if original_size:
            target_h = int(target_w * original_size[1] / original_size[0])
            if target_h % 2 != 0:
                target_h += 1
        if target_w % 2 != 0:
            target_w += 1

        for i, src_path in enumerate(frame_paths):
            with Image.open(src_path) as img:
                if target_h is None:
                    target_h = int(target_w * img.height / img.width)
                    if target_h % 2 != 0:
                        target_h += 1
                resized = img.convert("RGB").resize((target_w, target_h), Image.LANCZOS)
                resized.save(os.path.join(tmpdir, f"{i:06d}.png"), optimize=True)

        os.makedirs(os.path.dirname(video_output) or ".", exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(VIDEO_FPS),
            "-i", os.path.join(tmpdir, "%06d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", str(VIDEO_CRF),
            "-movflags", "+faststart",
            video_output,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traj_dir", help="Path to the trajectory logs directory (e.g. traj_logs/k26_general_3)")
    parser.add_argument("-o", "--output", help="Output path (default: site/trajs/<dirname>.json.gz)")
    parser.add_argument(
        "--with-screenshots",
        action="store_true",
        help="Bundle screenshots into a video file (.mp4) alongside the .json.gz",
    )
    parser.add_argument(
        "--video-base-url",
        default="",
        help="Base URL for video files (e.g. https://user.github.io/assets-repo/trajs). "
        "If set, _meta.video_file will be an absolute URL instead of a relative path.",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.traj_dir):
        sys.exit(f"Error: {args.traj_dir} is not a directory")

    output = args.output or os.path.join("site", "trajs", os.path.basename(args.traj_dir.rstrip("/")) + ".json.gz")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    bundle(args.traj_dir, output, with_screenshots=args.with_screenshots, video_base_url=args.video_base_url)
