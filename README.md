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

### Editing options

All options below are optional. Omitting them keeps the original render filter and appearance. Existing `transition` and `transition_duration` still enable scene transitions; add `transition_style` to choose `fade` (default), `wipe_left`, `wipe_right`, `slide_left`, or `slide_right`.

```json
{
  "transition": "crossfade",
  "transition_duration": 0.5,
  "transition_style": "wipe_left",
  "title_animation": "slide_up",
  "keyframe_zoom": {"from": 1.0, "to": 1.06},
  "speed_ramp": "ease_in_out",
  "effect": "pulse",
  "beat_sync_bpm": 120,
  "captions": true,
  "overlays": [{"image": "assets/sticker.png", "x": 0.82, "y": 0.76, "width": 0.12, "opacity": 0.9}]
}
```

`title_animation` accepts `fade` or `slide_up`. `keyframe_zoom` linearly animates scale between its `from` and `to` values (clamped to 1.0–1.2); `speed_ramp: "ease_in_out"` eases that scale motion. `effect` accepts `shake`, `glitch`, `pulse`, or `flash`. `beat_sync_bpm` (30–240) snaps scene cuts to the nearest beat and adds a subtle visual pulse; it uses the supplied BPM, not automatic music analysis. `captions: true` renders each scene's supplied `caption` text as a lower-third caption; it does not transcribe audio. `overlays` accepts user-supplied image paths and normalized `x`, `y`, `width`, and `opacity`; it can also be set on an individual scene to override the brief-level list. No stock stickers or proprietary assets are bundled.

These are deterministic FFmpeg/Pillow techniques. Fully automatic speech recognition, music beat detection, and complex AI/path-based animation are intentionally outside this renderer's dependencies.

## Skill installation

The skill instructions live in `SKILL.md`. Copy the skill directory into the skills location supported by your agent, or ask the agent to use this repository's `SKILL.md`. Skill discovery paths vary by agent.

## Project status

Early MVP. The baseline renderer focuses on reliable local rendering; browser capture, richer compositing, narration integration, and automated visual review are planned improvements. No paid API is required for the baseline renderer.
