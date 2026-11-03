"""v2 engine tests (pytest can run these unittest classes)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.brain_text import load_brain_text_for_run, parse_brain_text
from engine.default_brain import DEFAULT_BRAIN_TXT, DEFAULT_BRAIN_YAML
from engine.offline_brain import (
    load_brain_for_run, load_brain_from_text, pick_clips, plan_moments, validate_brain,
)
from engine.pipeline import Pipeline
from engine.settings import (
    DEFAULTS, bundled_brain_text, ensure_user_files, load_settings, save_settings,
)
from engine.transcript_fallback import IpBlockedError, TranscriptFetcher, parse_vtt
from engine.utils import fmt_time, parse_time, score_clip

SAMPLE = (
    "In 2009, a 19-year-old Taylor Swift won her first MTV VMA, but Kanye West "
    "stormed the stage, grabbed the microphone and said Beyonce deserved the award. "
    "In 2019, Taylor lost the rights to her first six albums when Scooter Braun "
    "bought her old record label. Instead of giving up, she re-recorded all of them."
)


class TestBrain(unittest.TestCase):
    def test_brain_validates(self):
        validate_brain(load_brain_from_text(DEFAULT_BRAIN_YAML))

    def test_sample_plan(self):
        plan = plan_moments(SAMPLE, load_brain_from_text(DEFAULT_BRAIN_YAML), 15)
        self.assertEqual(plan["main_subject"], "Taylor Swift")
        topics = [t["topic"] for t in plan["topics"]]
        self.assertIn("Kanye West: vma award 2009", topics)
        self.assertIn("Scooter Braun: bought rights 2019", topics)

    def test_embedded_brain_text_parses(self):
        sections = parse_brain_text(DEFAULT_BRAIN_TXT)
        self.assertTrue(any(k.startswith("PART A") for k in sections))
        self.assertTrue(any(k.startswith("PART B") for k in sections))


class TestUtils(unittest.TestCase):
    def test_time(self):
        self.assertEqual(fmt_time(75), "1:15")
        self.assertEqual(fmt_time(0), "0:00")
        self.assertEqual(parse_time("1:15"), 75)
        self.assertEqual(parse_time("1:02:03"), 3723)

    def test_scoring(self):
        self.assertEqual(score_clip(10, 10), 10.0)
        self.assertAlmostEqual(score_clip(8, 4), 6.4)


class TestTranscriptFallback(unittest.TestCase):
    def test_parse_vtt(self):
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello <b>world</b>\n\n00:00:05.000 --> 00:00:08.000\nSecond line\n"
        lines = parse_vtt(vtt)
        self.assertEqual(lines[0]["text"], "Hello world")
        self.assertEqual(lines[0]["start"], 1.0)

    def test_ipblocked_switches_to_whisper_and_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = TranscriptFetcher(Path(tmp))
            calls = []

            def fake_api(vid):
                calls.append("api")
                raise IpBlockedError("IpBlocked")

            def fake_whisper(vid):
                calls.append("whisper")
                return [{"start": 0.0, "text": "Taylor Swift VMA 2009 Kanye West scandal"}]

            fetcher._from_api = fake_api  # type: ignore[method-assign]
            fetcher._from_whisper = fake_whisper  # type: ignore[method-assign]
            lines = fetcher.get("abc123")
            self.assertTrue(fetcher.local_only)
            self.assertEqual(lines[0]["text"].split()[0], "Taylor")
            # Second call: cached, no new api/whisper calls.
            lines2 = fetcher.get("abc123")
            self.assertEqual(lines2, lines)
            self.assertEqual(calls, ["api", "whisper"])


def _fake_transcript():
    lines = []
    for i, start in enumerate(range(0, 60, 5)):
        lines.append({"start": float(start),
                      "text": "Taylor Swift VMA 2009 Kanye West interrupted scandal feud controversy news"})
    return lines


class TestPipelineWithFakes(unittest.TestCase):
    def _run(self, tmp):
        settings = dict(DEFAULTS)
        settings["output_folder"] = tmp
        settings["also_find_images"] = False
        data_dir = Path(tmp) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        events = []

        def fake_search(query, n):
            return [{"video_id": "vid1", "title": "Taylor Swift VMA 2009 Kanye West moment news",
                     "channel": "MTV", "duration": 300}]

        class FakeFetcher:
            def get(self, vid, duration=None):
                return _fake_transcript()

        pipe = Pipeline(settings, data_dir, log=lambda m: None, emit=events.append,
                        search_func=fake_search, transcript_fetcher=FakeFetcher())
        out = pipe.run(SAMPLE, "TaylorTest")
        return out, events

    def test_full_run_creates_excel_json_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, events = self._run(tmp)
            self.assertTrue((out / "broll_clips.xlsx").exists())
            data = json.loads((out / "broll_clips.json").read_text())
            self.assertGreater(len(data["clips"]), 0)
            self.assertTrue(any(e["type"] == "clip" for e in events))
            self.assertTrue(any(e["type"] == "done" for e in events))
            self.assertTrue((out / "resume.json").exists())

    def test_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = load_settings(Path(tmp))
            self.assertEqual(s["ai_provider"], "offline")
            s["min_score"] = 7.5
            save_settings(s, Path(tmp))
            self.assertEqual(load_settings(Path(tmp))["min_score"], 7.5)

    def test_empty_brain_file_is_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "brain_rules.yaml"
            p.write_text("", encoding="utf-8")
            ensure_user_files(Path(tmp))
            validate_brain(load_brain_from_text(p.read_text(encoding="utf-8")))

    def test_public_build_scans_from_embedded_brain_no_file(self):
        import engine.build_mode as build_mode

        orig = build_mode.PUBLIC_BUILD
        build_mode.PUBLIC_BUILD = True
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data_dir = Path(tmp) / "data"
                data_dir.mkdir(parents=True, exist_ok=True)
                ensure_user_files(data_dir)
                self.assertFalse((data_dir / "brain_rules.yaml").exists())
                brain = load_brain_for_run(data_dir)
                validate_brain(brain)
                plan = plan_moments(SAMPLE, brain, 15)
                self.assertEqual(plan["main_subject"], "Taylor Swift")
                # AI brain text also comes from the embedded copy.
                sections = load_brain_text_for_run(data_dir)
                self.assertTrue(any(k.startswith("PART A") for k in sections))
        finally:
            build_mode.PUBLIC_BUILD = orig


if __name__ == "__main__":
    unittest.main()
