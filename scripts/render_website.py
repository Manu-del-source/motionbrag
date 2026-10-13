#!/usr/bin/env python3
"""Render captured website screenshots as a motion-led promotional video."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont


HEADLINES = [
    ("THE EXPERIENCE", "A closer look at the interface"),
    ("EXPLORE THE DETAILS", "See the experience in context"),
    ("MADE TO BE EXPLORED", "Move through the real product"),
    ("EVERY VIEW HAS A PURPOSE", "A guided look at the interface"),
    ("DESIGNED AROUND THE USER", "Explore the experience for yourself"),
    ("TAKE A CLOSER LOOK", "Discover more online"),
]


def load_font(size: int, bold: bool = False):
    candidates = (
        ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def fit_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    image = image.convert("RGB")
    scale = max(width / image.width, height / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def make_frame(source: Path, target: Path, width: int, height: int, index: int, total: int,
               domain: str, accent: tuple[int, int, int]) -> None:
    with Image.open(source) as raw:
        canvas = fit_cover(raw, width, height).convert("RGBA")
    # Darken the lower portion for readable editorial captions without hiding the website.
    shade = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = shade.load()
    for y in range(height):
        start = int(height * 0.48)
        alpha = 0 if y < start else int(18 + 178 * ((y - start) / max(1, height - start)) ** 1.25)
        for x in range(width):
            pixels[x, y] = (8, 8, 12, alpha)
    canvas = Image.alpha_composite(canvas, shade)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = int(width * 0.065)
    top = int(height * 0.055)
    small = load_font(max(13, int(height * 0.022)), True)
    title_font = load_font(max(28, int(height * 0.058)), True)
    subtitle_font = load_font(max(17, int(height * 0.027)))
    draw.rounded_rectangle((margin, top, margin + 48, top + 5), radius=2, fill=(*accent, 255))
    draw.text((margin, top + 16), "MOTIONBRAG  /  WEBSITE FILM", font=small, fill=(255, 255, 255, 220))
    counter = f"{index + 1:02d} / {total:02d}"
    bbox = draw.textbbox((0, 0), counter, font=small)
    draw.text((width - margin - (bbox[2] - bbox[0]), top + 16), counter, font=small, fill=(255, 255, 255, 205))

    headline, subtitle = HEADLINES[min(index, len(HEADLINES) - 1)]
    if index == total - 1:
        headline = "EXPLORE " + (domain.upper() if domain else "THE EXPERIENCE")
        subtitle = "Visit the website to see it for yourself"
    y = int(height * 0.70)
    draw.text((margin, y), headline, font=title_font, fill=(255, 255, 255, 255),
              stroke_width=0)
    y += int(height * 0.075)
    draw.text((margin, y), subtitle, font=subtitle_font, fill=(236, 235, 238, 245))
    bar_y = height - int(height * 0.045)
    bar_width = int(width * 0.20)
    draw.rounded_rectangle((margin, bar_y, margin + bar_width, bar_y + 4), radius=2,
                           fill=(255, 255, 255, 75))
    draw.rounded_rectangle((margin, bar_y, margin + int(bar_width * (index + 1) / total), bar_y + 4),
                           radius=2, fill=(*accent, 255))
    canvas.convert("RGB").save(target, format="PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="manifest.json created by scripts/capture_site.py")
    parser.add_argument("--output", type=Path, default=Path("brag-output/website-promo.mp4"))
    parser.add_argument("--duration", type=float, default=45.0, help="Final duration, 30–60 seconds")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--accent", default="#D68A52", help="Caption accent color, e.g. #D68A52")
    parser.add_argument("--transition", type=float, default=0.4, help="Transition duration in seconds")
    parser.add_argument("--motion-style", choices=("cinematic", "subtle", "static"), default="cinematic",
                        help="Camera movement preset (default: cinematic)")
    parser.add_argument("--transition-style", choices=("cinematic", "clean", "energetic"), default="cinematic",
                        help="Transition preset (default: cinematic)")
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
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read manifest: {exc}", file=sys.stderr)
        return 2
    shots = manifest.get("shots")
    if not isinstance(shots, list) or len(shots) < 2:
        print("ERROR: manifest must contain at least two captured shots.", file=sys.stderr)
        return 2
    shots = shots[:12]
    source_base = args.manifest.parent
    image_paths = []
    for shot in shots:
        path = source_base / str(shot.get("image", ""))
        if not path.is_file():
            print(f"ERROR: screenshot missing: {path}", file=sys.stderr)
            return 2
        image_paths.append(path)

    def rgb(value: str):
        raw = value.strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        if len(raw) != 6:
            raise ValueError("accent must be a 3- or 6-digit hex color")
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))

    try:
        accent = rgb(args.accent)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    source_url = str(manifest.get("final_url") or manifest.get("source_url") or "")
    domain = urlparse(source_url).netloc.removeprefix("www.")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="motionbrag-web-") as temp_name:
        temp = Path(temp_name)
        prepared = []
        for i, source in enumerate(image_paths):
            frame = temp / f"frame-{i:02d}.png"
            make_frame(source, frame, args.width, args.height, i, len(image_paths), domain, accent)
            prepared.append(frame)

        # Overlap scenes with crossfades while preserving the requested total runtime.
        transition = min(max(0.0, args.transition), 0.8)
        if len(prepared) < 2:
            transition = 0.0
        clip_seconds = (args.duration + transition * (len(prepared) - 1)) / len(prepared)
        frames_per_clip = max(2, round(clip_seconds * args.fps))
        actual_clip_seconds = frames_per_clip / args.fps
        actual_transition = min(transition, max(0.0, actual_clip_seconds * 0.2))
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for frame in prepared:
            cmd += ["-loop", "1", "-framerate", str(args.fps), "-t",
                    f"{actual_clip_seconds:.6f}", "-i", str(frame)]

        filters = []
        # Use quadratic ease-in-out so camera movement accelerates and settles
        # naturally. Keep zoom conservative so website text remains legible.
        last_frame = max(1, frames_per_clip - 1)
        p = f"(on/{last_frame})"
        eased = f"if(lt({p},0.5),2*pow({p},2),1-2*pow(1-{p},2))"
        motion_moves = [
            (f"1+0.045*({eased})",
             f"(iw-iw/zoom)*({eased})*0.72", "(ih-ih/zoom)*0.18"),
            (f"1+0.045*({eased})",
             f"(iw-iw/zoom)*(1-({eased})*0.72)", "(ih-ih/zoom)*0.78"),
            (f"1.045-0.045*({eased})",
             f"(iw-iw/zoom)*(0.78-({eased})*0.62)", "(ih-ih/zoom)*0.22"),
            (f"1+0.045*({eased})",
             "(iw-iw/zoom)*0.48", f"(ih-ih/zoom)*(1-({eased})*0.58)"),
        ]
        for i in range(len(prepared)):
            if args.motion_style == "static":
                zoom, xpos, ypos = ("1.0", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")
            elif args.motion_style == "subtle":
                zoom = f"1+0.025*({eased})"
                xpos, ypos = ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")
            else:
                zoom, xpos, ypos = motion_moves[i % len(motion_moves)]
            filters.append(
                f"[{i}:v]zoompan=z='{zoom}':d=1:x='{xpos}':y='{ypos}':"
                f"s={args.width}x{args.height}:fps={args.fps},"
                f"trim=end_frame={frames_per_clip},setpts=PTS-STARTPTS,settb=AVTB,"
                f"format=yuv420p[v{i}]"
            )

        if args.transition_style == "clean":
            transition_names = ["fade"]
        elif args.transition_style == "energetic":
            transition_names = ["wipeleft", "slideright", "wipeup", "fade", "wipedown"]
        else:
            transition_names = ["fade", "smoothleft", "slideright", "fadeblack"]

        current = "v0"
        elapsed = actual_clip_seconds
        for i in range(1, len(prepared)):
            offset = max(0.0, elapsed - actual_transition)
            out_label = f"x{i}"
            transition_name = transition_names[(i - 1) % len(transition_names)]
            filters.append(
                f"[{current}][v{i}]xfade=transition={transition_name}:duration={actual_transition:.6f}:"
                f"offset={offset:.6f}[{out_label}]"
            )
            current = out_label
            elapsed += actual_clip_seconds - actual_transition

        cmd += ["-filter_complex", ";".join(filters), "-map", f"[{current}]",
                "-an", "-r", str(args.fps), "-movflags", "+faststart"]
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                  capture_output=True, text=True).stdout
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
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode:
            print("ERROR rendering website video:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            print("Try --transition 0 to disable crossfades, or lower --width/--height to 960x540.", file=sys.stderr)
            return 1

    print(f"Rendered website promo: {args.output}")
    print(f"Source: {source_url}")
    print(f"Scenes: {len(prepared)}")
    print(f"Duration requested: {args.duration:.2f}s")
    print(f"Output: {args.width}x{args.height} at {args.fps} fps")
    print("Next: python scripts/validate_video.py " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
