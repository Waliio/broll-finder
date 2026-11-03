"""Scan pipeline: plan -> search -> transcripts -> score -> export.

Saves after EVERY moment (Excel + JSON + resume.json), so Stop/Resume
never loses work.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.ai import AIProvider
from engine.brain_text import brain_part, load_brain_text_for_run
from engine.settings import ensure_user_files
from engine.export import save_results
from engine.offline_brain import load_brain_for_run, pick_clips, plan_moments
from engine.transcript_fallback import TranscriptFetcher
from engine.utils import clip_url, score_clip
from engine.youtube import RequestBudget, download_all_clips, youtube_search


class Pipeline:
    def __init__(self, settings: dict, data_dir: Path, log=print,
                 emit=lambda event: None, search_func=None, transcript_fetcher=None,
                 image_func=None):
        self.settings = settings
        # Guarantee the brain file exists (private) before any scan step.
        # Public builds: ensure_user_files writes no brain file, and the
        # for_run loaders use the embedded brain instead.
        self.data_dir = ensure_user_files(Path(data_dir))
        self.cache_dir = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log = log
        self.emit = emit
        self._stop = False
        self.budget = RequestBudget(int(settings.get("max_youtube_requests", 40)), log=log)
        self.search_func = search_func
        self.image_func = image_func
        self._fetcher = transcript_fetcher

    def stop(self):
        self._stop = True

    def should_stop(self):
        return self._stop

    def _log(self, msg: str):
        self.log(msg)
        self.emit({"type": "log", "text": msg})

    def get_fetcher(self) -> TranscriptFetcher:
        if self._fetcher is not None:
            return self._fetcher
        self._fetcher = TranscriptFetcher(
            self.cache_dir,
            ytdlp_opts={"proxy": self.settings.get("proxy", "")},
            whisper_model=self.settings.get("whisper_fallback_model", "base"),
            whisper_max_minutes=int(self.settings.get("whisper_max_minutes", 20)),
            use_whisper_fallback=bool(self.settings.get("use_whisper_fallback", True)),
            log=self._log, should_stop=self.should_stop)
        return self._fetcher

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
            if cur_start is None:
                cur_start = ln["start"]
            if ln["start"] - cur_start >= 20:
                blocks.append(f"[{ln['start']}] {' '.join(cur)}")
                cur, cur_start = [], None
        if cur:
            blocks.append(" ".join(cur))
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
            from engine.utils import parse_time

            s, e = parse_time(str(c.get("start", "0:00"))), parse_time(str(c.get("end", "0:00")))
            out.append({
                "start": s, "end": e, "category": c.get("category", ""),
                "what_happens": c.get("what_happens", ""), "key_quote": c.get("key_quote", ""),
                "why_it_fits": c.get("why_it_fits", ""), "relevance": c.get("relevance", 0),
                "interest": c.get("interest", 0),
                "score": score_clip(c.get("relevance", 0), c.get("interest", 0)),
            })
        return out

    def run(self, script_text: str, run_name: str, resume_from: Path | None = None) -> Path:
        out_root = Path(self.settings.get("output_folder") or (Path.home() / "Documents" / "B-Roll Finder"))
        out_dir = out_root / run_name
        out_dir.mkdir(parents=True, exist_ok=True)
        done_ids: set[int] = set()
        clips: list[dict] = []
        videos_checked: list[dict] = []
        images: list[dict] = []
        if resume_from and Path(resume_from).exists():
            try:
                prev = json.loads(Path(resume_from).read_text(encoding="utf-8"))
                done_ids = set(prev.get("done_topic_ids", []))
                clips = prev.get("clips", [])
                videos_checked = prev.get("videos_checked", [])
                images = prev.get("images", [])
            except Exception:
                pass
        self._log("Planning moments...")
        plan = self.plan(script_text)
        topics = plan.get("topics", [])
        self.emit({"type": "plan", "main_subject": plan.get("main_subject", ""), "topics": topics})
        min_score = float(self.settings.get("min_score", 6.0))
        videos_per = int(self.settings.get("videos_per_moment", 4))
        clips_per_video = int(self.settings.get("clips_per_video", 3))
        max_minutes = float(self.settings.get("max_video_minutes", 90))
        fetcher = self.get_fetcher()
        for topic in topics:
            if self._stop:
                break
            tid = int(topic.get("id", 0))
            if tid in done_ids:
                continue
            self.emit({"type": "moment", "id": tid, "topic": topic.get("topic", ""), "status": "searching", "clips": 0})
            queries = topic.get("search_queries", []) or [topic.get("topic", "")]
            found_videos: list[dict] = []
            for q in queries:
                if self.search_func:
                    found_videos += self.search_func(q, videos_per)
                else:
                    found_videos += youtube_search(
                        q, videos_per, self.cache_dir, budget=self.budget,
                        safe_mode=bool(self.settings.get("safe_mode", True)), log=self._log)
                if len(found_videos) >= videos_per:
                    break
            seen, videos = set(), []
            for v in found_videos:
                if v.get("video_id") in seen:
                    continue
                seen.add(v.get("video_id"))
                if max_minutes and float(v.get("duration") or 0) > max_minutes * 60:
                    continue
                videos.append(v)
            videos = videos[:videos_per]
            for v in videos:
                videos_checked.append({"topic": topic.get("topic", ""), **v})
            topic_clip_count = 0
            for video in videos:
                if self._stop:
                    break
                try:
                    lines = fetcher.get(str(video.get("video_id", "")), video.get("duration"))
                except Exception as exc:
                    self._log(f"Transcript failed for {video.get('title', '')}: {exc}")
                    continue
                picked = self.pick_for_video(topic, video, lines, clips_per_video)
                for c in picked:
                    if c["score"] < min_score:
                        continue
                    clip = {
                        "topic_id": tid, "topic": topic.get("topic", ""),
                        "script_line": topic.get("script_line", ""),
                        "video_id": video.get("video_id", ""),
                        "video_title": video.get("title", ""), "channel": video.get("channel", ""),
                        "start": c["start"], "end": c["end"],
                        "start_str": c.get("start_str") or "", "end_str": c.get("end_str") or "",
                        "category": c["category"], "score": c["score"],
                        "what_happens": c["what_happens"], "key_quote": c["key_quote"],
                        "why_it_fits": c["why_it_fits"],
                        "clip_url": clip_url(str(video.get("video_id", "")), c["start"]),
                        "video_url": f"https://www.youtube.com/watch?v={video.get('video_id', '')}",
                        "rejected": False,
                    }
                    if not clip["start_str"]:
                        from engine.utils import fmt_time

                        clip["start_str"], clip["end_str"] = fmt_time(c["start"]), fmt_time(c["end"])
                    clips.append(clip)
                    topic_clip_count += 1
                    self.emit({"type": "clip", "clip": clip})
            if self.settings.get("also_find_images"):
                try:
                    if self.image_func:
                        found_images = self.image_func(topic.get("topic", ""))
                    else:
                        from engine.images import find_images_for_moment

                        found_images = find_images_for_moment(
                            topic.get("topic", ""),
                            commercial_only=bool(self.settings.get("commercial_images_only", True)))
                    for im in found_images:
                        images.append({"topic": topic.get("topic", ""), **im})
                        self.emit({"type": "image", "image": images[-1]})
                except Exception as exc:
                    self._log(f"Images failed for {topic.get('topic', '')}: {exc}")
            done_ids.add(tid)
            self.emit({"type": "moment", "id": tid, "topic": topic.get("topic", ""), "status": "done", "clips": topic_clip_count})
            save_results(out_dir, run_name, clips, topics, videos_checked, images)
            (out_dir / "resume.json").write_text(json.dumps({
                "run_name": run_name, "done_topic_ids": sorted(done_ids),
                "clips": clips, "videos_checked": videos_checked, "images": images,
                "topics": topics,
            }, indent=2), encoding="utf-8")
        save_results(out_dir, run_name, clips, topics, videos_checked, images)
        self.emit({"type": "done", "out_dir": str(out_dir), "clips": len(clips)})
        self._log(f"Done. {len(clips)} clips saved to {out_dir}")
        return out_dir
