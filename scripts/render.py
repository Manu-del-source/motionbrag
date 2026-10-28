#!/usr/bin/env python3
"""Render a simple animated typography promo from a JSON brief using Pillow and FFmpeg."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"]
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def hex_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    try:
        raw = value.strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) != 6:
            raise ValueError
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except (ValueError, AttributeError):
        return fallback


def wrap_text(draw: ImageDraw.ImageDraw, text: str, face: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=face)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


class BriefError(ValueError):
    """Raised when the JSON brief is missing fields or has invalid values."""


class RenderError(RuntimeError):
    """Raised when an FFmpeg step fails."""


ALLOWED_FPS = (24, 25, 30, 50, 60)
ALLOWED_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")


def _number(value: Any, name: str, cast: type = float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise BriefError(f"'{name}' must be a number, got {value!r}")
    try:
        number = cast(value)
    except (TypeError, ValueError):
        raise BriefError(f"'{name}' must be a number, got {value!r}") from None
    if isinstance(value, float) and cast is int and not value.is_integer():
        raise BriefError(f"'{name}' must be a whole number, got {value!r}")
    if number != number or number in (float("inf"), float("-inf")):
        raise BriefError(f"'{name}' must be finite, got {value!r}")
    return number


def parse_brief(brief: Any) -> dict[str, Any]:
    """Validate a decoded brief and return normalized settings.

    Raises BriefError with a human-readable message on any invalid input.
    """
    if not isinstance(brief, dict):
        raise BriefError("brief must be a JSON object")

    width = _number(brief.get("width", 1280), "width", int)
    height = _number(brief.get("height", 720), "height", int)
    fps = _number(brief.get("fps", 30), "fps", int)
    if not 320 <= width <= 1920 or not 320 <= height <= 1920:
        raise BriefError("width and height must be between 320 and 1920")
    if width % 2 or height % 2:
        raise BriefError("width and height must be even (H.264 yuv420p requires it)")
    if fps not in ALLOWED_FPS:
        raise BriefError("fps must be one of 24, 25, 30, 50, or 60")

    scenes = brief.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise BriefError("brief must contain a non-empty 'scenes' array")
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise BriefError(f"scene {index} must be an object")
        for key in ("title", "subtitle"):
            if key in scene and scene[key] is not None and not isinstance(scene[key], str):
                raise BriefError(f"scene {index} '{key}' must be a string")
        if "duration" in scene:
            weight = _number(scene["duration"], f"scenes[{index}].duration")
            if weight <= 0:
                raise BriefError(f"scene {index} duration must be greater than 0")

    scene_total = sum(_number(s["duration"], "duration") if "duration" in s else 5.0 for s in scenes)
    if "duration" in brief:
        target_duration = _number(brief["duration"], "duration")
    else:
        target_duration = scene_total
    if not 30 <= target_duration <= 60:
        raise BriefError("requested duration must be between 30 and 60 seconds")

    for key in ("title", "tagline", "brand_color", "background_color"):
        if key in brief and brief[key] is not None and not isinstance(brief[key], str):
            raise BriefError(f"'{key}' must be a string")

    return {
        "width": width,
        "height": height,
        "fps": fps,
        "scenes": scenes,
        "duration": target_duration,
        "brand": hex_rgb(brief.get("brand_color") or "#D68A52", (214, 138, 82)),
        "background": hex_rgb(brief.get("background_color") or "#101014", (16, 16, 20)),
    }


def scene_durations(scenes: list[dict[str, Any]], target: float) -> list[float]:
    """Split the target duration across scenes by weight; the last scene absorbs rounding."""
    weights = [max(0.1, float(s.get("duration", 5))) for s in scenes]
    total = sum(weights)
    durations = [target * w / total for w in weights]
    durations[-1] += target - sum(durations)
    return durations


def ffmpeg_quote_path(path: Path) -> str:
    """Escape a path for the concat demuxer ('file' lines use single quotes)."""
    return "'" + path.as_posix().replace("'", "'\\''") + "'"


def run_ffmpeg(cmd: list[str], step: str) -> None:
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except OSError as exc:
        raise RenderError(f"could not start ffmpeg while {step}: {exc}") from exc
    if result.returncode:
        raise RenderError(f"ffmpeg failed while {step} (exit {result.returncode}):\n{result.stderr.strip()}")


def probe_has_audio(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", str(path)],
            text=True, capture_output=True, check=False)
    except OSError as exc:
        raise RenderError(f"could not run ffprobe on music file: {exc}") from exc
    return result.returncode == 0 and bool(result.stdout.strip())



def draw_scene(path: Path, width: int, height: int, title: str, subtitle: str,
               brand: tuple[int, int, int], background: tuple[int, int, int],
               index: int, total: int) -> None:
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image, "RGBA")

    # Soft brand glows and geometric framing, kept intentionally subtle.
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    radius = int(min(width, height) * 0.36)
    cx = int(width * (0.83 if index % 2 == 0 else 0.17))
    cy = int(height * (0.20 if index % 2 == 0 else 0.80))
    for step in range(28, 0, -1):
        r = int(radius * step / 28)
        alpha = int(2 + (28 - step) * 0.8)
        gd.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(*brand, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), glow)
    draw = ImageDraw.Draw(image, "RGBA")

    margin = int(width * 0.085)
    draw.rounded_rectangle((margin, int(height * .105), margin + 64, int(height * .105) + 7),
                           radius=3, fill=(*brand, 255))
    draw.text((margin, int(height * .15)), f"MOTIONBRAG  /  {index + 1:02d}",
              font=font(max(14, int(height * .022)), True), fill=(215, 215, 224, 210))

    title_face = font(max(30, int(height * .075)), True)
    lines = wrap_text(draw, title, title_face, int(width * .79))
    line_heights = [draw.textbbox((0, 0), line, font=title_face)[3] for line in lines]
    gap = int(height * .018)
    block_height = sum(line_heights) + max(0, len(lines) - 1) * gap
    subtitle_face = font(max(18, int(height * .032)))
    subtitle_lines = wrap_text(draw, subtitle, subtitle_face, int(width * .76)) if subtitle else []
    subtitle_height = sum(draw.textbbox((0, 0), line, font=subtitle_face)[3] for line in subtitle_lines)
    total_height = block_height + int(height * .04) + subtitle_height
    y = int((height - total_height) * .48)

    for line, line_height in zip(lines, line_heights):
        draw.text((margin, y), line, font=title_face, fill=(250, 249, 247, 255),
                  stroke_width=0)
        y += line_height + gap
    y += int(height * .04)
    for line in subtitle_lines:
        draw.text((margin, y), line, font=subtitle_face, fill=(195, 196, 205, 255))
        y += draw.textbbox((0, 0), line, font=subtitle_face)[3] + int(height * .008)

    # Scene progress marks.
    bar_y = height - int(height * .09)
    bar_w = int(width * .12)
    draw.rounded_rectangle((margin, bar_y, margin + bar_w, bar_y + 5), radius=2,
                           fill=(255, 255, 255, 55))
    draw.rounded_rectangle((margin, bar_y, margin + int(bar_w * (index + 1) / total), bar_y + 5),
                           radius=2, fill=(*brand, 255))
    image.convert("RGB").save(path, quality=95)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path, help="JSON brief with title and scenes")
    parser.add_argument("--output", type=Path, default=Path("brag-output/motionbrag.mp4"))
    parser.add_argument("--music", type=Path, help="Optional licensed music/audio file")
    parser.add_argument("--preset", default="veryfast", choices=list(ALLOWED_PRESETS),
                        help="x264 speed/efficiency preset (default: veryfast)")
    parser.add_argument("--crf", type=int, default=20,
                        help="x264 quality, 0-51, lower is better (default: 20)")
    parser.add_argument("--audio-bitrate", default="160k", help="AAC bitrate for music (default: 160k)")
    args = parser.parse_args()

    if not 0 <= args.crf <= 51:
        print("ERROR: --crf must be between 0 and 51.", file=sys.stderr)
        return 2
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ERROR: FFmpeg and ffprobe must be installed and on PATH.", file=sys.stderr)
        return 2
    if not args.brief.is_file():
        print(f"ERROR: brief not found: {args.brief}", file=sys.stderr)
        return 2
    if args.music and not args.music.is_file():
        print(f"ERROR: music file not found: {args.music}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(args.brief.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read JSON brief: {exc}", file=sys.stderr)
        return 2
    try:
        settings = parse_brief(raw)
    except BriefError as exc:
        print(f"ERROR: invalid brief: {exc}", file=sys.stderr)
        return 2

    width, height, fps = settings["width"], settings["height"], settings["fps"]
    scenes = settings["scenes"]
    target_duration = settings["duration"]
    durations = scene_durations(scenes, target_duration)
    brand, background = settings["brand"], settings["background"]

    try:
        if args.music and not probe_has_audio(args.music):
            print(f"ERROR: music file has no audio stream: {args.music}", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="motionbrag-") as temp_dir:
            temp = Path(temp_dir)
            clip_paths: list[Path] = []
            for index, (scene, duration) in enumerate(zip(scenes, durations)):
                image_path = temp / f"scene-{index:03d}.png"
                draw_scene(image_path, width, height,
                           str(scene.get("title") or raw.get("title") or "A new idea"),
                           str(scene.get("subtitle") or raw.get("tagline") or ""),
                           brand, background, index, len(scenes))
                clip_path = temp / f"clip-{index:03d}.mp4"
                frames = max(1, round(duration * fps))
                # A subtle zoom gives the typography cards movement without heavy compositing.
                vf = (f"zoompan=z='min(zoom+0.00035,1.035)':d=1:"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"s={width}x{height}:fps={fps},format=yuv420p")
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                       "-loop", "1", "-framerate", str(fps), "-i", str(image_path),
                       "-vf", vf, "-frames:v", str(frames), "-an",
                       "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
                       "-tune", "stillimage", "-pix_fmt", "yuv420p", str(clip_path)]
                run_ffmpeg(cmd, f"rendering scene {index + 1}")
                clip_paths.append(clip_path)

            concat_file = temp / "concat.txt"
            concat_file.write_text("".join(f"file {ffmpeg_quote_path(p)}\n" for p in clip_paths),
                                   encoding="utf-8")
            joined = temp / "joined.mp4"
            run_ffmpeg(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(concat_file),
                        "-c", "copy", str(joined)], "joining scenes")

            if args.music:
                fade_out = max(0.0, target_duration - 2)
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                       "-i", str(joined), "-stream_loop", "-1", "-i", str(args.music),
                       "-t", f"{target_duration:.3f}", "-map", "0:v:0", "-map", "1:a:0",
                       "-c:v", "copy", "-c:a", "aac", "-b:a", args.audio_bitrate,
                       "-af", f"volume=0.22,afade=t=in:st=0:d=1.2,afade=t=out:st={fade_out:.3f}:d=2",
                       "-movflags", "+faststart", str(args.output)]
            else:
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                       "-i", str(joined), "-t", f"{target_duration:.3f}", "-c", "copy",
                       "-movflags", "+faststart", str(args.output)]
            run_ffmpeg(cmd, "finalizing video")
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: file operation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Rendered: {args.output}")
    print(f"Target duration: {target_duration:.2f}s")
    print(f"Resolution: {width}x{height} at {fps} fps")
    print("Next: python scripts/validate_video.py " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
