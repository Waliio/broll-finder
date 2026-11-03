"""Transcript fetching with fallback and a circuit breaker.

Order: 7-day cache -> youtube-transcript-api -> yt-dlp subtitles ->
download audio + local Whisper. After the first IpBlocked/429 the
fetcher switches to local-transcription mode for the rest of the run.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path


class IpBlockedError(Exception):
    pass


class RateLimitError(Exception):
    pass


def parse_vtt(text: str) -> list[dict]:
    """Parse WebVTT into [{start, text}]."""
    lines: list[dict] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        if "WEBVTT" in block and "-->" not in block:
            continue
        m = re.search(r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->", block)
        if not m:
            continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = h * 3600 + mi * 60 + s
        nl = block.find("\n", m.end())
        body = block[nl + 1 :].strip() if nl >= 0 else ""
        body = re.sub(r"<[^>]+>", "", body).replace("\n", " ").strip()
        if body:
            lines.append({"start": float(start), "text": body})
    # Merge lines with the same start (multi-line cues).
    merged: list[dict] = []
    for ln in lines:
        if merged and merged[-1]["start"] == ln["start"]:
            merged[-1]["text"] += " " + ln["text"]
        else:
            merged.append(dict(ln))
    return merged


def _is_blocked(exc: Exception) -> bool:
    name = type(exc).__name__
    msg = str(exc)
    return (
        isinstance(exc, (IpBlockedError, RateLimitError))
        or name in ("IpBlocked", "TooManyRequests", "RequestBlocked")
        or "429" in msg
        or "IpBlocked" in msg
    )


class TranscriptFetcher:
    def __init__(self, cache_dir: Path, ytdlp_opts: dict | None = None,
                 whisper_model: str = "base", whisper_max_minutes: int = 20,
                 use_whisper_fallback: bool = True, log=print, should_stop=lambda: False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ytdlp_opts = ytdlp_opts or {}
        self.whisper_model = whisper_model
        self.whisper_max_minutes = whisper_max_minutes
        self.use_whisper_fallback = use_whisper_fallback
        self.log = log
        self.should_stop = should_stop
        self.local_only = False

    def _cache_path(self, video_id: str) -> Path:
        return self.cache_dir / f"transcript_{video_id}.json"

    def _from_cache(self, video_id: str):
        p = self._cache_path(video_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - float(data.get("ts", 0)) > 7 * 86400:
                return None
            return data["lines"]
        except Exception:
            return None

    def _to_cache(self, video_id: str, lines: list[dict]):
        try:
            self._cache_path(video_id).write_text(
                json.dumps({"ts": time.time(), "lines": lines}), encoding="utf-8"
            )
        except Exception:
            pass

    def _from_api(self, video_id: str) -> list[dict]:
        from youtube_transcript_api import YouTubeTranscriptApi

        try:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        except Exception as exc:
            if _is_blocked(exc):
                raise IpBlockedError(str(exc)) from exc
            raise
        return [{"start": float(r["start"]), "text": r["text"]} for r in raw]

    def _from_subtitles(self, video_id: str) -> list[dict]:
        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = [
            "yt-dlp", "--write-auto-sub", "--sub-lang", "en", "--skip-download",
            "--convert-subs", "vtt", "-o", str(self.cache_dir / "%(id)s.%(ext)s"), url,
        ]
        if self.ytdlp_opts.get("proxy"):
            cmd += ["--proxy", str(self.ytdlp_opts["proxy"])]
        subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        vtt_files = sorted(self.cache_dir.glob(f"{video_id}*.vtt"))
        if not vtt_files:
            raise RuntimeError("No subtitles found.")
        return parse_vtt(vtt_files[0].read_text(encoding="utf-8", errors="ignore"))

    def _from_whisper(self, video_id: str) -> list[dict]:
        if not self.use_whisper_fallback:
            raise RuntimeError("Local Whisper fallback is off.")
        from faster_whisper import WhisperModel

        url = f"https://www.youtube.com/watch?v={video_id}"
        audio = self.cache_dir / f"{video_id}.mp3"
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", str(audio), url]
        subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if not audio.exists():
            raise RuntimeError("Could not download audio for local transcription.")
        model = WhisperModel(self.whisper_model, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio))
        lines = []
        for seg in segments:
            if seg.start > self.whisper_max_minutes * 60:
                break
            lines.append({"start": float(seg.start), "text": seg.text.strip()})
        return lines

    def get(self, video_id: str, duration: float | None = None) -> list[dict]:
        cached = self._from_cache(video_id)
        if cached is not None:
            return cached
        if self.local_only:
            lines = self._from_whisper(video_id)
            self._to_cache(video_id, lines)
            return lines
        for step, fn in (("api", self._from_api), ("subtitles", self._from_subtitles)):
            try:
                lines = fn(video_id)
                if lines:
                    self._to_cache(video_id, lines)
                    return lines
            except Exception as exc:
                if _is_blocked(exc):
                    self.local_only = True
                    self.log("Local transcription mode (YouTube is blocking transcripts). Slower but working.")
                    break
                self.log(f"Transcript step {step} failed: {exc}")
        lines = self._from_whisper(video_id)
        self._to_cache(video_id, lines)
        return lines
