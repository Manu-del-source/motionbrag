#!/usr/bin/env python3
"""Capture genuine product visuals from a website for MotionBrag.

Produces viewport screenshots at several scroll depths, an optional full-page
screenshot, an optional smooth-scroll video, and a manifest.json with page
metadata plus a suggested `scenes` list you can paste into brief.json.

Only capture sites you own or have permission to use.

Setup (once):
    pip install playwright
    playwright install chromium

Usage:
    python scripts/capture.py https://example.com --out brag-output/capture
    python scripts/capture.py https://example.com --mobile --sections 5 --video
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

COOKIE_BUTTON_TEXTS = ["Accept all", "Accept", "I agree", "Got it", "Agree", "OK"]


def dismiss_banners(page) -> None:
    """Best-effort click on common cookie/consent buttons."""
    for text in COOKIE_BUTTON_TEXTS:
        try:
            btn = page.get_by_role("button", name=text, exact=True).first
            if btn.is_visible(timeout=300):
                btn.click(timeout=800)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


def read_metadata(page) -> dict:
    return page.evaluate(
        """() => {
            const meta = (n) => {
              const el = document.querySelector(`meta[name="${n}"], meta[property="${n}"]`);
              return el ? el.content : null;
            };
            const texts = (sel, max) => Array.from(document.querySelectorAll(sel))
              .map(e => e.innerText.trim().replace(/\\s+/g, ' '))
              .filter(t => t.length > 2 && t.length < 90)
              .slice(0, max);
            return {
              title: document.title || null,
              description: meta('description') || meta('og:description'),
              theme_color: meta('theme-color'),
              og_image: meta('og:image'),
              h1: texts('h1', 1)[0] || null,
              headings: texts('h2', 6),
              scroll_height: document.documentElement.scrollHeight,
            };
        }"""
    )


def smooth_scroll(page, total: int, viewport_h: int, seconds: float) -> None:
    """Scroll top to bottom over roughly `seconds` for the recorded video."""
    max_y = max(total - viewport_h, 0)
    steps = max(int(seconds * 30), 1)
    for i in range(steps + 1):
        # ease-in-out so the motion feels intentional
        t = i / steps
        eased = t * t * (3 - 2 * t)
        page.evaluate("y => window.scrollTo(0, y)", int(max_y * eased))
        page.wait_for_timeout(int(1000 / 30))


def capture(args: argparse.Namespace) -> dict:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.mobile:
        width, height, scale = 390, 844, 2
    else:
        width, height, scale = args.width, args.height, 1

    manifest: dict = {"url": args.url, "viewport": [width, height], "screenshots": []}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx_kwargs = dict(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
            is_mobile=args.mobile,
            has_touch=args.mobile,
        )
        if args.video:
            ctx_kwargs["record_video_dir"] = str(out / "_video")
            ctx_kwargs["record_video_size"] = {"width": width, "height": height}
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        try:
            page.goto(args.url, wait_until="networkidle", timeout=args.timeout)
        except PWTimeout:
            # Many sites never go fully idle (analytics, chat widgets).
            page.goto(args.url, wait_until="load", timeout=args.timeout)
        page.wait_for_timeout(args.wait)
        dismiss_banners(page)

        meta = read_metadata(page)
        manifest["metadata"] = meta
        total = int(meta["scroll_height"] or height)

        # Viewport screenshots at evenly spaced scroll depths.
        max_y = max(total - height, 0)
        n = max(args.sections, 1)
        positions = [0] if n == 1 else [round(max_y * i / (n - 1)) for i in range(n)]
        for i, y in enumerate(positions, start=1):
            page.evaluate("y => window.scrollTo(0, y)", y)
            page.wait_for_timeout(700)  # let lazy images and reveal animations settle
            path = out / f"section-{i:02d}.png"
            page.screenshot(path=str(path))
            manifest["screenshots"].append({"file": path.name, "scroll_y": y})

        if args.full_page:
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
            full = out / "full-page.png"
            page.screenshot(path=str(full), full_page=True)
            manifest["full_page"] = full.name

        if args.video:
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            smooth_scroll(page, total, height, args.video_seconds)
            page.wait_for_timeout(500)

        context.close()  # flushes the video file
        if args.video:
            video_path = Path(page.video.path())
            final = out / "scroll.webm"
            video_path.replace(final)
            try:
                (out / "_video").rmdir()
            except OSError:
                pass
            manifest["video"] = final.name

        browser.close()

    # Suggested scenes: one per screenshot, titled from page headings where possible.
    titles = [meta.get("h1")] + (meta.get("headings") or [])
    zooms = ["zoom_in", "pan_up", "zoom_out", "pan_down"]
    manifest["suggested_scenes"] = []
    for i, shot in enumerate(manifest["screenshots"]):
        title = titles[i] if i < len(titles) and titles[i] else f"Scene {i + 1}"
        manifest["suggested_scenes"].append(
            {
                "image": str(out / shot["file"]),
                "title": title,
                "duration": 5,
                "motion": zooms[i % len(zooms)],
            }
        )

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out", default="brag-output/capture")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--mobile", action="store_true", help="390x844 @2x touch emulation (for 9:16 promos)")
    ap.add_argument("--sections", type=int, default=4, help="number of scroll-depth screenshots")
    ap.add_argument("--full-page", action="store_true", help="also save a full-page screenshot")
    ap.add_argument("--video", action="store_true", help="record a smooth-scroll video (webm)")
    ap.add_argument("--video-seconds", type=float, default=8.0)
    ap.add_argument("--wait", type=int, default=1500, help="ms to wait after load")
    ap.add_argument("--timeout", type=int, default=30000, help="navigation timeout in ms")
    args = ap.parse_args()

    if not args.url.startswith(("http://", "https://")):
        args.url = "https://" + args.url

    try:
        manifest = capture(args)
    except ImportError:
        print("Playwright is not installed. Run:\n  pip install playwright\n  playwright install chromium", file=sys.stderr)
        return 1
    except Exception as exc:  # surface a readable error instead of a traceback wall
        print(f"Capture failed: {exc}", file=sys.stderr)
        return 1

    print(f"Saved {len(manifest['screenshots'])} screenshots to {args.out}")
    print(f"Manifest: {Path(args.out) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
