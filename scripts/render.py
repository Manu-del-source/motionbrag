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

    transition = brief.get("transition", "none")
    if not isinstance(transition, str) or transition.lower() not in ("none", "fade", "crossfade"):
        raise BriefError("'transition' must be none, fade, or crossfade")
    transition = transition.lower()
    transition_duration = _number(brief.get("transition_duration", 0.5), "transition_duration")
    if not 0 <= transition_duration <= 3:
        raise BriefError("'transition_duration' must be between 0 and 3 seconds")
    transition_style = brief.get("transition_style", "fade")
    styles = {"fade": "fade", "wipe": "wipe", "wipe_left": "wipe_left", "wipe_right": "wipe_right",
              "slide": "slide", "slide_left": "slide_left", "slide_right": "slide_right"}
    if not isinstance(transition_style, str) or transition_style.lower() not in styles:
        raise BriefError("'transition_style' must be fade, wipe, wipe_left, wipe_right, slide, slide_left, or slide_right")
    transition_style = transition_style.lower()

    title_animation = brief.get("title_animation", "none")
    if not isinstance(title_animation, str) or title_animation.lower() not in ("none", "fade", "slide_up"):
        raise BriefError("'title_animation' must be none, fade, or slide_up")
    title_animation = title_animation.lower()
    allowed_effects = ("none", "shake", "glitch", "pulse", "flash")
    effect = brief.get("effect", "none")
    if not isinstance(effect, str) or effect.lower() not in allowed_effects:
        raise BriefError("'effect' must be none, shake, glitch, pulse, or flash")
    effect = effect.lower()
    for index, scene in enumerate(scenes, start=1):
        if "effect" in scene and (not isinstance(scene["effect"], str) or scene["effect"].lower() not in allowed_effects):
            raise BriefError(f"scene {index} 'effect' must be none, shake, glitch, pulse, or flash")
        for key in ("image", "caption"):
            if key in scene and scene[key] is not None and not isinstance(scene[key], str):
                raise BriefError(f"scene {index} '{key}' must be a string")
        if "overlays" in scene:
            if not isinstance(scene["overlays"], list):
                raise BriefError(f"scene {index} 'overlays' must be an array")
            for overlay in scene["overlays"]:
                if not isinstance(overlay, dict):
                    raise BriefError(f"scene {index} overlays must contain objects")
                if "image" in overlay and not isinstance(overlay["image"], str):
                    raise BriefError(f"scene {index} overlay 'image' must be a string path")
                for key in ("x", "y", "width", "opacity"):
                    if key in overlay:
                        value = _number(overlay[key], f"scene {index} overlay.{key}")
                        if not 0 <= value <= 1:
                            raise BriefError(f"scene {index} overlay '{key}' must be between 0 and 1")

    zoom = brief.get("keyframe_zoom")
    if zoom is not None:
        if not isinstance(zoom, dict):
            raise BriefError("'keyframe_zoom' must be an object with from/to values")
        zfrom = _number(zoom.get("from", 1.0), "keyframe_zoom.from")
        zto = _number(zoom.get("to", 1.05), "keyframe_zoom.to")
        if not 1 <= zfrom <= 1.2 or not 1 <= zto <= 1.2:
            raise BriefError("keyframe zoom values must be between 1.0 and 1.2")
        zoom = {"from": zfrom, "to": zto}
    speed_ramp = brief.get("speed_ramp", "none")
    if not isinstance(speed_ramp, str) or speed_ramp.lower() not in ("none", "ease_in_out"):
        raise BriefError("'speed_ramp' must be none or ease_in_out")
    speed_ramp = speed_ramp.lower()
    bpm = _number(brief.get("beat_sync_bpm", 0), "beat_sync_bpm")
    if bpm != 0 and not 30 <= bpm <= 240:
        raise BriefError("'beat_sync_bpm' must be 0 or between 30 and 240")
    captions = brief.get("captions", False)
    if not isinstance(captions, bool):
        raise BriefError("'captions' must be a boolean")
    for key in ("logo",):
        if key in brief and brief[key] is not None and not isinstance(brief[key], str):
            raise BriefError(f"'{key}' must be a string path")
    overlays = brief.get("overlays", [])
    if not isinstance(overlays, list):
        raise BriefError("'overlays' must be an array")
    for overlay in overlays:
        if not isinstance(overlay, dict):
            raise BriefError("each overlay must be an object")
        if "image" in overlay and not isinstance(overlay["image"], str):
            raise BriefError("overlay 'image' must be a string path")
        for key, default, low, high in (("x", 0.82, 0, 1), ("y", 0.76, 0, 1),
                                        ("width", 0.12, 0, 1), ("opacity", 1, 0, 1)):
            if key in overlay:
                value = _number(overlay[key], f"overlay.{key}")
                if not low <= value <= high:
                    raise BriefError(f"overlay '{key}' must be between {low} and {high}")

    editing_enabled = bool(transition != "none" or title_animation != "none" or effect != "none" or
                           any(s.get("effect", "none") != "none" for s in scenes) or zoom is not None or
                           speed_ramp != "none" or bpm or captions or brief.get("logo") or overlays or
                           any(s.get("image") or s.get("caption") or s.get("overlays") for s in scenes))
    return {
        "width": width, "height": height, "fps": fps, "scenes": scenes,
        "duration": target_duration,
        "brand": hex_rgb(brief.get("brand_color") or "#D68A52", (214, 138, 82)),
        "background": hex_rgb(brief.get("background_color") or "#101014", (16, 16, 20)),
        "transition": transition, "transition_duration": transition_duration,
        "transition_style": transition_style, "title_animation": title_animation,
        "effect": effect, "keyframe_zoom": zoom, "speed_ramp": speed_ramp,
        "beat_sync_bpm": bpm, "captions": captions, "overlays": overlays,
        "logo": brief.get("logo"), "editing_enabled": editing_enabled,
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



def cover_fit(img: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / img.width, height / img.height)
    img = img.resize((max(1, int(img.width * scale + 0.5)), max(1, int(img.height * scale + 0.5))), Image.LANCZOS)
    left = (img.width - width) // 2
    top = (img.height - height) // 2
    return img.crop((left, top, left + width, top + height))


def draw_scene(path: Path, width: int, height: int, title: str, subtitle: str,
               brand: tuple[int, int, int], background: tuple[int, int, int],
               index: int, total: int, image_path: Path | None = None,
               logo_path: Path | None = None,
               overlays: list[dict[str, Any]] | None = None,
               caption: str = "") -> None:
    image = Image.new("RGB", (width, height), background)

    # Optional per-scene background image: cover-fit, darkened so type stays readable.
    if image_path and Path(image_path).is_file():
        bg = Image.open(image_path).convert("RGB")
        bg = cover_fit(bg, width, height)
        bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.45)
        image.paste(bg, (0, 0))

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
    # Optional logo, top-right, scaled to ~8% of height.
    if logo_path and Path(logo_path).is_file():
        logo = Image.open(logo_path).convert("RGBA")
        lh = max(1, int(height * 0.08))
        lw = max(1, int(logo.width * lh / logo.height))
        logo = logo.resize((lw, lh), Image.LANCZOS)
        image.paste(logo, (width - lw - margin, margin), logo)

    # Optional user-supplied overlays/stickers. Coordinates and width are frame fractions.
    for item in overlays or []:
        sticker_path = Path(str(item.get("image", "")))
        if not sticker_path.is_file():
            continue
        sticker = Image.open(sticker_path).convert("RGBA")
        sticker_width = max(1, int(width * float(item.get("width", 0.12))))
        sticker_height = max(1, int(sticker.height * sticker_width / sticker.width))
        sticker = sticker.resize((sticker_width, sticker_height), Image.LANCZOS)
        opacity = max(0.0, min(1.0, float(item.get("opacity", 1.0))))
        if opacity < 1:
            alpha = sticker.getchannel("A").point(lambda value: int(value * opacity))
            sticker.putalpha(alpha)
        x = int(width * float(item.get("x", 0.82)))
        y = int(height * float(item.get("y", 0.76)))
        image.paste(sticker, (x, y), sticker)

    # Captions are supplied per scene, not inferred with an external speech model.
    if caption:
        caption_face = font(max(18, int(height * 0.032)), True)
        caption_lines = wrap_text(draw, caption, caption_face, int(width * 0.84))
        caption_y = height - int(height * 0.22) - len(caption_lines) * int(height * 0.045)
        for line in caption_lines:
            bbox = draw.textbbox((0, 0), line, font=caption_face)
            tw = bbox[2] - bbox[0]
            tx = (width - tw) // 2
            draw.rounded_rectangle((tx - 16, caption_y - 7, tx + tw + 16, caption_y + bbox[3] + 7),
                                   radius=8, fill=(0, 0, 0, 170))
            draw.text((tx, caption_y), line, font=caption_face, fill=(255, 255, 255, 255))
            caption_y += int(height * 0.045)

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
    # Validate and normalize optional editing controls here so missing values stay inert.
    transition = settings["transition"]
    transition_duration = settings["transition_duration"]
    transition_style = settings["transition_style"]
    bpm = settings["beat_sync_bpm"]
    if bpm > 0 and len(durations) > 1:
        beat = 60.0 / bpm
        min_gap = max(0.5, beat * 0.5)
        snapped = [0.0]
        elapsed = 0.0
        for boundary in durations[:-1]:
            elapsed += boundary
            candidate = round(elapsed / beat) * beat
            lower = snapped[-1] + min_gap
            upper = target_duration - min_gap * (len(durations) - len(snapped))
            snapped.append(min(max(candidate, lower), upper))
        snapped.append(target_duration)
        durations = [snapped[i + 1] - snapped[i] for i in range(len(snapped) - 1)]
    if transition in ("fade", "crossfade") and transition_duration > 0:
        durations = [d + transition_duration for d in durations[:-1]] + [durations[-1]]

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
                           brand, background, index, len(scenes),
                           image_path=Path(scene["image"]) if scene.get("image") else None,
                           logo_path=Path(raw["logo"]) if raw.get("logo") else None,
                           overlays=scene.get("overlays", raw.get("overlays", [])),
                           caption=str(scene.get("caption", "") if raw.get("captions", False) else ""))
                clip_path = temp / f"clip-{index:03d}.mp4"
                frames = max(1, round(duration * fps))
                # No new settings means the PR #5 filter, quality, and encode path remain unchanged.
                vf = (f"zoompan=z='min(zoom+0.00035,1.035)':d=1:"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"s={width}x{height}:fps={fps},format=yuv420p")
                title_animation = settings["title_animation"]
                effect = scene.get("effect", settings["effect"])
                zoom = settings["keyframe_zoom"]
                if title_animation == "fade":
                    vf += ",fade=t=in:st=0:d=0.45"
                elif title_animation == "slide_up":
                    vf = (f"zoompan=z='1.035':d=1:x='iw/2-(iw/zoom/2)':"
                          f"y='max(0,ih/2-(ih/zoom/2)+60*(1-min(on/({frames}*0.35),1)))':"
                          f"s={width}x{height}:fps={fps},format=yuv420p")
                if zoom is not None:
                    z0, z1 = zoom["from"], zoom["to"]
                    progress = f"on/{max(1, frames - 1)}"
                    if settings["speed_ramp"] == "ease_in_out":
                        progress = f"({progress})*({progress})*(3-2*({progress}))"
                    vf = (f"zoompan=z='{z0:.4f}+({z1-z0:.4f})*{progress}':d=1:"
                          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                          f"s={width}x{height}:fps={fps},format=yuv420p")
                if effect == "shake":
                    vf = (f"zoompan=z='1.05':d=1:x='iw/2-(iw/zoom/2)+8*sin(on*2.5)':"
                          f"y='ih/2-(ih/zoom/2)+6*sin(on*3.1)':s={width}x{height}:fps={fps},format=yuv420p")
                elif effect == "glitch":
                    vf += ",rgbashift=rh=1:bh=-1"
                elif effect == "pulse":
                    vf += ",eq=brightness='0.05+0.05*sin(2*PI*t)'"
                elif effect == "flash":
                    vf += ",eq=brightness='if(lt(mod(t,2),0.08),0.35,0)'"
                if bpm > 0:
                    period = 60.0 / bpm
                    vf += f",eq=brightness='0.04+0.04*sin(2*PI*t/{period:.5f})'"
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                       "-loop", "1", "-framerate", str(fps), "-i", str(image_path),
                       "-vf", vf, "-frames:v", str(frames), "-an",
                       "-c:v", "libx264", "-preset", args.preset,
                       "-crf", str(args.crf if not settings["editing_enabled"] else 23)]
                if not settings["editing_enabled"]:
                    cmd.extend(["-tune", "stillimage", "-pix_fmt", "yuv420p"])
                cmd.append(str(clip_path))
                run_ffmpeg(cmd, f"rendering scene {index + 1}")
                clip_paths.append(clip_path)

            if transition in ("fade", "crossfade") and len(clip_paths) > 1 and transition_duration > 0:
                transition_map = {"fade": "fade", "wipe_left": "wipeleft", "wipe_right": "wiperight",
                                  "slide_left": "slideleft", "slide_right": "slideright",
                                  "wipe": "wipeleft", "slide": "slideleft"}
                transition_filter = transition_map[transition_style]
                chained = clip_paths[0]
                prev_out_dur = durations[0]
                for i, nxt in enumerate(clip_paths[1:]):
                    out_path = temp / f"x{i:03d}.mp4"
                    offset = max(0.0, prev_out_dur - transition_duration)
                    xargs = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                             "-i", str(chained), "-i", str(nxt), "-filter_complex",
                             f"[0:v][1:v]xfade=transition={transition_filter}:duration={transition_duration:.3f}:offset={offset:.3f}[v]",
                             "-map", "[v]", "-an", "-c:v", "libx264", "-preset", args.preset,
                             "-crf", "23", str(out_path)]
                    run_ffmpeg(xargs, f"applying transition {i + 1}")
                    prev_out_dur = offset + durations[i + 1]
                    chained = out_path
                clip_paths = [chained]

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
