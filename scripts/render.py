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
    parser.add_argument("--preset", default="veryfast", choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"])
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("ERROR: FFmpeg is not installed or not on PATH.", file=sys.stderr)
        return 2
    if not args.brief.is_file():
        print(f"ERROR: brief not found: {args.brief}", file=sys.stderr)
        return 2
    if args.music and not args.music.is_file():
        print(f"ERROR: music file not found: {args.music}", file=sys.stderr)
        return 2
    try:
        brief = json.loads(args.brief.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read JSON brief: {exc}", file=sys.stderr)
        return 2

    width = int(brief.get("width", 1280))
    height = int(brief.get("height", 720))
    fps = int(brief.get("fps", 30))
    scenes = brief.get("scenes")
    if width < 320 or height < 320 or width > 1920 or height > 1920 or fps not in (24, 25, 30, 50, 60):
        print("ERROR: use dimensions from 320–1920 and fps 24, 25, 30, 50, or 60.", file=sys.stderr)
        return 2
    if not isinstance(scenes, list) or not scenes:
        print("ERROR: brief must contain a non-empty 'scenes' array.", file=sys.stderr)
        return 2

    target_duration = float(brief.get("duration", sum(float(s.get("duration", 5)) for s in scenes)))
    if not 30 <= target_duration <= 60:
        print("ERROR: requested duration must be between 30 and 60 seconds.", file=sys.stderr)
        return 2
    scene_weights = [max(0.1, float(s.get("duration", 5))) for s in scenes]
    total_weight = sum(scene_weights)
    durations = [target_duration * w / total_weight for w in scene_weights]
    durations[-1] += target_duration - sum(durations)
    bpm = float(brief.get("beat_sync_bpm", 0) or 0)
    if bpm > 0 and len(durations) > 1:
        beat = 60.0 / max(30.0, min(240.0, bpm))
        min_gap = max(0.5, beat * 0.5)
        snapped = [0.0]
        target = 0.0
        for boundary in durations[:-1]:
            target += boundary
            candidate = round(target / beat) * beat
            lower = snapped[-1] + min_gap
            upper = target_duration - min_gap * (len(durations) - len(snapped))
            snapped.append(min(max(candidate, lower), upper))
        snapped.append(target_duration)
        durations = [snapped[i + 1] - snapped[i] for i in range(len(snapped) - 1)]
    _trans = str(brief.get("transition", "none")).lower()
    _td = float(brief.get("transition_duration", 0.5)) if _trans in ("fade", "crossfade") else 0.0
    if _td > 0:
        durations = [d + _td for d in durations[:-1]] + [durations[-1]]

    brand = hex_rgb(brief.get("brand_color", "#D68A52"), (214, 138, 82))
    background = hex_rgb(brief.get("background_color", "#101014"), (16, 16, 20))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="motionbrag-") as temp_dir:
        temp = Path(temp_dir)
        clip_paths: list[Path] = []
        for index, (scene, duration) in enumerate(zip(scenes, durations)):
            image_path = temp / f"scene-{index:03d}.png"
            draw_scene(image_path, width, height,
                       str(scene.get("title") or brief.get("title") or "A new idea"),
                       str(scene.get("subtitle") or brief.get("tagline") or ""),
                       brand, background, index, len(scenes),
                       image_path=(Path(str(scene["image"])) if scene.get("image") else None),
                       logo_path=(Path(str(brief["logo"])) if brief.get("logo") else None),
                       overlays=scene.get("overlays", brief.get("overlays", [])),
                       caption=str(scene.get("caption", "") if brief.get("captions", False) else ""))
            clip_path = temp / f"clip-{index:03d}.mp4"
            frames = max(1, round(duration * fps))
            # Preserve the legacy filter chain byte-for-byte when no new options are set.
            vf = (f"zoompan=z='min(zoom+0.00035,1.035)':d=1:"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"s={width}x{height}:fps={fps},format=yuv420p")
            title_animation = str(brief.get("title_animation", "none")).lower()
            effect = str(brief.get("effect", "none")).lower()
            zoom = brief.get("keyframe_zoom")
            if title_animation == "fade":
                vf += ",fade=t=in:st=0:d=0.45"
            elif title_animation == "slide_up":
                vf = (f"zoompan=z='1.035':d=1:x='iw/2-(iw/zoom/2)':"
                      f"y='max(0,ih/2-(ih/zoom/2)+60*(1-min(on/({frames}*0.35),1)))':"
                      f"s={width}x{height}:fps={fps},format=yuv420p")
            if isinstance(zoom, dict):
                z0 = max(1.0, min(1.2, float(zoom.get("from", 1.0))))
                z1 = max(1.0, min(1.2, float(zoom.get("to", 1.05))))
                progress = f"on/{max(1,frames-1)}"
                if brief.get("speed_ramp") == "ease_in_out":
                    progress = f"({progress})*({progress})*(3-2*({progress}))"
                vf = (f"zoompan=z='{z0:.4f}+({z1-z0:.4f})*{progress}':d=1:"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"s={width}x{height}:fps={fps},format=yuv420p")
            if effect == "shake":
                vf = (f"zoompan=z='1.05':d=1:x='iw/2-(iw/zoom/2)+8*sin(on*2.5)':"
                      f"y='ih/2-(ih/zoom/2)+6*sin(on*3.1)':s={width}x{height}:fps={fps},format=yuv420p")
            elif effect == "glitch":
                vf += ",rgbashift=rh=4:bh=-4"
            elif effect == "pulse":
                vf += ",eq=brightness='0.05+0.05*sin(2*PI*t)'"
            elif effect == "flash":
                vf += ",eq=brightness='if(lt(mod(t,2),0.08),0.35,0)'"
            bpm = float(brief.get("beat_sync_bpm", 0) or 0)
            if bpm > 0:
                period = 60.0 / max(30.0, min(240.0, bpm))
                vf += f",eq=brightness='0.04+0.04*sin(2*PI*t/{period:.5f})'"
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-loop", "1", "-framerate", str(fps), "-i", str(image_path),
                   "-vf", vf, "-frames:v", str(frames), "-an",
                   "-c:v", "libopenh264", "-preset", args.preset, "-crf", "23",
                   str(clip_path)]
            result = subprocess.run(cmd, text=True, capture_output=True)
            if result.returncode:
                print(f"ERROR rendering scene {index + 1}:\n{result.stderr}", file=sys.stderr)
                return 1
            clip_paths.append(clip_path)

        # Optional crossfade transitions between scenes. Each scene except the last
        # is rendered with an extra transition_duration of tail so the final cut
        # still lands on the target duration.
        transition = str(brief.get("transition", "none")).lower()
        transition_duration = float(brief.get("transition_duration", 0.5))
        transition_name = str(brief.get("transition_style", "fade")).lower()
        transition_map = {"fade": "fade", "wipe_left": "wipeleft", "wipe_right": "wiperight",
                         "slide_left": "slideleft", "slide_right": "slideright"}
        if transition in ("fade", "crossfade") and len(clip_paths) > 1 and transition_duration > 0:
            transition_filter = transition_map.get(transition_name, "fade")
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
                result = subprocess.run(xargs, text=True, capture_output=True)
                if result.returncode:
                    print(f"ERROR applying transition {i + 1}:\n{result.stderr}", file=sys.stderr)
                    return 1
                prev_out_dur = offset + durations[i + 1]
                chained = out_path
            clip_paths = [chained]

        concat_file = temp / "concat.txt"
        concat_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in clip_paths), encoding="utf-8")
        joined = temp / "joined.mp4"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(joined)]
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode:
            print(f"ERROR joining scenes:\n{result.stderr}", file=sys.stderr)
            return 1

        if args.music:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(joined), "-stream_loop", "-1", "-i", str(args.music),
                   "-t", f"{target_duration:.3f}", "-map", "0:v:0", "-map", "1:a:0",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                   "-af", "volume=0.22,afade=t=in:st=0:d=1.2,afade=t=out:st=" + f"{max(0,target_duration-2):.3f}" + ":d=2",
                   "-shortest", "-movflags", "+faststart", str(args.output)]
        else:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(args.output)]
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode:
            print(f"ERROR finalizing video:\n{result.stderr}", file=sys.stderr)
            return 1

    print(f"Rendered: {args.output}")
    print(f"Target duration: {target_duration:.2f}s")
    print(f"Resolution: {width}x{height} at {fps} fps")
    print("Next: python scripts/validate_video.py " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
