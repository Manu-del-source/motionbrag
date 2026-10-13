#!/usr/bin/env python3
"""MotionBrag media-aware renderer.

Superset of the original brief format: scenes without a "type" (or with
"type": "title") render as animated title cards, exactly like a plain brief.
Scenes with "type": "media" and an "image" show a captured screenshot inside
a browser frame with Ken Burns motion.

Scene fields
    type        "title" | "media"                       (default "title")
    title       headline / caption text
    subtitle    secondary line (title scenes)
    image       path to screenshot (media scenes)
    motion      zoom_in | zoom_out | pan_up | pan_down | none   (default zoom_in)
    frame       browser | none                           (media scenes, default browser)
    duration    seconds                                  (default 5)

Brief-level fields
    width, height, fps, brand_color, background_color, font (path to .ttf)
    transition  {"type": "crossfade|slide|wipe|none", "duration": 0.5}

Total length = sum(scene durations) - transition_duration * (scenes - 1).

Usage
    python scripts/render_media.py brief.json --output brag-output/promo.mp4
    python scripts/render_media.py brief.json --preset reels --music track.mp3
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PRESETS = {"landscape": (1280, 720), "reels": (1080, 1920), "square": (1080, 1080)}
XFADE = {"crossfade": "fade", "fade": "fade", "slide": "slideleft", "wipe": "wipeleft", "none": None}
MOTIONS = {"zoom_in", "zoom_out", "pan_up", "pan_down", "none"}
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
    "/system/fonts/Roboto-Bold.ttf",  # Android / Termux
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


class BriefError(Exception):
    pass


# ---------- helpers ----------

def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        raise BriefError(f"Bad color '{value}', expected #RRGGBB")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def load_font(size: int, custom: str | None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ([custom] if custom else []) + FONT_CANDIDATES:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def text_block_height(lines: list[str], size: int, gap: float = 1.25) -> int:
    return int(len(lines) * size * gap)


def draw_centered(draw, lines, font, fill, cx, top, size, gap: float = 1.25) -> int:
    y = top
    for ln in lines:
        w = draw.textlength(ln, font=font)
        draw.text((cx - w / 2, y), ln, font=font, fill=fill)
        y += int(size * gap)
    return y


def background(w: int, h: int, bg, brand) -> Image.Image:
    base = Image.new("RGB", (w, h), bg)
    glow = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(glow)
    d.ellipse([w * 0.45, -h * 0.25, w * 1.3, h * 0.45], fill=brand)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    return Image.blend(base, glow, 0.35)


# ---------- scene cards ----------

def title_card(scene: dict, brief: dict, w: int, h: int, out: Path) -> None:
    s = min(w, h) / 720
    bg, brand = brief["_bg"], brief["_brand"]
    img = background(w, h, bg, brand)
    d = ImageDraw.Draw(img)
    t_size, st_size = int(64 * s), int(30 * s)
    t_font, st_font = load_font(t_size, brief.get("font")), load_font(st_size, brief.get("font"))
    title = scene.get("title", "")
    sub = scene.get("subtitle", "")
    t_lines = wrap(d, title, t_font, int(w * 0.8))
    s_lines = wrap(d, sub, st_font, int(w * 0.75)) if sub else []
    bar_h, bar_gap, sub_gap = int(6 * s), int(28 * s), int(22 * s)
    total = bar_h + bar_gap + text_block_height(t_lines, t_size) + (sub_gap + text_block_height(s_lines, st_size) if s_lines else 0)
    y = (h - total) // 2
    d.rounded_rectangle([w / 2 - 40 * s, y, w / 2 + 40 * s, y + bar_h], radius=bar_h // 2, fill=brand)
    y += bar_h + bar_gap
    y = draw_centered(d, t_lines, t_font, (255, 255, 255), w / 2, y, t_size)
    if s_lines:
        draw_centered(d, s_lines, st_font, (190, 190, 200), w / 2, y + sub_gap, st_size)
    img.save(out)


def media_card(scene: dict, brief: dict, w: int, h: int, out: Path, base_dir: Path) -> None:
    s = min(w, h) / 720
    bg, brand = brief["_bg"], brief["_brand"]
    src = resolve(scene["image"], base_dir)
    shot = Image.open(src).convert("RGB")
    img = background(w, h, bg, brand).convert("RGBA")
    d = ImageDraw.Draw(img)

    cap_size = int(36 * s)
    cap_font = load_font(cap_size, brief.get("font"))
    cap_lines = wrap(d, scene.get("title", ""), cap_font, int(w * 0.84)) if scene.get("title") else []
    cap_h = text_block_height(cap_lines, cap_size) + (int(0.04 * h) if cap_lines else 0)

    margin_x, margin_top = int(0.06 * w), int(0.05 * h)
    use_frame = scene.get("frame", "browser") == "browser"
    bar_h = int(30 * s) if use_frame else 0
    avail_w = w - 2 * margin_x
    avail_h = h - margin_top - cap_h - int(0.03 * h) - bar_h
    scale = min(avail_w / shot.width, avail_h / shot.height, 2.0)
    nw, nh = max(int(shot.width * scale), 1), max(int(shot.height * scale), 1)
    shot = shot.resize((nw, nh), Image.LANCZOS)

    fw, fh = nw, nh + bar_h
    fx = (w - fw) // 2
    fy = margin_top + (avail_h + bar_h - fh) // 2
    radius = int(14 * s)

    frame = Image.new("RGB", (fw, fh), (34, 34, 42))
    if use_frame:
        fd = ImageDraw.Draw(frame)
        r = int(5 * s)
        for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            cx, cy = int(16 * s) + i * int(18 * s), bar_h // 2
            fd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    frame.paste(shot, (0, bar_h))
    mask = Image.new("L", (fw, fh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], radius=radius, fill=255)

    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [fx, fy + int(10 * s), fx + fw, fy + fh + int(10 * s)], radius=radius, fill=(0, 0, 0, 150)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(18 * s)))
    img = Image.alpha_composite(img, shadow)
    img.paste(frame, (fx, fy), mask)

    if cap_lines:
        d = ImageDraw.Draw(img)
        top = fy + fh + int(0.035 * h)
        draw_centered(d, cap_lines, cap_font, (255, 255, 255), w / 2, top, cap_size)
    img.convert("RGB").save(out)


# ---------- ffmpeg ----------

def motion_filter(motion: str, n: int, w: int, h: int, fps: int) -> str:
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    exprs = {
        "zoom_in": (f"1+0.10*on/{n}", cx, cy),
        "zoom_out": (f"1.10-0.10*on/{n}", cx, cy),
        "pan_up": ("1.12", cx, f"(ih-ih/zoom)*(1-on/{n})"),
        "pan_down": ("1.12", cx, f"(ih-ih/zoom)*on/{n}"),
        "none": ("1", cx, cy),
    }
    z, x, y = exprs[motion]
    return f"scale={w * 2}:{h * 2}:flags=lanczos,zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={w}x{h}:fps={fps},format=yuv420p"


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{res.stderr.strip()}")


def render_clip(card: Path, motion: str, dur: float, w: int, h: int, fps: int, out: Path) -> None:
    n = max(int(round(dur * fps)), 1)
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(card),
        "-vf", motion_filter(motion, n, w, h, fps), "-frames:v", str(n),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(fps), str(out),
    ])


def assemble(clips: list[Path], durs: list[float], trans: dict, fps: int, music: str | None, out: Path) -> float:
    n = len(clips)
    t = float(trans.get("duration", 0.5))
    kind = XFADE[trans.get("type", "crossfade")]
    if kind is None:
        t = 0.0
    total = sum(durs) - t * (n - 1)

    if n == 1:
        chain, last = "", "[0:v]"
    elif kind is None:
        chain = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vx];"
        last = "[vx]"
    else:
        parts, last, acc = [], "[0:v]", 0.0
        for i in range(1, n):
            acc += durs[i - 1]
            offset = acc - i * t
            label = f"[v{i}]"
            parts.append(f"{last}[{i}:v]xfade=transition={kind}:duration={t}:offset={offset:.3f}{label}")
            last = label
        chain = ";".join(parts) + ";"
    fade = f"{last}fade=t=in:st=0:d=0.4,fade=t=out:st={max(total - 0.5, 0):.3f}:d=0.5,format=yuv420p[vout]"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
    cmd += ["-filter_complex", chain + fade, "-map", "[vout]"]
    if music:
        cmd += ["-map", f"{n}:a", "-af", f"afade=t=in:d=1,afade=t=out:st={max(total - 1.5, 0):.3f}:d=1.5",
                "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", str(fps), str(out)]
    run(cmd)
    return total


# ---------- main ----------

def resolve(path: str, base_dir: Path) -> Path:
    p = Path(path)
    for cand in ([p] if p.is_absolute() else [Path.cwd() / p, base_dir / p]):
        if cand.exists():
            return cand
    raise BriefError(f"Image not found: {path}")


def validate(brief: dict, base_dir: Path) -> None:
    scenes = brief.get("scenes")
    if not scenes:
        raise BriefError("Brief needs a non-empty 'scenes' list")
    trans = brief.get("transition", {})
    if trans.get("type", "crossfade") not in XFADE:
        raise BriefError(f"transition.type must be one of {sorted(XFADE)}")
    t = 0.0 if XFADE[trans.get("type", "crossfade")] is None else float(trans.get("duration", 0.5))
    for i, sc in enumerate(scenes, 1):
        dur = float(sc.get("duration", 5))
        if dur <= 2 * t:
            raise BriefError(f"Scene {i} duration ({dur}s) must exceed twice the transition ({t}s)")
        if sc.get("motion", "zoom_in") not in MOTIONS:
            raise BriefError(f"Scene {i}: motion must be one of {sorted(MOTIONS)}")
        if sc.get("type", "media" if sc.get("image") else "title") == "media":
            if not sc.get("image"):
                raise BriefError(f"Scene {i}: media scene needs 'image'")
            resolve(sc["image"], base_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief")
    ap.add_argument("--output", default="brag-output/motionbrag.mp4")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="override brief size")
    ap.add_argument("--music", help="licensed audio file to mix in")
    args = ap.parse_args()

    brief_path = Path(args.brief)
    base_dir = brief_path.resolve().parent
    try:
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        w, h = PRESETS[args.preset] if args.preset else (int(brief.get("width", 1280)), int(brief.get("height", 720)))
        w, h = w - w % 2, h - h % 2
        fps = int(brief.get("fps", 30))
        brief["_bg"] = hex_to_rgb(brief.get("background_color", "#101014"))
        brief["_brand"] = hex_to_rgb(brief.get("brand_color", "#D68A52"))
        validate(brief, base_dir)
        if args.music and not Path(args.music).exists():
            raise BriefError(f"Music file not found: {args.music}")

        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        durs = [float(s.get("duration", 5)) for s in brief["scenes"]]

        with tempfile.TemporaryDirectory(prefix="motionbrag_") as tmp:
            tmp_dir = Path(tmp)
            clips = []
            for i, sc in enumerate(brief["scenes"]):
                kind = sc.get("type", "media" if sc.get("image") else "title")
                card = tmp_dir / f"card{i}.png"
                if kind == "media":
                    media_card(sc, brief, w, h, card, base_dir)
                else:
                    title_card(sc, brief, w, h, card)
                clip = tmp_dir / f"clip{i}.mp4"
                render_clip(card, sc.get("motion", "zoom_in"), durs[i], w, h, fps, clip)
                clips.append(clip)
                print(f"scene {i + 1}/{len(brief['scenes'])} ({kind}) done")
            total = assemble(clips, durs, brief.get("transition", {"type": "crossfade", "duration": 0.5}), fps, args.music, out)

        target = brief.get("duration")
        if target and abs(total - float(target)) > 1:
            print(f"Note: rendered {total:.1f}s but brief says duration={target}s (transitions overlap scenes).")
        print(f"Wrote {out} ({w}x{h}, {total:.1f}s)")
        return 0
    except (BriefError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
