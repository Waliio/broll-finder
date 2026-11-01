"""
Transcript waterfall for B-Roll Finder — keeps working when YouTube blocks transcripts.

Order for each video:
  1. Disk cache
  2. youtube-transcript-api              (fast, but YouTube blocks it often: IpBlocked / RequestBlocked)
  3. yt-dlp auto-subtitles               (fast, also blockable: HTTP 429)
  4. Audio + local Whisper (faster-whisper)  (slower, but free, no key, works when 2 and 3 are blocked)

A "circuit breaker" remembers when steps 2/3 are blocked during a run and skips straight to
step 4 for the rest of that run, so the app stops hammering YouTube and making the block worse.

All functions return transcript lines: [{"start": seconds, "text": str}, ...] or None.
Engine code calls TranscriptFetcher(...).get(video_id, duration_seconds).
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable

BLOCK_SIGNS = ("ipblocked", "requestblocked", "429", "too many requests",
               "sign in to confirm", "not a bot")


def _is_block(err: Exception | str) -> bool:
    msg = str(err).lower()
    return any(s in msg for s in BLOCK_SIGNS) or type(err).__name__ in ("IpBlocked", "RequestBlocked")


def parse_vtt(text: str) -> list[dict]:
    """Turn a WebVTT subtitle file into [{"start", "text"}], removing duplicate rolling lines."""
    lines, last = [], ""
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d+):(\d\d):(\d\d)[.,](\d+)\s+-->", block)
        if not m:
            continue
        start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)[:3]) / 1000
        body = "\n".join(l for l in block.splitlines() if "-->" not in l and not l.strip().isdigit())
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"\s+", " ", body).strip()
        if not body or body == last:
            continue
        if last and body.startswith(last):
            body = body[len(last):].strip()  # rolling auto-captions repeat the previous line
            if not body:
                continue
        lines.append({"start": round(start, 2), "text": body})
        last = body
    return lines


class TranscriptFetcher:
    def __init__(self, cache_dir: Path, ytdlp_opts: dict | None = None,
                 whisper_model: str = "base", whisper_max_minutes: int = 20,
                 use_whisper_fallback: bool = True, log: Callable[[str], None] = print,
                 should_stop: Callable[[], bool] = lambda: False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # extra yt-dlp options shared by every call: cookiesfrombrowser, proxy, ffmpeg_location ...
        self.ytdlp_opts = dict(ytdlp_opts or {})
        self.whisper_model_name = whisper_model
        self.whisper_max_minutes = whisper_max_minutes
        self.use_whisper = use_whisper_fallback
        self.log = log
        self.should_stop = should_stop
        self.blocked = False  # circuit breaker for steps 2 and 3
        self._whisper = None

    # ------------------------------------------------------------------ public
    def get(self, video_id: str, duration: float | None = None) -> list[dict] | None:
        cache = self.cache_dir / f"tr_{video_id}.json"
        if cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                pass

        lines, reasons = None, []
        if not self.blocked:
            for step in (self._from_api, self._from_subtitles):
                try:
                    lines = step(video_id)
                    if lines:
                        break
                except Exception as e:  # noqa: BLE001
                    reasons.append(f"{step.__name__[6:]}: {str(e).splitlines()[0][:120]}")
                    if _is_block(e):
                        self.blocked = True
                        self.log("YouTube is blocking transcripts on this internet. "
                                 "Switching to local transcription (slower, but it works).")
                        break

        if not lines and self.use_whisper and not self.should_stop():
            if duration and duration > self.whisper_max_minutes * 60 * 3:
                reasons.append("whisper: video too long, skipped")
            else:
                try:
                    lines = self._from_whisper(video_id)
                except Exception as e:  # noqa: BLE001
                    reasons.append(f"whisper: {str(e).splitlines()[0][:120]}")

        if lines:
            cache.write_text(json.dumps(lines), encoding="utf-8")
            return lines
        if reasons:
            self.log(f"[Transcript Failed] {video_id}: " + "; ".join(reasons))
        return None

    # ------------------------------------------------------------------ steps
    def _from_api(self, video_id: str) -> list[dict] | None:
        from youtube_transcript_api import YouTubeTranscriptApi
        kwargs = {}
        proxy = self.ytdlp_opts.get("proxy")
        if proxy:
            try:
                from youtube_transcript_api.proxies import GenericProxyConfig
                kwargs["proxy_config"] = GenericProxyConfig(http_url=proxy, https_url=proxy)
            except Exception:
                pass
        api = YouTubeTranscriptApi(**kwargs)
        try:
            fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        except Exception as e:
            if _is_block(e):
                raise
            tr = next(iter(api.list(video_id)))
            try:
                tr = tr.translate("en")
            except Exception:
                pass
            fetched = tr.fetch()
        return [{"start": s.start, "text": s.text} for s in fetched]

    def _from_subtitles(self, video_id: str) -> list[dict] | None:
        import yt_dlp
        with tempfile.TemporaryDirectory() as tmp:
            opts = {**self.ytdlp_opts, "quiet": True, "no_warnings": True, "skip_download": True,
                    "writesubtitles": True, "writeautomaticsubtitles": True,
                    "subtitleslangs": ["en", "en-orig", "en-US", "en-GB"], "subtitlesformat": "vtt",
                    "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s")}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            files = glob.glob(os.path.join(tmp, "*.vtt"))
            if not files:
                return None
            return parse_vtt(Path(files[0]).read_text(encoding="utf-8", errors="ignore")) or None

    def _from_whisper(self, video_id: str) -> list[dict] | None:
        import yt_dlp
        from yt_dlp.utils import download_range_func
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self.log(f"Loading local speech model '{self.whisper_model_name}' (first time downloads it)...")
            self._whisper = WhisperModel(self.whisper_model_name, device="auto", compute_type="int8")
        with tempfile.TemporaryDirectory() as tmp:
            opts = {**self.ytdlp_opts, "quiet": True, "no_warnings": True,
                    "format": "bestaudio[abr<=96]/bestaudio/worst",
                    "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
                    "download_ranges": download_range_func(None, [(0, self.whisper_max_minutes * 60)])}
            self.log(f"  Listening to the video audio ({self.whisper_max_minutes} min max)...")
            t0 = time.time()
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            files = [f for f in glob.glob(os.path.join(tmp, "*")) if not f.endswith(".part")]
            if not files:
                return None
            segments, _ = self._whisper.transcribe(files[0], vad_filter=True, beam_size=1)
            lines = []
            for seg in segments:
                if self.should_stop():
                    break
                text = seg.text.strip()
                if text:
                    lines.append({"start": round(seg.start, 2), "text": text})
            self.log(f"  Local transcript ready ({len(lines)} lines, {int(time.time() - t0)}s).")
            return lines or None
