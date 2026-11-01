"""YouTube search + clip download, with Safe Mode (Final Update section 3).

Safe mode ON by default:
- random 3-5 s delay between YouTube requests
- max 40 YouTube requests per run (search + transcript + audio), counted and logged
- searches cached for 7 days, never request the same thing twice in that window
- optional browser cookies and proxy, passed to yt-dlp and to TranscriptFetcher
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from .utils import safe_name


class RequestBudget:
    """Counts YouTube requests for one run and stops politely at the limit."""

    def __init__(self, max_requests: int = 40, log=print):
        self.max_requests = int(max_requests)
        self.used = 0
        self.log = log

    def use(self, what: str = "request") -> bool:
        self.used += 1
        if self.used > self.max_requests:
            self.log(f"YouTube request limit reached ({self.max_requests}). "
                     "Stopping new requests; results so far are saved.")
            return False
        return True

    def status(self) -> str:
        return f"{self.used} / {self.max_requests} YouTube requests used"


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"search_{key}.json"


def youtube_search(query: str, n: int, cache_dir: Path,
                   budget: RequestBudget | None = None,
                   ytdlp_opts: dict | None = None,
                   delay: float = 1.5, safe_mode: bool = True) -> list[dict]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = "".join(c if c.isalnum() else "_" for c in query.lower())[:80]
    cache = _cache_path(cache_dir, key)
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - data.get("_ts", 0) < 7 * 24 * 3600:
                return data["results"]
        except Exception:
            pass
    if budget and not budget.use(f"search: {query}"):
        return []
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("YouTube search is not available in this build.") from e
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
            "skip_download": True, **(ytdlp_opts or {})}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    except Exception as e:
        # Search itself blocked -> the UI shows the "YouTube Request Blocked" popup.
        raise RuntimeError(
            "YouTube is limiting requests from your internet. "
            "Wait 30-60 minutes or switch networks (for example a mobile hotspot). "
            f"Details: {e}") from e
    out = []
    for e in (data or {}).get("entries") or []:
        vid = e.get("id")
        if not vid or len(vid) != 11:
            continue
        out.append({
            "video_id": vid, "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration") or 0,
            "views": e.get("view_count") or 0,
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    cache.write_text(json.dumps({"_ts": time.time(), "results": out}), encoding="utf-8")
    if safe_mode:
        time.sleep(random.uniform(3, 5))
    elif delay:
        time.sleep(delay)
    return out


def download_clip(video_url: str, start: float, end: float, out_path: Path,
                  pad: float = 2.0, ytdlp_opts: dict | None = None) -> Path:
    """Download one clip range as MP4 (max 1080p), start/end padded by `pad`."""
    import yt_dlp
    from yt_dlp.utils import download_range_func
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    opts = {"quiet": True, "no_warnings": True,
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "outtmpl": str(out_path.with_suffix(".%(ext)s")),
            "download_ranges": download_range_func(None, [(max(0, start - pad), end + pad)]),
            "force_keyframes_at_cuts": True, "merge_output_format": "mp4",
            **(ytdlp_opts or {})}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video_url])
    mp4 = out_path.with_suffix(".mp4")
    return mp4 if mp4.exists() else out_path


def download_all_clips(clips: list[dict], clips_dir: Path, log=print,
                       should_stop=lambda: False, ytdlp_opts: dict | None = None) -> dict:
    """One-click Download All Clips: skips files already downloaded, skips
    failures and continues, returns a plain summary for the UI."""
    clips_dir = Path(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)
    done, failed = 0, []
    for i, c in enumerate(clips, 1):
        if should_stop():
            break
        name = f"{i:02d}_Moment{c.get('topic_id', '')}_{safe_name(c.get('category', ''), 20)}_" \
               f"{safe_name(c.get('video_title', ''), 40)}"
        target = clips_dir / f"{name}.mp4"
        if target.exists():
            done += 1
            continue
        log(f"Downloading {i} of {len(clips)}: {name}")
        try:
            download_clip(c["video_url"], float(c["start_s"]), float(c["end_s"]),
                          target, ytdlp_opts=ytdlp_opts)
            c["file"] = target.name
            done += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name}: {str(e)[:100]}")
            c["file"] = "download failed"
    return {"downloaded": done, "failed": len(failed), "failures": failed}
