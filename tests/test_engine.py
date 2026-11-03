"""Engine tests, runnable with plain unittest (no pytest needed):
python -m unittest discover -s tests -v
Covers the shipped tests plus pipeline, export, safe mode and resume.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.offline_brain import load_brain, pick_clips, plan_moments
from engine.pipeline import Pipeline
from engine.settings import DEFAULTS, bundled_brain_text, ensure_user_files, load_settings, save_settings
from engine.transcript_fallback import TranscriptFetcher, parse_vtt
from engine.utils import fmt_time, parse_time, score_clip

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ('Hey guys, welcome back. In 2009, a 19-year-old Taylor Swift won her first MTV VMA, '
          'but Kanye West stormed the stage, grabbed the microphone and said Beyonce deserved '
          'the award. The moment went viral and started a feud that lasted for years. '
          'In 2019, Taylor lost the rights to her first six albums when Scooter Braun bought '
          'her old record label. Instead of giving up, she re-recorded all of them, and '
          '"Taylor\'s Version" became one of the biggest comebacks in music history. '
          "Don't forget to subscribe.")


def fake_transcript():
    lines = []
    def add(t, s):
        lines.append({"start": t, "text": s})
    add(0, "hey guys welcome back to my channel don't forget to subscribe")
    add(5, "this video is sponsored by nordvpn use code")
    add(20, "so let's talk about music awards in general")
    add(60, "breaking news tonight at the MTV VMAs 2009")
    add(66, "Kanye West interrupted Taylor Swift on stage [booing]")
    add(72, "the crowd was booing as he grabbed the microphone")
    add(78, "she was shocked and heartbroken")
    add(90, "later Taylor said I felt embarrassed honestly")
    add(200, "thanks for watching like and subscribe")
    return lines


class TestUtils(unittest.TestCase):
    def test_times(self):
        self.assertEqual(fmt_time(75), "1:15")
        self.assertEqual(fmt_time(3661), "1:01:01")
        self.assertEqual(parse_time("1:15"), 75)
        self.assertEqual(parse_time("01:01:15"), 3675)
        self.assertEqual(score_clip(10, 10), 10.0)
        self.assertEqual(score_clip(10, 5), 8.0)


class TestOfflineBrain(unittest.TestCase):
    def setUp(self):
        self.brain = load_brain(ROOT / "resources" / "brain_rules.yaml")

    def test_plan_and_pick(self):
        plan = plan_moments(SCRIPT, self.brain)
        self.assertEqual(plan["main_subject"], "Taylor Swift")
        self.assertGreaterEqual(len(plan["topics"]), 2)
        video = {"title": "Kanye West interrupts Taylor Swift VMA 2009 (Official)", "channel": "MTV"}
        clips = pick_clips(plan["topics"][0], video, fake_transcript(), self.brain, 3)
        self.assertTrue(clips)
        self.assertTrue(50 <= clips[0]["start"] <= 66)
        self.assertTrue(all(c["start"] > 15 for c in clips))
        bad = pick_clips(plan["topics"][0], {"title": "cooking", "channel": "x"},
                         [{"start": i * 5, "text": "cooking pasta tips"} for i in range(40)], self.brain)
        self.assertEqual(bad, [])

    def test_brain_validation(self):
        from engine.offline_brain import validate_brain
        with self.assertRaises(ValueError):
            validate_brain({"script": {}})


class TestTranscriptFallback(unittest.TestCase):
    def test_parse_vtt(self):
        vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nKanye West <c>interrupted</c>\n\n"
               "00:00:03.000 --> 00:00:05.000\nKanye West interrupted\nTaylor on stage\n\n"
               "00:00:05.500 --> 00:00:07.000\n[booing]\n")
        lines = parse_vtt(vtt)
        self.assertEqual(lines[0], {"start": 1.0, "text": "Kanye West interrupted"})
        self.assertEqual(lines[1]["text"], "Taylor on stage")
        self.assertEqual(lines[2]["text"], "[booing]")

    def test_block_switches_to_whisper_and_caches(self):
        logs = []
        with tempfile.TemporaryDirectory() as d:
            f = TranscriptFetcher(Path(d), log=logs.append)
            calls = []
            class IpBlocked(Exception):
                pass
            def api(v):
                calls.append("api"); raise IpBlocked("IpBlocked")
            def subs(v):
                calls.append("subs"); return None
            def whisper(v):
                calls.append("whisper"); return [{"start": 0, "text": "hello"}]
            f._from_api, f._from_subtitles, f._from_whisper = api, subs, whisper
            api.__name__, subs.__name__ = "_from_api", "_from_subtitles"
            self.assertEqual(f.get("aaaaaaaaaaa"), [{"start": 0, "text": "hello"}])
            self.assertTrue(f.blocked and calls == ["api", "whisper"])
            calls.clear(); f.get("bbbbbbbbbbb"); self.assertEqual(calls, ["whisper"])
            calls.clear()
            self.assertEqual(f.get("aaaaaaaaaaa")[0]["text"], "hello")
            self.assertEqual(calls, [])
            self.assertTrue(any("local transcription" in l for l in logs))


class TestPipelineWithFakes(unittest.TestCase):
    def run_pipeline(self, tmp):
        settings = dict(DEFAULTS)
        settings["output_folder"] = str(Path(tmp) / "out")
        settings["videos_per_moment"] = 2
        settings["min_score"] = 1
        events = []
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        import shutil
        shutil.copy(ROOT / "resources" / "brain_rules.yaml", data_dir / "brain_rules.yaml")
        shutil.copy(ROOT / "resources" / "brain.txt", data_dir / "brain.txt")
        def fake_search(q, n):
            return [{"video_id": "aaaaaaaaaaa", "title": "Kanye West interrupts Taylor Swift VMA 2009 (Official)",
                     "channel": "MTV", "duration": 300, "views": 1000,
                     "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}]
        class FakeFetcher:
            blocked = False
            def get(self, vid, duration=None):
                return fake_transcript()
        pipe = Pipeline(settings, data_dir, log=lambda m: None, emit=events.append,
                        search_func=fake_search, transcript_fetcher=FakeFetcher())
        out = pipe.run(SCRIPT, "TaylorTest")
        return out, events

    def test_full_run_creates_excel_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, events = self.run_pipeline(tmp)
            self.assertTrue((out / "broll_clips.xlsx").exists())
            data = json.loads((out / "broll_clips.json").read_text())
            self.assertGreater(len(data["clips"]), 0)
            self.assertTrue(any(e["type"] == "clip" for e in events))
            self.assertTrue(any(e["type"] == "done" for e in events))
            # Resume file exists, so a stopped run can continue.
            self.assertTrue((out / "resume.json").exists())

    def test_empty_brain_file_is_repaired(self):
        # Regression: an empty BRAIN tab blocked every scan. An empty
        # brain file must be rewritten from the bundled/embedded default.
        import yaml
        from engine.offline_brain import validate_brain
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "brain_rules.yaml"
            p.write_text("", encoding="utf-8")
            ensure_user_files(Path(tmp))
            validate_brain(yaml.safe_load(p.read_text(encoding="utf-8")))

    def test_embedded_brain_fallback_when_resource_missing(self):
        import engine.settings as settings_mod
        orig = settings_mod.resource_path
        settings_mod.resource_path = lambda name: Path("/definitely/not/here") / name
        try:
            text = bundled_brain_text("brain_rules.yaml")
            self.assertTrue(text and "clips:" in text)
        finally:
            settings_mod.resource_path = orig

    def test_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = load_settings(Path(tmp))
            self.assertEqual(s["ai_provider"], "offline")
            s["min_score"] = 7.5
            save_settings(s, Path(tmp))
            self.assertEqual(load_settings(Path(tmp))["min_score"], 7.5)


if __name__ == "__main__":
    unittest.main()
