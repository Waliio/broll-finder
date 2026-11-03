"""The scan pipeline: script -> moments -> YouTube -> transcripts -> clips.

Default brain is Offline Brain (no key). Gemini / Claude are optional and
use the same plan/clip shapes, via engine.ai. Every transcript request
goes through TranscriptFetcher (cache -> API -> yt-dlp subtitles ->
local Whisper, with a circuit breaker). Safe mode, partial save and
Resume are built in: stopping mid-run saves what was found so far, and
Resume continues from the next unfinished moment using the cache.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from .ai import AIProvider
from .brain_text import brain_part, load_brain_text_for_run
from .export import save_results
from .offline_brain import load_brain_for_run, pick_clips, plan_moments
from .transcript_fallback import TranscriptFetcher
from .utils import clip_url, fmt_time, parse_time, score_clip
from .youtube import RequestBudget, download_all_clips, youtube_search


class Pipeline:
    def __init__(self, settings: dict, data_dir: Path, log=print,
                 emit=lambda event: None, search_func=None, transcript_fetcher=None,
                 image_func=None):
        self.settings = settings
        self.data_dir = Path(data_dir)
        self.cache_dir = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log = log
        self.emit = emit
        self._stop = False
        self.budget = RequestBudget(int(settings.get("max_youtube_requests", 40)), log=log)
        self.search_func = search_func
        self.image_func = image_func
        self._fetcher = transcript_fetcher
        self.videos_per_moment_effective = int(settings.get("videos_per_moment", 4))

    def stop(self):
        self._stop = True

    def should_stop(self):
        return self._stop

    def _log(self, msg: str):
        self.log(msg)
        self.emit({"type": "log", "text": msg})

    def _ytdlp_opts(self) -> dict:
        opts = {}
        if self.settings.get("proxy"):
            opts["proxy"] = self.settings["proxy"]
        browser = self.settings.get("cookies_from_browser", "")
        if browser:
            opts["cookiesfrombrowser"] = (browser.lower(),)
        return opts

    def get_fetcher(self) -> TranscriptFetcher:
        if self._fetcher is not None:
            return self._fetcher
        self._fetcher = TranscriptFetcher(
            self.cache_dir, ytdlp_opts=self._ytdlp_opts(),
            whisper_model=self.settings.get("whisper_fallback_model", "base"),
            whisper_max_minutes=int(self.settings.get("whisper_max_minutes", 20)),
            use_whisper_fallback=bool(self.settings.get("use_whisper_fallback", True)),
            log=self._log, should_stop=self.should_stop)
        return self._fetcher

    # -- planning ---------------------------------------------------------
    def plan(self, script_text: str, max_topics: int | None = None):
        provider = self.settings.get("ai_provider", "offline")
        max_topics = int(max_topics or self.settings.get("max_moments", 15))
        if provider == "offline":
            brain = load_brain_for_run(self.data_dir)
            return plan_moments(script_text, brain, max_topics)
        sections = load_brain_text_for_run(self.data_dir)
        ai = AIProvider(self.settings)
        system = brain_part(sections, "WHO YOU ARE", "PART A", "MY PREFERENCES")
        user = (f"SCRIPT:\n\"\"\"{script_text[:30000]}\"\"\"\n\nReturn JSON in this exact shape:\n"
                '{"main_subject": "...", "topics": [{"id": 1, "script_line": "...", '
                '"topic": "...", "what_to_show": "...", "search_queries": ["..."], '
                f'"keywords": ["..."]}}]}} Follow the PART A rules. At most {max_topics} topics, '
                "in script order.")
        plan = ai.ask_json(system, user, max_tokens=6000)
        if not plan or not plan.get("topics"):
            raise RuntimeError("Could not plan topics. Check your key / internet, or use Offline Brain.")
        return plan

    def pick_for_video(self, topic, video, lines, max_clips=3):
        provider = self.settings.get("ai_provider", "offline")
        if provider == "offline":
            brain = load_brain_for_run(self.data_dir)
            return pick_clips(topic, video, lines, brain, max_clips)
        sections = load_brain_text_for_run(self.data_dir)
        ai = AIProvider(self.settings)
        blocks = []
        cur, cur_start = [], None
        for ln in lines:
            if cur_start is None:
                cur_start = ln["start"]
            cur.append(ln["text"])
            if ln["start"] - cur_start >= 20:
                blocks.append(f"[{fmt_time(cur_start)}] {' '.join(cur)}")
                cur, cur_start = [], None
        if cur:
            blocks.append(f"[{fmt_time(cur_start)}] {' '.join(cur)}")
        system = brain_part(sections, "WHO YOU ARE", "PART B", "EXAMPLES", "MY PREFERENCES")
        user = (f"SCRIPT LINE: {topic.get('script_line')}\nTOPIC: {topic.get('topic')}\n"
                f"VIDEO: \"{video.get('title')}\" by {video.get('channel')}\nTRANSCRIPT:\n"
                + "\n".join(blocks)[:60000] +
                f"\nPick up to {max_clips} best clips. Return JSON: {{\"clips\": [{{"
                '"start": "m:ss", "end": "m:ss", "category": "...", "what_happens": "...", '
                '"key_quote": "...", "why_it_fits": "...", "relevance": 1-10, "interest": 1-10}}]}}')
        result = ai.ask_json(system, user, max_tokens=3000) or {}
        out = []
        for c in result.get("clips", []):
            s, e = parse_time(c.get("start")), parse_time(c.get("end"))
            if e <= s:
                e = s + 15
            out.append({"start": round(s, 1), "end": round(e, 1),
                        "category": c.get("category", "Background"),
                        "what_happens": c.get("what_happens", ""),
                        "key_quote": c.get("key_quote", ""),
                        "why_it_fits": c.get("why_it_fits", ""),
                        "relevance": float(c.get("relevance", 5)),
                        "interest": float(c.get("interest", 5))})
        return out

    # -- full run ---------------------------------------------------------
    def run(self, script_text: str, run_name: str, resume_from: dict | None = None):
        """Run a scan. Returns the run folder path. Saves partial results
        on stop/error so nothing is lost."""
        out_root = Path(self.settings.get("output_folder") or "broll_results")
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        out_dir = out_root / f"{run_name}_{stamp}" if not resume_from else Path(resume_from["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "script_transcript.txt").write_text(script_text, encoding="utf-8")

        if resume_from:
            plan = resume_from["plan"]
            all_clips = list(resume_from.get("clips", []))
            videos_seen = list(resume_from.get("videos_checked", []))
            done_ids = set(resume_from.get("done_topic_ids", []))
            images = list(resume_from.get("images", []))
        else:
            self._log("Planning moments from your script...")
            self.emit({"type": "stage", "stage": "plan"})
            plan = self.plan(script_text)
            all_clips, videos_seen, images, done_ids = [], [], [], set()
            self._log(f"Found {len(plan['topics'])} moments about: {plan.get('main_subject', '?')}")

        fetcher = self.get_fetcher()
        if getattr(fetcher, "blocked", False):
            self.videos_per_moment_effective = min(self.videos_per_moment_effective, 2)

        for topic in plan["topics"]:
            if self._stop:
                break
            if topic["id"] in done_ids:
                continue
            topic.setdefault("search_queries", [])
            topic.setdefault("keywords", [])
            self.emit({"type": "moment", "id": topic["id"], "status": "searching",
                       "topic": topic.get("topic", "")})
            self._log(f"\nMoment {topic['id']}: {topic.get('topic', '')}")
            candidates = {}
            search_blocked = False
            for q in topic.get("search_queries", []):
                if self._stop:
                    break
                try:
                    if self.search_func:
                        found = self.search_func(q, int(self.settings.get("results_per_search", 5)))
                    else:
                        found = youtube_search(
                            q, int(self.settings.get("results_per_search", 5)), self.cache_dir,
                            budget=self.budget, ytdlp_opts=self._ytdlp_opts(),
                            safe_mode=bool(self.settings.get("safe_mode", True)))
                    for v in found:
                        candidates.setdefault(v["video_id"], v)
                except RuntimeError as e:
                    search_blocked = True
                    self._log(str(e))
                    self.emit({"type": "search_blocked", "text": str(e)})
                    break
            if search_blocked:
                break

            scored = []
            for vid, v in candidates.items():
                if self._stop:
                    break
                rec = {**v, "topic_id": topic["id"], "status": ""}
                if v.get("duration") and v["duration"] > int(self.settings.get("max_video_minutes", 90)) * 60:
                    rec["status"] = "skipped: too long"
                    videos_seen.append(rec)
                    continue
                self.budget.use("transcript")
                lines = fetcher.get(vid, v.get("duration"))
                if fetcher.blocked and self.videos_per_moment_effective > 2:
                    self.videos_per_moment_effective = 2
                    self.emit({"type": "local_transcription",
                               "text": "Local transcription mode (YouTube is blocking transcripts). Slower but working."})
                if not lines:
                    rec["status"] = "no transcript"
                    videos_seen.append(rec)
                    continue
                blob = " ".join(l["text"] for l in lines).lower()
                rec["_lines"] = lines
                rec["_kw"] = sum(blob.count(k.lower()) for k in topic.get("keywords", []) if k)
                scored.append(rec)

            used_ids = {c["video_id"] for c in all_clips}
            scored.sort(key=lambda r: (r["video_id"] in used_ids, -r["_kw"]))
            to_read = scored[: self.videos_per_moment_effective]
            for r in scored[self.videos_per_moment_effective:]:
                r["status"] = "not read (lower keyword match)"
                videos_seen.append(r)

            self.emit({"type": "moment", "id": topic["id"], "status": "scoring"})
            for rec in to_read:
                if self._stop:
                    break
                self._log(f"  Reading: {rec['title'][:70]}")
                try:
                    found_clips = self.pick_for_video(
                        topic, rec, rec["_lines"], int(self.settings.get("clips_per_video", 3)))
                except Exception as e:  # noqa: BLE001
                    self._log(f"  Clip picking failed: {e}")
                    found_clips = []
                kept = 0
                for c in found_clips:
                    s, e = float(c["start"]), float(c["end"])
                    sc = score_clip(c.get("relevance", 5), c.get("interest", 5))
                    if sc < float(self.settings.get("min_score", 6)):
                        continue
                    kept += 1
                    clip = {"topic_id": topic["id"], "script_line": topic.get("script_line", ""),
                            "category": c.get("category", "Background"), "score": sc,
                            "start_s": s, "end_s": e, "start_str": fmt_time(s), "end_str": fmt_time(e),
                            "clip_url": clip_url(rec["video_id"], s),
                            "video_url": rec["url"], "video_id": rec["video_id"],
                            "video_title": rec["title"], "channel": rec["channel"],
                            "what_happens": c.get("what_happens", ""),
                            "key_quote": c.get("key_quote", ""),
                            "why_it_fits": c.get("why_it_fits", ""), "file": ""}
                    all_clips.append(clip)
                    self.emit({"type": "clip", "clip": clip})
                rec["status"] = f"read: {kept} clip(s) kept"
                videos_seen.append(rec)
            done_ids.add(topic["id"])
            self.emit({"type": "moment", "id": topic["id"], "status": "done",
                       "clips": sum(1 for c in all_clips if c["topic_id"] == topic["id"])})

            if self.settings.get("also_find_images") and self.image_func:
                try:
                    for im in self.image_func(topic):
                        images.append(im)
                        self.emit({"type": "image", "image": im})
                except Exception:
                    pass

            # Never lose work: save after every moment.
            save_results(out_dir, plan, all_clips, videos_seen, images)
            (out_dir / "resume.json").write_text(json.dumps(
                {"plan": plan, "clips": all_clips, "videos_checked": videos_seen,
                 "images": images, "done_topic_ids": sorted(done_ids),
                 "out_dir": str(out_dir)}, indent=2), encoding="utf-8")

        all_clips.sort(key=lambda c: (c["topic_id"], -c["score"]))
        result = save_results(out_dir, plan, all_clips, videos_seen, images)
        (out_dir / "resume.json").write_text(json.dumps(
            {"plan": plan, "clips": all_clips, "videos_checked": videos_seen,
             "images": images, "done_topic_ids": sorted(done_ids),
             "out_dir": str(out_dir)}, indent=2), encoding="utf-8")
        self._log(f"\nDONE! {len(all_clips)} clips. Excel file: {result['excel']}")
        self.emit({"type": "done", "out_dir": str(out_dir), "clips": len(all_clips),
                   "excel": result["excel"], "stopped": self._stop})
        return out_dir

    def download_all(self, out_dir: Path, clips: list[dict]) -> dict:
        return download_all_clips(clips, Path(out_dir) / "clips", log=self._log,
                                  should_stop=self.should_stop,
                                  ytdlp_opts=self._ytdlp_opts())
