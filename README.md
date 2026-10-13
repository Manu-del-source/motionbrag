# MotionBrag

MotionBrag is an original AI-agent skill inspired by the workflow of BRAG-SLIM. It turns real website interfaces into short promotional films using browser capture, camera motion, editorial captions, transitions, and FFmpeg.

This repository is an independent implementation and does not include or copy BRAG's source code.

## Current capabilities

- Capture a sequence of real website viewport screenshots with Playwright.
- Scroll pages to reveal content below the fold, including lazy-loaded sections.
- Render screenshots as motion-led video scenes with camera zooms, captions, progress marks, and crossfades.
- Add a licensed soundtrack after rendering, with adjustable volume and fade-in/fade-out.
- Automatically select an encoder available in the local FFmpeg build (libx264, libopenh264, or mpeg4).
- Validate duration, dimensions, frame rate, codecs, and complete video decoding.
- Keep the typography-only renderer as a separate mode.

## Requirements

- Python 3.10+
- FFmpeg with ffprobe
- Pillow and Playwright (installed from requirements.txt)
- Chromium for Playwright

On Fedora, use your enabled FFmpeg repositories and check `ffmpeg -version`. Some Fedora builds omit encoders such as libx264; the website renderer detects libopenh264 as a fallback when available.

## Setup on Fedora

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

If Playwright reports missing operating-system libraries, follow the dependency instructions printed by `python -m playwright install --with-deps chromium` only if supported by your distribution, or install the missing Fedora packages through DNF.

## Create a website promo

Capture a public website. Example:

```bash
python scripts/capture_site.py https://malihub.smartbiz365.site/ \
  --output-dir brag-output/malihub-capture \
  --shots 6
```

The capture folder contains `shot-01.png`, `shot-02.png`, etc. and a `manifest.json`. Review the screenshots before rendering. Captures may include cookie notices or other overlays shown by the site.

Render a 30–60-second film:

```bash
python scripts/render_website.py brag-output/malihub-capture/manifest.json \
  --output brag-output/malihub-website-film.mp4 \
  --duration 30 --width 640 --height 360 --fps 24
```

### Add an energetic soundtrack

Download a track whose license allows your intended use (for example, an instrumental electronic, upbeat, or cinematic track from [Mixkit's free music library](https://mixkit.co/free-stock-music/) or [Pixabay Music](https://pixabay.com/music/)). Check the specific track's license and keep a copy of its license/attribution details with your project. Do not use commercial chart music unless you have permission.

Place the downloaded file somewhere such as `assets/music/promo-track.mp3`, then run:

```bash
python scripts/add_music.py brag-output/malihub-website-film.mp4 \
  --music assets/music/promo-track.mp3 \
  --output brag-output/malihub-website-film-music.mp4 \
  --volume 0.22 --fade 1.5
```

The music mixer keeps the original video stream without re-encoding it, loops shorter tracks as needed, trims the soundtrack to the video duration, and applies gentle fade-in and fade-out. Adjust `--volume` between `0.0` and `1.0`; around `0.18`–`0.28` is a useful starting point for background music.

Validate and play the final version:

```bash
python scripts/validate_video.py brag-output/malihub-website-film-music.mp4
xdg-open brag-output/malihub-website-film-music.mp4
```

Useful renderer options:

```bash
python scripts/render_website.py --help
python scripts/add_music.py --help
```

- `--duration 30` to `--duration 60`
- `--width 1280 --height 720` for a higher-resolution render; use `640x360` for a quick low-load test
- `--accent '#D68A52'` for the caption accent color
- `--transition 0` to disable crossfades if the local FFmpeg build has a filter issue

Use only pages and media you are authorized to capture. Do not capture account dashboards containing customer data, private messages, access tokens, or other sensitive information. For a public product demo, prefer public pages and test accounts with dummy data. Browser capture is not a substitute for recording actual interactive user flows; the current capture script scrolls a page and captures viewport frames.

## Existing typography renderer

```bash
python scripts/render.py examples/malihub-30s.json --output brag-output/motionbrag.mp4
python scripts/validate_video.py brag-output/motionbrag.mp4
```

This remains available for simple typography-based videos. Website promos use the separate `capture_site.py` and `render_website.py` pipeline.

## Skill installation

The skill instructions live in `SKILL.md`. Copy the skill directory into the skills location supported by your agent, or ask the agent to use this repository's `SKILL.md`. Skill discovery paths vary by agent.

## Project status

The website capture and motion-rendering path is an early implementation. It has not yet been verified end-to-end on every operating system or website. Inspect captures, validate the rendered MP4, and review playback before publishing. No paid API is required.
