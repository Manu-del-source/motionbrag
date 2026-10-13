#!/usr/bin/env python3
"""Capture a sequence of real website viewport screenshots for MotionBrag."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Public website URL to capture (HTTP or HTTPS)")
    parser.add_argument("--output-dir", type=Path, default=Path("brag-output/site-capture"))
    parser.add_argument("--shots", type=int, default=6, help="Maximum number of viewport shots (2–12)")
    parser.add_argument("--width", type=int, default=1365)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--wait", type=float, default=1.2, help="Seconds to wait after each scroll")
    parser.add_argument("--scroll-step", type=float, default=0.72, help="Viewport fraction to scroll per shot")
    parser.add_argument("--timeout", type=int, default=45000, help="Navigation timeout in milliseconds")
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print("ERROR: provide a complete http:// or https:// URL.", file=sys.stderr)
        return 2
    if not 2 <= args.shots <= 12:
        print("ERROR: --shots must be between 2 and 12.", file=sys.stderr)
        return 2
    if not 640 <= args.width <= 1920 or not 480 <= args.height <= 1200:
        print("ERROR: use a viewport width of 640–1920 and height of 480–1200.", file=sys.stderr)
        return 2
    if not 0.25 <= args.scroll_step <= 0.9:
        print("ERROR: --scroll-step must be between 0.25 and 0.9.", file=sys.stderr)
        return 2
    if not shutil.which("ffmpeg"):
        print("WARNING: ffmpeg was not found; capture can still work, but rendering will not.", file=sys.stderr)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright is missing. Run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    shots: list[dict[str, object]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=1,
                reduced_motion="reduce",
                locale="en-KE",
            )
            page = context.new_page()
            page.set_default_navigation_timeout(args.timeout)
            response = page.goto(args.url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(900)
            final_url = page.url
            page_title = page.title().strip()
            previous_y = -1
            for i in range(args.shots):
                y = page.evaluate("() => window.scrollY")
                filename = f"shot-{i + 1:02d}.png"
                image_path = output / filename
                page.screenshot(path=str(image_path), full_page=False, animations="disabled", caret="hide")
                shots.append({
                    "image": filename,
                    "index": i + 1,
                    "scroll_y": int(y),
                    "page_title": page_title,
                    "url": final_url,
                })
                if i + 1 >= args.shots:
                    break
                previous_y = int(y)
                page.evaluate("(fraction) => window.scrollBy(0, Math.max(1, Math.floor(window.innerHeight * fraction)) )", args.scroll_step)
                page.wait_for_timeout(max(250, int(args.wait * 1000)))
                new_y = int(page.evaluate("() => window.scrollY"))
                max_y = int(page.evaluate("() => Math.max(0, document.documentElement.scrollHeight - window.innerHeight)"))
                if new_y == previous_y or (new_y >= max_y and i >= 1):
                    break
            context.close()
            browser.close()
    except Exception as exc:
        print(f"ERROR capturing website: {exc}", file=sys.stderr)
        print("If Chromium is not installed, run: python -m playwright install chromium", file=sys.stderr)
        return 1

    manifest = {
        "tool": "MotionBrag website capture",
        "source_url": args.url,
        "final_url": final_url,
        "page_title": page_title,
        "http_status": response.status if response else None,
        "viewport": {"width": args.width, "height": args.height},
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "shots": shots,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Captured {len(shots)} website views into: {output}")
    print(f"Page title: {page_title or '(no title)'}")
    print(f"Final URL: {final_url}")
    print(f"Manifest: {manifest_path}")
    print("Next: python scripts/render_website.py " + str(manifest_path) + " --output brag-output/website-promo.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
