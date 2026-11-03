"""Small pure helpers: time formatting/parsing and clip scoring."""

from __future__ import annotations


def fmt_time(seconds: float) -> str:
    """Seconds -> 'm:ss' (e.g. 75 -> '1:15')."""
    total = max(0, int(round(float(seconds))))
    return f"{total // 60}:{total % 60:02d}"


def parse_time(text: str) -> float:
    """'m:ss' or 'h:mm:ss' -> seconds. Plain numbers pass through."""
    text = str(text).strip()
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return 0.0
    return 0.0


def clip_url(video_id: str, start_s: float) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(start_s)}s"


def score_clip(relevance: float, interest: float) -> float:
    """Locked formula: relevance x 0.6 + interest x 0.4, capped at 10."""
    return round(min(10.0, float(relevance) * 0.6 + float(interest) * 0.4), 2)
