#!/usr/bin/env python3
"""Mix narration over background music, automatically ducking music while speech is present."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
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
    parser.add_argument("video", type=Path, help="Rendered MP4; its video stream is copied")
    parser.add_argument("--voiceover", required=True, type=Path, help="Narration audio file")
    parser.add_argument("--music", required=True, type=Path, help="Licensed background music")
    parser.add_argument("--output", type=Path, default=Path("brag-output/website-promo-narrated.mp4"))
    parser.add_argument("--music-volume", type=float, default=0.24, help="Music level from 0.0 to 1.0")
    parser.add_argument("--voice-volume", type=float, default=1.0, help="Narration level from 0.0 to 2.0")
    parser.add_argument("--threshold", type=float, default=0.08, help="Sidechain threshold from 0.01 to 0.9")
    parser.add_argument("--ratio", type=float, default=5.0, help="Ducking compression ratio")
    parser.add_argument("--fade", type=float, default=1.5, help="Music fade-in/out duration in seconds")
    args = parser.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"ERROR: {tool} is not installed or not on PATH.", file=sys.stderr)
            return 2
    for label, path in (("video", args.video), ("voiceover", args.voiceover), ("music", args.music)):
        if not path.is_file():
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 2
    if args.output.resolve() == args.video.resolve():
        print("ERROR: output must differ from input video.", file=sys.stderr)
        return 2
    if not 0 <= args.music_volume <= 1:
        print("ERROR: music volume must be between 0 and 1.", file=sys.stderr)
        return 2
    if not 0 <= args.voice_volume <= 2:
        print("ERROR: voice volume must be between 0 and 2.", file=sys.stderr)
        return 2
    if not 0.01 <= args.threshold <= 0.9 or args.ratio < 1 or args.fade < 0:
        print("ERROR: threshold must be 0.01–0.9, ratio at least 1, and fade non-negative.", file=sys.stderr)
        return 2

    try:
        duration = probe_duration(args.video)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    fade = min(args.fade, duration / 2)
    music_filters = [f"volume={args.music_volume:.4f}"]
    if fade > 0:
        music_filters.extend([
            f"afade=t=in:st=0:d={fade:.4f}",
            f"afade=t=out:st={max(0.0, duration - fade):.4f}:d={fade:.4f}",
        ])

    graph = (
        f"[1:a]{','.join(music_filters)}[music];"
        f"[2:a]volume={args.voice_volume:.4f},asplit=2[voice_sc][voice_mix];"
        f"[music][voice_sc]sidechaincompress=threshold={args.threshold:.4f}:"
        f"ratio={args.ratio:.3f}:attack=25:release=300[ducked];"
        f"[ducked][voice_mix]amix=inputs=2:duration=first:dropout_transition=2,"
        f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[aout]"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(args.video),
        "-stream_loop", "-1", "-i", str(args.music),
        "-i", str(args.voiceover),
        "-filter_complex", graph,
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.6f}", "-movflags", "+faststart", str(args.output),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode:
        print("ERROR mixing narration and music:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1
    print(f"Narrated video: {args.output}")
    print(f"Video duration: {duration:.2f}s")
    print(f"Music level: {args.music_volume:.2f}; narration level: {args.voice_volume:.2f}")
    print(f"Sidechain threshold: {args.threshold:.2f}; ratio: {args.ratio:.1f}:1")
    print("Next: python scripts/validate_video.py " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
