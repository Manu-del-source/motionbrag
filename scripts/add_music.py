#!/usr/bin/env python3
"""Mix a licensed music track under a rendered MotionBrag video."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"Could not inspect {path}")
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise ValueError(f"Could not read duration for {path}") from exc
    if duration <= 0:
        raise ValueError(f"Invalid media duration for {path}")
    return duration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Rendered input MP4")
    parser.add_argument("--music", required=True, type=Path, help="Licensed music file (MP3, WAV, AAC, etc.)")
    parser.add_argument("--output", type=Path, default=Path("brag-output/website-promo-music.mp4"))
    parser.add_argument("--volume", type=float, default=0.22, help="Music volume from 0.0 to 1.0 (default: 0.22)")
    parser.add_argument("--fade", type=float, default=1.5, help="Fade-in/out duration in seconds (default: 1.5)")
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ERROR: FFmpeg and ffprobe must be installed and on PATH.", file=sys.stderr)
        return 2
    if not args.video.is_file():
        print(f"ERROR: video not found: {args.video}", file=sys.stderr)
        return 2
    if not args.music.is_file():
        print(f"ERROR: music file not found: {args.music}", file=sys.stderr)
        return 2
    if args.video.resolve() == args.output.resolve():
        print("ERROR: output must differ from input video.", file=sys.stderr)
        return 2
    if not 0.0 <= args.volume <= 1.0:
        print("ERROR: volume must be between 0.0 and 1.0.", file=sys.stderr)
        return 2
    if args.fade < 0:
        print("ERROR: fade must be zero or greater.", file=sys.stderr)
        return 2

    try:
        duration = probe_duration(args.video)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    fade = min(args.fade, duration / 2)
    filters = [f"volume={args.volume:.4f}"]
    if fade > 0:
        filters.extend([f"afade=t=in:st=0:d={fade:.4f}",
                        f"afade=t=out:st={max(0.0, duration - fade):.4f}:d={fade:.4f}"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(args.video), "-stream_loop", "-1", "-i", str(args.music),
        "-filter_complex", f"[1:a]{','.join(filters)},atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[aout]",
        "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", "-t", f"{duration:.6f}",
        "-movflags", "+faststart", str(args.output),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode:
        print("ERROR mixing music into video:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    print(f"Music added: {args.output}")
    print(f"Duration: {duration:.2f}s")
    print(f"Music volume: {args.volume:.2f}")
    print(f"Fade in/out: {fade:.2f}s")
    print("Next: python scripts/validate_video.py " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
