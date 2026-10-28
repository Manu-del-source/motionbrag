# Changes

Improvement pass on the motionbrag-improvements branch. Existing layout and CLI kept, no rewrite.

## Bugs fixed (scripts/render.py)
- Non-numeric brief values (for example "width": "wide", "fps": true, "fps": 29.97) crashed with a traceback. They now exit with code 2 and a clear message.
- Odd width or height produced an invalid yuv420p stream for H.264. Brief validation now rejects odd dimensions with a message.
- Scene duration of 0 or negative was silently clamped. It is now rejected.
- Concat list paths were written with bare single quotes, so a path containing an apostrophe broke the join. Paths are now escaped.
- Without --music, the output was not trimmed to the target duration. It is now trimmed with -t.
- A --music file with no audio stream failed deep inside ffmpeg. It is now checked with ffprobe first and rejected with a clear message.
- A missing ffprobe was not checked before rendering. It is now checked along with ffmpeg.
- Brief title, tagline and colour fields with non-string types were not validated. They are now.

## Error handling
- Every ffmpeg call goes through one runner that reports the failing step (scene N, joining, finalizing) and includes stderr.
- OS-level failures (missing binary, write errors) are caught and reported as errors instead of tracebacks.
- Brief parsing moved into parse_brief(), which raises BriefError. Covered by tests.

## Output quality and audio sync
- Default CRF lowered from 23 to 20 for better quality. Use --crf (0 to 51) to change it. Invalid values are rejected.
- Added --audio-bitrate (default 160k, same as before).
- Added -tune stillimage and explicit -pix_fmt yuv420p for the title-card clips, which are mostly static.
- Added the slow preset to the allowed presets.
- The music mix is cut to the exact target duration with -t, so audio length matches the video, and the fade-out is positioned from that duration.
- Without music, the output is trimmed to the target duration too, so video length matches the brief.

## Tests (tests/test_render.py)
- 19 tests with stdlib unittest, no extra dependency.
- Covers brief validation, duration split, path quoting, hex colours, end-to-end rendering of the example brief with a 30 second duration check, and invalid-input exit codes.
- Run with: python -m unittest discover -s tests -v (all 19 pass locally).

## Not changed
- scripts/validate_video.py was reviewed and left as is.
- README.md and SKILL.md were not edited.
