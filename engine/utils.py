"""Small shared helpers: times, scoring, safe filenames."""
from __future__ import annotations

import re


def fmt_time(seconds) -> str:
    seconds = int(max(0, float(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_time(value) -> float:
    """Accept 75, '75', '1:15', '01:01:15' -> seconds (float)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    total = 0.0
    for p in nums:
        total = total * 60 + p
    return total


def score_clip(relevance, interest) -> float:
    """The locked formula from the brief: relevance*0.6 + interest*0.4."""
    return round(float(relevance) * 0.6 + float(interest) * 0.4, 1)


def clip_url(video_id: str, start_s: float) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(start_s)}s"


def safe_name(text: str, limit: int = 50) -> str:
    return re.sub(r"[^\w\- ]", "", text or "")[:limit].strip() or "clip"
