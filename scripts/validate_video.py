#!/usr/bin/env python3
"""Validate an exported video using ffprobe and a full FFmpeg decode pass."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--min-duration", type=float, default=1.0)
    args = parser.parse_args()

    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        print("ERROR: ffprobe and ffmpeg must be installed.", file=sys.stderr)
        return 2
    if not args.video.is_file():
        print(f"ERROR: video not found: {args.video}", file=sys.stderr)
        return 2

    probe = run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", str(args.video),
    ])
    if probe.returncode:
        print(probe.stderr.strip() or "ffprobe failed", file=sys.stderr)
        return 1
    try:
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        size = int(info["format"].get("size", 0))
        streams = info.get("streams", [])
    except (ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: could not parse ffprobe output: {exc}", file=sys.stderr)
        return 1

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream:
        print("ERROR: no video stream found.", file=sys.stderr)
        return 1
    if duration < args.min_duration:
        print(f"ERROR: duration {duration:.2f}s is below minimum {args.min_duration:.2f}s.", file=sys.stderr)
        return 1

    decode = run(["ffmpeg", "-v", "error", "-i", str(args.video), "-f", "null", "-"])
    if decode.returncode:
        print("ERROR: FFmpeg could not fully decode the file.", file=sys.stderr)
        if decode.stderr.strip():
            print(decode.stderr.strip(), file=sys.stderr)
        return 1

    print("Video validation passed")
    print(f"  File:      {args.video}")
    print(f"  Duration:  {duration:.2f}s")
    print(f"  Resolution:{video_stream.get('width')}x{video_stream.get('height')}")
    print(f"  Video:     {video_stream.get('codec_name')}")
    print(f"  Frame rate:{video_stream.get('r_frame_rate')}")
    print(f"  Audio:     {audio_stream.get('codec_name') if audio_stream else 'none'}")
    print(f"  File size: {size / (1024 * 1024):.2f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
