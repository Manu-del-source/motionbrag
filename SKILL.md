---
name: motionbrag
description: Create polished 30–60 second promotional videos from websites, local projects, screenshots, or supplied media. Captures real interfaces with Playwright, edits motion-led scenes with FFmpeg, and validates the final MP4.
---

# MotionBrag — short-form video production skill

Act as a video director, motion designer, editor, and production engineer. Deliver a purposeful, edited video rather than a slideshow of static title cards.

## Target deliverable

- Default duration: 45 seconds; support 30–60 seconds.
- Default format: 1280×720 landscape for modest hardware; use higher resolution when appropriate.
- Default frame rate: 30 fps; MP4 with H.264 when an available encoder supports it.
- Output folder: brag-output/, including source captures, manifest, storyboard, and final video.
- Optimize for the machine. Use 960×540 or 1280×720 if memory or rendering speed is constrained.

## Workflow

1. **Understand the brief.** Identify subject, audience, platform, call to action, pages to show, brand colors, and claims that must remain accurate. Ask only for details that block production. Never invent product features, customers, metrics, or testimonials.
2. **Inspect the source.** For a URL, identify relevant public pages and capture genuine UI using Playwright. For a local project, inspect its README, package metadata, and running UI when practical. Never expose secrets, private messages, customer data, tokens, or private account details.
3. **Storyboard the edit.** Create brag-output/storyboard.md with timings, purpose, visual, camera move, transition, captions, and audio cues. Structure the story as hook → context → real product reveal → 2–4 useful interface moments → payoff → call to action.
4. **Capture real interfaces.** Use python scripts/capture_site.py URL --output-dir brag-output/site-capture --shots 6 for a public website. Review manifest.json and the PNGs before rendering. The current capture tool scrolls through a page; it does not yet record complex click-through flows or authenticated screens. Use test accounts and dummy data if a private environment is explicitly authorized.
5. **Prepare assets.** Prefer real product screenshots and user-provided assets. Keep the UI itself visually dominant; use captions as supporting editorial framing, not as the entire scene. Use only music/media the user owns, provides, or is licensed to use. Never scrape copyrighted music.
6. **Render motion-led scenes.** Use python scripts/render_website.py manifest.json --output brag-output/website-promo.mp4. It applies a slow camera zoom, editorial labels, and crossfades over actual website screenshots. Adjust duration, dimensions, accent color, and transition to suit the brief. For typography-only output, scripts/render.py remains available.
7. **Quality-check.** Run scripts/validate_video.py on the export. Check duration, resolution, frame rate, codec, audio stream, file size, and complete decode. Open the video and inspect it visually for blank frames, duplicate captures, consent banners, awkward crops, unreadable captions, or transitions that feel too slow. Fix issues before delivery.
8. **Deliver clearly.** Report the exact output path, duration, format, validation result, and limitations. Never claim a render or test succeeded unless it actually did.

## Scripts

- python scripts/capture_site.py --help: capture viewport screenshots from a public website.
- python scripts/render_website.py --help: turn a capture manifest into a motion-led website promo with FFmpeg.
- python scripts/render.py --help: render a simple typography-led MP4 from a JSON brief.
- python scripts/validate_video.py path/to/video.mp4: inspect and decode-check a video.

## Editing principles

- The actual product interface should occupy most of the frame.
- Lead with the most visually compelling real page in the first 1–3 seconds.
- Build rhythm with camera motion, purposeful crops, crossfades, and concise captions.
- Show real interfaces accurately; do not fabricate a screen and present it as functioning software.
- Keep captions inside safe margins and legible on phones.
- End with one clear call to action that does not promise unimplemented features.
- Prefer a locally renderable workflow over a dependency on paid APIs.
