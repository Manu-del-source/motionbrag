#!/usr/bin/env python3
"""Story-led website film renderer: preserve the UI, animate the composition, not the pixels."""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

BG_TOP = (16, 17, 23)
BG_BOTTOM = (7, 8, 12)
WHITE = (248, 247, 245)
MUTED = (177, 179, 188)
DEFAULT_ACCENT = "#D68A52"


def font(size: int, bold: bool = False):
    names = (["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
             if bold else
             ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def parse_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise ValueError("accent must be a 3- or 6-digit hex color")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def fit_inside(image: Image.Image, width: int, height: int) -> Image.Image:
    """Resize into a box without cropping or distorting any UI content."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def humanize_path(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return "THE PRODUCT"
    part = re.sub(r"[-_]+", " ", path.split("/")[-1])
    part = re.sub(r"\s+", " ", part).strip()
    return part.upper()[:54] if part else "THE PRODUCT"


def scene_copy(shot: dict, index: int, total: int, source_url: str) -> tuple[str, str]:
    """Prefer actual capture metadata; fall back to the captured URL, never generic filler."""
    url = str(shot.get("url") or shot.get("page_url") or source_url)
    title = str(shot.get("title") or shot.get("heading") or shot.get("label") or "").strip()
    subtitle = str(shot.get("description") or shot.get("subtitle") or "").strip()
    if not title:
        title = humanize_path(url)
    title = re.sub(r"\s+", " ", title).strip().upper()[:58]
    if not subtitle:
        path = urlparse(url).path.strip("/")
        subtitle = "A closer look at the real interface" if not path else "Explore the " + path.split("/")[-1].replace("-", " ").replace("_", " ")
    subtitle = re.sub(r"\s+", " ", subtitle).strip()[:90]
    if index == 0 and not shot.get("title") and not shot.get("heading") and not shot.get("label"):
        title = urlparse(source_url).netloc.removeprefix("www.").upper() or "THE PRODUCT"
        subtitle = "A look inside the product"
    if index == total - 1:
        domain = urlparse(source_url).netloc.removeprefix("www.")
        title = domain.upper() if domain else title
        subtitle = "Explore the product online"
    return title, subtitle


def gradient_background(width: int, height: int, accent: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGB", (width, height))
    pix = im.load()
    for y in range(height):
        t = y / max(1, height - 1)
        base = tuple(round(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        for x in range(width):
            # A restrained accent glow, far behind the product window.
            dx = (x - width * 0.78) / (width * 0.85)
            dy = (y - height * 0.08) / (height * 0.8)
            glow = max(0.0, 1.0 - math.sqrt(dx * dx + dy * dy)) * 0.10
            pix[x, y] = tuple(min(255, round(base[i] * (1 - glow) + accent[i] * glow)) for i in range(3))
    return im


def compose_scene(source: Path, out: Path, width: int, height: int, index: int, total: int,
                  domain: str, accent: tuple[int, int, int], headline: str, subtitle: str,
                  frame_no: int, scene_frames: int, intro: bool = False) -> None:
    # Motion is a restrained movement of the complete browser card. Screenshot pixels are never zoomed.
    t = frame_no / max(1, scene_frames - 1)
    eased = t * t * (3 - 2 * t)
    direction = -1 if index % 2 else 1
    drift_x = direction * (eased - 0.5) * width * 0.012
    drift_y = (0.5 - eased) * height * 0.006
    canvas = gradient_background(width, height, accent).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")

    margin = round(width * 0.055)
    eyebrow = font(max(12, round(height * 0.021)), True)
    title_font = font(max(24, round(height * 0.041)), True)
    sub_font = font(max(15, round(height * 0.021)))
    micro = font(max(11, round(height * 0.016)), True)

    # Header: short and quiet, with a scene-specific title rather than stock slogans.
    draw.rounded_rectangle((margin, round(height * 0.042), margin + round(width * 0.035),
                            round(height * 0.042) + 4), radius=2, fill=(*accent, 255))
    draw.text((margin, round(height * 0.058)), domain.upper()[:44] or "WEBSITE FILM",
              font=eyebrow, fill=(*WHITE, 238))
    counter = f"{index + 1:02d} / {total:02d}"
    box = draw.textbbox((0, 0), counter, font=micro)
    draw.text((width - margin - (box[2] - box[0]), round(height * 0.062)),
              counter, font=micro, fill=(*MUTED, 240))

    # Browser card dimensions leave a dedicated caption band and preserve the screenshot aspect ratio.
    card_w = round(width * 0.90)
    card_h = round(height * 0.705)
    card_x = round((width - card_w) / 2 + drift_x)
    card_y = round(height * 0.125 + drift_y)
    chrome_h = max(24, round(height * 0.038))
    radius = max(9, round(width * 0.009))

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((card_x - 2, card_y + 8, card_x + card_w + 2, card_y + card_h + 10),
                         radius=radius, fill=(0, 0, 0, 145))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(5, round(width * 0.009))))
    canvas = Image.alpha_composite(canvas, shadow)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h),
                           radius=radius, fill=(24, 25, 32, 255),
                           outline=(255, 255, 255, 36), width=1)
    draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + chrome_h + 7),
                           radius=radius, fill=(35, 36, 44, 255))
    draw.rectangle((card_x, card_y + chrome_h, card_x + card_w, card_y + chrome_h + 7),
                   fill=(35, 36, 44, 255))
    dot_r = max(3, round(height * 0.005))
    for j, col in enumerate(((242, 105, 96, 230), (242, 190, 78, 230), (80, 190, 120, 230))):
        cx = card_x + round(width * 0.018) + j * dot_r * 3
        cy = card_y + chrome_h // 2
        draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=col)
    # A minimal address pill grounds the image as a browser capture, not a poster.
    address = (domain or "website").replace("https://", "").replace("http://", "")[:48]
    pill_w = min(round(card_w * 0.54), max(120, round(width * 0.33)))
    pill_x = card_x + (card_w - pill_w) // 2
    pill_y = card_y + round(chrome_h * 0.22)
    draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + round(chrome_h * 0.56)),
                           radius=7, fill=(18, 19, 24, 230))
    draw.text((pill_x + 9, pill_y - 1), address, font=micro, fill=(*MUTED, 240))

    inner_pad = max(3, round(width * 0.003))
    area_x = card_x + inner_pad
    area_y = card_y + chrome_h + inner_pad
    area_w = card_w - inner_pad * 2
    area_h = card_h - chrome_h - inner_pad * 2
    with Image.open(source) as raw:
        shot = fit_inside(raw, area_w, area_h)
    # Keep the screenshot centered in a dark matte. Never crop, stretch, or zoom UI text.
    sx = area_x + (area_w - shot.width) // 2
    sy = area_y + (area_h - shot.height) // 2
    canvas.alpha_composite(shot.convert("RGBA"), (sx, sy))

    # Caption is outside the browser card so it cannot cover the actual interface.
    draw = ImageDraw.Draw(canvas, "RGBA")
    cap_y = round(height * 0.855)
    max_title_w = width - margin * 2
    # Shrink long real page titles to fit one line.
    while draw.textbbox((0, 0), headline, font=title_font)[2] > max_title_w and title_font.size > 18:
        title_font = font(title_font.size - 1, True)
    draw.text((margin, cap_y), headline, font=title_font, fill=(*WHITE, 255))
    sub_y = cap_y + round(height * 0.055)
    draw.text((margin, sub_y), subtitle, font=sub_font, fill=(*MUTED, 255))
    # Segment indicator replaces the oversized generic progress bar.
    track_y = height - max(12, round(height * 0.025))
    track_w = round(width * 0.13)
    draw.rounded_rectangle((margin, track_y, margin + track_w, track_y + 3),
                           radius=2, fill=(255, 255, 255, 60))
    draw.rounded_rectangle((margin, track_y, margin + round(track_w * (index + 1) / total), track_y + 3),
                           radius=2, fill=(*accent, 255))
    canvas.convert("RGB").save(out, "JPEG", quality=90, optimize=True)


def write_deliverables(output: Path, source_url: str, scenes: list[tuple[str, str]], thumbnail: Path) -> None:
    out_dir = output.parent
    plan = ["# Website film plan", "", f"Source: {source_url or 'Not supplied'}", "",
            "The film keeps the captured interface fully visible inside a browser frame. Movement is applied to the composed frame, not by zooming into screenshot pixels.", "",
            "## Scenes", ""]
    for i, (title, subtitle) in enumerate(scenes, 1):
        plan += [f"{i}. **{title}** — {subtitle}"]
    (out_dir / "brag-plan.md").write_text("\n".join(plan) + "\n", encoding="utf-8")
    domain = urlparse(source_url).netloc.removeprefix("www.")
    caption = f"A closer look at {domain or 'the product'} — captured from the real interface."
    (out_dir / "share-copy.txt").write_text(caption + "\n", encoding="utf-8")
    if thumbnail.is_file():
        shutil.copy2(thumbnail, out_dir / "brag.jpg")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("brag-output/website-story-film.mp4"))
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--accent", default=DEFAULT_ACCENT)
    parser.add_argument("--transition", type=float, default=0.35)
    parser.add_argument("--transition-style", choices=("clean", "cinematic", "energetic"), default="clean")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("ERROR: FFmpeg is not installed or not on PATH.", file=sys.stderr)
        return 2
    if not args.manifest.is_file():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    if not 30 <= args.duration <= 60:
        print("ERROR: duration must be between 30 and 60 seconds.", file=sys.stderr)
        return 2
    if args.width < 640 or args.height < 360 or args.width > 1920 or args.height > 1920:
        print("ERROR: dimensions must be at least 640x360 and no larger than 1920x1920.", file=sys.stderr)
        return 2
    if args.fps not in (24, 25, 30, 50, 60):
        print("ERROR: fps must be 24, 25, 30, 50, or 60.", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        accent = parse_color(args.accent)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    shots = manifest.get("shots")
    if not isinstance(shots, list) or len(shots) < 2:
        print("ERROR: manifest must contain at least two captured shots.", file=sys.stderr)
        return 2
    shots = shots[:12]
    source_base = args.manifest.parent
    source_url = str(manifest.get("final_url") or manifest.get("source_url") or "")
    domain = urlparse(source_url).netloc.removeprefix("www.")
    selected = []
    for shot in shots:
        path = source_base / str(shot.get("image") or "")
        if not path.is_file():
            print(f"ERROR: screenshot missing: {path}", file=sys.stderr)
            return 2
        selected.append((shot, path))
    scene_text = [scene_copy(shot, i, len(selected), source_url) for i, (shot, _) in enumerate(selected)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    transition = min(max(0.0, args.transition), 0.8)
    frames_per_scene = max(2, round(args.duration * args.fps / len(selected)))
    actual_scene = frames_per_scene / args.fps
    actual_transition = min(transition, actual_scene * 0.18)
    thumb_path = args.output.parent / ".brag-thumbnail.jpg"

    with tempfile.TemporaryDirectory(prefix="motionbrag-story-") as temp_name:
        temp = Path(temp_name)
        inputs = []
        for i, ((shot, source), (headline, subtitle)) in enumerate(zip(selected, scene_text)):
            folder = temp / f"scene-{i:02d}"
            folder.mkdir()
            for frame_no in range(frames_per_scene):
                target = folder / f"frame-{frame_no:04d}.jpg"
                compose_scene(source, target, args.width, args.height, i, len(selected),
                              domain, accent, headline, subtitle, frame_no, frames_per_scene)
            inputs.append(folder / "frame-%04d.jpg")
            if i == 0:
                shutil.copy2(folder / "frame-0000.jpg", thumb_path)

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for pattern in inputs:
            cmd += ["-framerate", str(args.fps), "-i", str(pattern)]
        filters = []
        for i in range(len(inputs)):
            filters.append(f"[{i}:v]trim=end_frame={frames_per_scene},setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
        transitions = ["fade"] if args.transition_style == "clean" else (
            ["fade", "smoothleft", "slideright", "fadeblack"] if args.transition_style == "cinematic"
            else ["wipeleft", "slideright", "wipeup", "fade"])
        current = "v0"
        elapsed = actual_scene
        for i in range(1, len(inputs)):
            offset = max(0.0, elapsed - actual_transition)
            out_label = f"x{i}"
            name = transitions[(i - 1) % len(transitions)] if actual_transition > 0 else "fade"
            if actual_transition > 0:
                filters.append(f"[{current}][v{i}]xfade=transition={name}:duration={actual_transition:.6f}:offset={offset:.6f}[{out_label}]")
            else:
                filters.append(f"[{current}][v{i}]concat=n=2:v=1:a=0[{out_label}]")
            current = out_label
            elapsed += actual_scene - actual_transition
        cmd += ["-filter_complex", ";".join(filters), "-map", f"[{current}]", "-an",
                "-r", str(args.fps), "-movflags", "+faststart"]
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        if "libx264" in encoders:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
        elif "libopenh264" in encoders:
            cmd += ["-c:v", "libopenh264", "-b:v", "2500k"]
        elif "mpeg4" in encoders:
            cmd += ["-c:v", "mpeg4", "-q:v", "3"]
        else:
            print("ERROR: no supported software video encoder found in FFmpeg.", file=sys.stderr)
            return 2
        cmd.append(str(args.output))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode:
            print("ERROR rendering website film:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

    write_deliverables(args.output, source_url, scene_text, thumb_path)
    try:
        thumb_path.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"Rendered: {args.output}")
    print(f"Scenes: {len(selected)} | duration target: {args.duration:.1f}s | output: {args.width}x{args.height} @ {args.fps}fps")
    print(f"Also created: {args.output.parent / 'brag.jpg'}, {args.output.parent / 'brag-plan.md'}, {args.output.parent / 'share-copy.txt'}")
    print("Validate with: python scripts/validate_video.py " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
