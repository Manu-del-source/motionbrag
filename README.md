# MotionBrag

MotionBrag is an original AI-agent skill inspired by the workflow of BRAG-SLIM. It helps compatible coding agents plan and produce edited 30–60 second promotional videos from websites, local projects, screenshots, and supplied media.

The repository is an independent implementation; it does not include or copy BRAG's source code.

## What it aims to do

- Turn a short brief into a timed storyboard.
- Use genuine website/product captures where available.
- Create motion-led title cards and product scenes.
- Render MP4 with FFmpeg and optionally mix licensed music.
- Validate duration, dimensions, codecs, and playback.

## Requirements

- Python 3.10+
- FFmpeg and ffprobe
- Pillow (install with `python -m pip install -r requirements.txt`)
- Optional: Playwright for browser capture, plus its browser installation; optional TTS software for narration.

On Fedora, install FFmpeg from your enabled repositories (RPM Fusion may be needed), then verify with `ffmpeg -version` and `ffprobe -version`.

## Quick start

Create a JSON brief:

```json
{
  "title": "Meet MaliHub",
  "tagline": "A better way to discover local fashion",
  "call_to_action": "Explore MaliHub",
  "duration": 30,
  "width": 1280,
  "height": 720,
  "fps": 30,
  "brand_color": "#D68A52",
  "background_color": "#101014",
  "scenes": [
    {"title": "Discover something different", "subtitle": "Style starts with discovery", "duration": 5},
    {"title": "Explore the marketplace", "subtitle": "Browse products in one place", "duration": 7},
    {"title": "Find your next favourite", "subtitle": "A simple shopping experience", "duration": 7},
    {"title": "Your style. Your choice.", "subtitle": "Discover MaliHub today", "duration": 6}
  ]
}
```

Save it as `brief.json`, then run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/render.py brief.json --output brag-output/motionbrag.mp4
python scripts/validate_video.py brag-output/motionbrag.mp4
```

The renderer creates animated typography scenes as a starter pipeline. For a real product promo, use the skill workflow to capture product screens, replace or supplement title cards with those visuals, add intentional transitions, and use only media you have rights to use. Audio can be supplied with `--music path/to/licensed-track.mp3`.

## Skill installation

The skill instructions live in `SKILL.md`. Copy the skill directory into the skills location supported by your agent, or ask the agent to use this repository's `SKILL.md`. Skill discovery paths vary by agent.

## Project status

Early MVP. The baseline renderer focuses on reliable local rendering; browser capture, richer compositing, narration integration, and automated visual review are planned improvements. No paid API is required for the baseline renderer.
