"""Tests for the MotionBrag renderer. Run with: python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import render  # noqa: E402

EXAMPLE = ROOT / "examples" / "malihub-30s.json"


def base_brief(**overrides):
    brief = {"title": "T", "scenes": [{"title": "a", "duration": 15}, {"title": "b", "duration": 15}]}
    brief.update(overrides)
    return brief


class ParseBriefTests(unittest.TestCase):
    def test_example_brief_is_valid(self):
        settings = render.parse_brief(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        self.assertEqual(settings["duration"], 30)
        self.assertEqual((settings["width"], settings["height"], settings["fps"]), (1280, 720, 30))

    def test_defaults_applied(self):
        s = render.parse_brief(base_brief())
        self.assertEqual((s["width"], s["height"], s["fps"]), (1280, 720, 30))
        self.assertEqual(s["duration"], 30)

    def test_rejects_non_object(self):
        with self.assertRaises(render.BriefError):
            render.parse_brief([1, 2])

    def test_rejects_missing_or_empty_scenes(self):
        for bad in ({}, {"scenes": []}, {"scenes": "x"}):
            with self.assertRaises(render.BriefError):
                render.parse_brief(bad)

    def test_rejects_non_numeric_fields_with_message(self):
        with self.assertRaisesRegex(render.BriefError, "width"):
            render.parse_brief(base_brief(width="wide"))
        with self.assertRaisesRegex(render.BriefError, "fps"):
            render.parse_brief(base_brief(fps=True))

    def test_rejects_fractional_integers(self):
        with self.assertRaisesRegex(render.BriefError, "whole number"):
            render.parse_brief(base_brief(fps=29.97))

    def test_rejects_odd_dimensions(self):
        with self.assertRaisesRegex(render.BriefError, "even"):
            render.parse_brief(base_brief(width=1281))

    def test_rejects_out_of_range_dimensions_and_fps(self):
        with self.assertRaises(render.BriefError):
            render.parse_brief(base_brief(width=100))
        with self.assertRaises(render.BriefError):
            render.parse_brief(base_brief(height=2160))
        with self.assertRaises(render.BriefError):
            render.parse_brief(base_brief(fps=15))

    def test_rejects_bad_scene_entries(self):
        with self.assertRaisesRegex(render.BriefError, "scene 1 must be an object"):
            render.parse_brief(base_brief(scenes=["oops"]))
        with self.assertRaisesRegex(render.BriefError, "duration must be greater than 0"):
            render.parse_brief(base_brief(scenes=[{"duration": 0}, {"duration": 40}]))
        with self.assertRaisesRegex(render.BriefError, "title' must be a string"):
            render.parse_brief(base_brief(scenes=[{"title": 5}]))

    def test_duration_bounds(self):
        with self.assertRaisesRegex(render.BriefError, "between 30 and 60"):
            render.parse_brief(base_brief(duration=10))
        with self.assertRaisesRegex(render.BriefError, "between 30 and 60"):
            render.parse_brief(base_brief(duration=61))
        with self.assertRaises(render.BriefError):
            render.parse_brief(base_brief(duration="thirty"))

    def test_bad_colour_falls_back(self):
        s = render.parse_brief(base_brief(brand_color="not-a-colour"))
        self.assertEqual(s["brand"], (214, 138, 82))

    def test_non_string_colour_rejected(self):
        with self.assertRaises(render.BriefError):
            render.parse_brief(base_brief(brand_color=123))

    def test_editing_fields_are_normalized_and_default_to_legacy(self):
        legacy = render.parse_brief(base_brief())
        self.assertFalse(legacy["editing_enabled"])
        self.assertEqual(legacy["transition"], "none")
        self.assertEqual(legacy["title_animation"], "none")
        edited = render.parse_brief(base_brief(
            transition="crossfade", transition_style="wipe_left", transition_duration=0.4,
            title_animation="slide_up", effect="pulse", keyframe_zoom={"from": 1, "to": 1.1},
            speed_ramp="ease_in_out", beat_sync_bpm=120, captions=True,
            logo="logo.png", overlays=[{"image": "sticker.png", "opacity": 0.5}],
            scenes=[{"title": "a", "duration": 15, "image": "scene.png", "caption": "hello"},
                    {"title": "b", "duration": 15}],
        ))
        self.assertTrue(edited["editing_enabled"])
        self.assertEqual(edited["transition_style"], "wipe_left")
        self.assertEqual(edited["beat_sync_bpm"], 120)

    def test_invalid_editing_fields_are_rejected(self):
        bad_fields = (
            {"transition": "zoom"}, {"transition_duration": -1},
            {"transition_style": "spin"}, {"title_animation": "bounce"},
            {"effect": "explode"}, {"keyframe_zoom": {"from": 0.5, "to": 1.1}},
            {"speed_ramp": "random"}, {"beat_sync_bpm": 500},
            {"captions": "yes"}, {"overlays": "sticker.png"},
            {"scenes": [{"title": "x", "duration": 30, "effect": "explode"}]},
        )
        for fields in bad_fields:
            with self.subTest(fields=fields), self.assertRaises(render.BriefError):
                render.parse_brief(base_brief(**fields))


    def test_durations_sum_to_target(self):
        durations = render.scene_durations([{"duration": 5}, {"duration": 7}, {"duration": 7}], 30)
        self.assertAlmostEqual(sum(durations), 30.0, places=9)
        self.assertEqual(len(durations), 3)

    def test_durations_default_weight(self):
        durations = render.scene_durations([{}, {}], 30)
        self.assertAlmostEqual(durations[0], 15.0)

    def test_concat_path_quoting(self):
        self.assertEqual(render.ffmpeg_quote_path(Path("/tmp/it's a/clip.mp4")),
                         "'/tmp/it'\\''s a/clip.mp4'")

    def test_hex_rgb(self):
        self.assertEqual(render.hex_rgb("#fff", (0, 0, 0)), (255, 255, 255))
        self.assertEqual(render.hex_rgb("zzzzzz", (1, 2, 3)), (1, 2, 3))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class EndToEndTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "render.py"), *args],
                              capture_output=True, text=True, check=False)

    def test_example_renders_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.mp4"
            result = self.run_cli(str(EXAMPLE), "--output", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(out)], capture_output=True, text=True)
            self.assertAlmostEqual(float(probe.stdout), 30.0, delta=0.3)

    def test_invalid_brief_exits_2_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "b.json"
            brief.write_text(json.dumps(base_brief(width="wide")), encoding="utf-8")
            result = self.run_cli(str(brief), "--output", str(Path(tmp) / "o.mp4"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid brief", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_bad_crf_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(str(EXAMPLE), "--crf", "99", "--output", str(Path(tmp) / "o.mp4"))
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
