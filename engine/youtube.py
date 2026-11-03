"""YouTube search and clip downloads via yt-dlp, with Safe Mode."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import time
from pathlib import Path


class RequestBudget:
    def __init__(self, max_requests: int = 40, log=print):
        self.max_requests = int(max_requests)
        self.used = 0
        self.log = log

    def check(self) -> bool:
        if self.used >= self.max_requests:
            self.log("YouTube request budget reached for this run.")
            return False
        return True

    def spend(self, n: int = 1):
        self.used += n


def _cache_file(cache_dir: Path, query: str) -> Path:
    key = hashlib.md5(query.encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"search_{key}.json"


def youtube_search(query: str, max_results: int, cache_dir: Path,
                   budget: RequestBudget | None = None, safe_mode: bool = True,
                   log=print) -> list[dict]:
    """Search YouTube. Returns [{video_id, title, channel, duration}]."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cf = _cache_file(cache_dir, query)
    if cf.exists():
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
            if time.time() - float(data.get("ts", 0)) <= 7 * 86400:
                return data["videos"][:max_results]
        except Exception:
            pass
    if budget is not None and not budget.check():
        return []
    if safe_mode:
        time.sleep(random.uniform(3, 5))
    cmd = [
        "yt-dlp", f"ytsearch{max_results}:{query}", "--flat-playlist",
        "--dump-json", "--no-warnings",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as exc:
        log(f"YouTube search failed: {exc}")
        return []
    videos = []
    for line in out.stdout.splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        videos.append(
            {
                "video_id": item.get("id", ""),
                "title": item.get("title", ""),
                "channel": item.get("channel") or item.get("uploader", ""),
                "duration": float(item.get("duration") or 0),
            }
        )
    if budget is not None:
        budget.spend()
    try:
        cf.write_text(json.dumps({"ts": time.time(), "videos": videos}), encoding="utf-8")
    except Exception:
        pass
    return videos[:max_results]


def download_clip(video_id: str, start_s: float, end_s: float, out_path: Path, log=print) -> bool:
    url = f"https://www.youtube.com/watch?v={video_id}"
    section = f"*{int(start_s)}-{int(end_s)}"
    cmd = [
        "yt-dlp", "--download-sections", section, "-f",
        "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "-o", str(out_path), url,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return res.returncode == 0 and out_path.exists()
    except Exception as exc:
        log(f"Clip download failed: {exc}")
        return False


def download_all_clips(clips: list[dict], out_dir: Path, log=print) -> list[str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for i, clip in enumerate(clips, 1):
        path = out_dir / f"clip_{i:02d}_{clip.get('video_id', 'video')}.mp4"
        if download_clip(str(clip.get("video_id", "")), float(clip.get("start", 0)),
                         float(clip.get("end", 0)), path, log=log):
            done.append(str(path))
    return done
