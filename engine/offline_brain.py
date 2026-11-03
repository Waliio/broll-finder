"""Offline Brain: rule-based planning and clip scoring, no API key.

Rules come from the brain YAML (see engine/default_brain.py for the
embedded copy). plan_moments() turns script sentences into moments;
pick_clips() scores transcript windows against a moment.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml


def load_brain(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_brain(data)
    return data


def load_brain_from_text(text: str) -> dict:
    data = yaml.safe_load(text)
    validate_brain(data)
    return data


def load_brain_for_run(data_dir: str | Path) -> dict:
    """Brain for a scan. Public builds use the embedded brain only, so
    no readable brain file ever has to exist on the user's PC."""
    try:
        from engine.settings import is_public_build

        public = is_public_build()
    except Exception:
        public = False
    if public:
        from engine.default_brain import DEFAULT_BRAIN_YAML

        return load_brain_from_text(DEFAULT_BRAIN_YAML)
    return load_brain(Path(data_dir) / "brain_rules.yaml")


def validate_brain(b: dict) -> None:
    if not isinstance(b, dict):
        raise ValueError("The brain file is empty or not valid YAML.")
    for key in ("script", "clips", "sources"):
        if key not in b:
            raise ValueError(f"The brain file is missing the '{key}:' section.")
    if not b["clips"].get("categories"):
        raise ValueError("The brain file has no clip categories.")
    if not b["script"].get("events"):
        raise ValueError("The brain file has no script events.")


@lru_cache(maxsize=4096)
def _phrase_re(phrase: str) -> re.Pattern:
    p = phrase.lower().strip()
    body = re.escape(p).replace(r"\ ", r"\s+")
    left = r"\b" if re.match(r"\w", p) else ""
    right = r"\b" if re.search(r"\w$", p) else ""
    return re.compile(left + body + right)


def _count(text_lower: str, phrase: str) -> int:
    return len(_phrase_re(str(phrase)).findall(text_lower))


def _has(text_lower: str, phrase: str) -> bool:
    return _phrase_re(str(phrase)).search(text_lower) is not None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _full_names(text: str, not_names: set[str]) -> list[str]:
    found = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b", text):
        name = m.group(1)
        words = name.split()
        if any(w in not_names for w in words):
            continue
        if name not in found:
            found.append(name)
    return found


def plan_moments(script_text: str, brain: dict, max_topics: int = 15) -> dict:
    """Return {"main_subject": ..., "topics": [...]}.

    Main subject: the full name whose first name is mentioned most.
    A moment needs a name or a year plus an event word. Topic label:
    the winning event group's words (award groups get an "award" suffix,
    business groups keep their first two words in brain-list order, e.g.
    "bought rights").
    """
    cfg = brain["script"]
    not_names = set(cfg.get("not_names", []))
    skip_res = [re.compile(p, re.IGNORECASE) for p in cfg.get("skip_sentence_patterns", [])]
    events = cfg.get("events", {})
    sentences = [s for s in _sentences(script_text) if not any(r.search(s) for r in skip_res)]
    if not sentences:
        return {"main_subject": "", "topics": []}

    names = _full_names(script_text, not_names)
    # Main subject by first-name mention count.
    counts: Counter = Counter()
    for name in names:
        first = name.split()[0]
        counts[name] = len(re.findall(rf"\b{re.escape(first)}\b", script_text))
    main = counts.most_common(1)[0][0] if counts else ""

    topics = []
    max_sent = int(cfg.get("max_sentences_per_moment", 2))
    for sent in sentences:
        if len(topics) >= max_topics:
            break
        low = sent.lower()
        years = re.findall(r"\b(?:19|20)\d{2}\b", sent)
        sent_names = [n for n in names if n.lower() in low]
        if not sent_names and not years:
            continue
        # Winning event group: first group (brain order) with a word hit,
        # preferring non-generic groups.
        win_group = None
        win_words: list[str] = []
        for gname, g in events.items():
            words = [w for w in g.get("words", []) if _has(low, str(w))]
            if words:
                if not g.get("generic"):
                    win_group, win_words = gname, words
                    break
                if win_group is None:
                    win_group, win_words = gname, words
        if win_group is None:
            continue
        group = events[win_group]
        if win_group == "award_show":
            label = f"{win_words[0]} award"
        elif win_group == "business":
            label = " ".join(win_words[:2])
        else:
            label = win_words[0]
        person = next((n for n in sent_names if n != main), sent_names[0] if sent_names else main)
        year = years[0] if years else ""
        topic = f"{person}: {label} {year}".strip() if person else f"{label} {year}".strip()
        extra = " ".join(group.get("query_words", [])[:2])
        queries = []
        for tmpl in cfg.get("query_templates", ["{main} {names} {event} {year}"]):
            q = tmpl.format(main=main, names=person, event=label, year=year, extra=extra)
            q = " ".join(q.split())
            words = q.split()[: int(cfg.get("max_query_words", 9))]
            q = " ".join(words)
            if q and q not in queries:
                queries.append(q)
        queries = queries[: int(cfg.get("queries_per_moment", 2))]
        topics.append(
            {
                "id": len(topics) + 1,
                "script_line": sent,
                "topic": topic,
                "what_to_show": group.get("show", ""),
                "search_queries": queries,
                "keywords": sorted(set(win_words + [w.lower() for w in sent_names] + years)),
            }
        )
    return {"main_subject": main, "topics": topics}


def pick_clips(topic: dict, video: dict, lines: list[dict], brain: dict, max_clips: int = 3) -> list[dict]:
    """Score sliding transcript windows; return up to max_clips clips."""
    from engine.utils import fmt_time, score_clip

    cfg = brain["clips"]
    window = float(cfg.get("window_seconds", 30))
    step = float(cfg.get("step_seconds", 10))
    min_len = float(cfg.get("min_length", 8))
    max_len = float(cfg.get("max_length", 40))
    pre_roll = float(cfg.get("pre_roll", 2))
    min_gap = float(cfg.get("min_gap_between_clips", 20))
    min_rel = float(cfg.get("min_relevance", 3))
    require = bool(cfg.get("require_name_or_year", True))
    pts = cfg.get("relevance_points", {})
    rel_per = float(cfg.get("relevance_per_point", 1.2))
    int_per = float(cfg.get("interest_per_point", 1.0))
    categories = cfg.get("categories", {})
    penalties = cfg.get("penalties", {})
    pen_phrases = penalties.get("phrases", [])
    duration = float(video.get("duration") or 0)

    if not lines:
        return []
    lines = sorted(lines, key=lambda ln: float(ln.get("start", 0)))
    topic_names = [k for k in topic.get("keywords", [])]
    topic_text = (topic.get("topic", "") + " " + topic.get("script_line", "")).lower()
    title = str(video.get("title", "")).lower()
    channel = str(video.get("channel", "")).lower()
    trusted = brain.get("sources", {}).get("trusted_channels", {})
    trusted_names = [str(n).lower() for n in trusted.get("names", [])]
    trusted_bonus = float(trusted.get("bonus", 0))
    good_words = [str(w).lower() for w in brain.get("sources", {}).get("good_title_words", {}).get("words", [])]
    good_bonus = float(brain.get("sources", {}).get("good_title_words", {}).get("bonus", 0))
    bad_words = [str(w).lower() for w in brain.get("sources", {}).get("bad_title_words", {}).get("words", [])]
    bad_pen = float(brain.get("sources", {}).get("bad_title_words", {}).get("penalty", 0))

    candidates = []
    t = float(lines[0].get("start", 0))
    end_t = float(lines[-1].get("start", 0))
    while t <= end_t:
        win_lines = [ln for ln in lines if t <= float(ln.get("start", 0)) < t + window]
        if win_lines:
            text = " ".join(str(ln.get("text", "")) for ln in win_lines)
            low = text.lower()
            start_s = max(0.0, float(win_lines[0].get("start", 0)) - pre_roll)
            end_s = min(start_s + max_len, float(win_lines[-1].get("start", 0)) + 10)
            if end_s - start_s >= min_len:
                # Relevance
                points = 0.0
                found_name = False
                for kw in topic_names:
                    if _has(low, kw):
                        found_name = True
                        if kw in topic_text:
                            points += float(pts.get("name", 3))
                        else:
                            points += float(pts.get("other_keyword", 1))
                main = topic.get("main_subject", "") if isinstance(topic.get("main_subject"), str) else ""
                # Main subject comes via topic keywords in practice; keep generic:
                for w in topic.get("keywords", []):
                    if re.search(r"\b(?:19|20)\d{2}\b", w) and _has(low, w):
                        points += float(pts.get("year", 2))
                for w in topic.get("keywords", []):
                    if w not in topic_names:
                        continue
                if any(_has(title, kw) for kw in topic_names):
                    points += float(pts.get("title_match", 1))
                relevance = min(10.0, points * rel_per)
                # Interest: best category
                best_cat, best_score = "Background", 0.0
                for cat, cdef in categories.items():
                    s = float(cdef.get("weight", 1)) * sum(_count(low, ph) for ph in cdef.get("phrases", []))
                    if s > best_score:
                        best_cat, best_score = cat, s
                interest = best_score * int_per
                for pen in pen_phrases:
                    if _has(low, str(pen.get("phrase", ""))):
                        interest -= float(pen.get("points", 0))
                if duration and start_s < float(penalties.get("intro_seconds", 15)):
                    interest -= float(penalties.get("intro_penalty", 2))
                if duration and end_s > duration - float(penalties.get("outro_seconds", 30)):
                    interest -= float(penalties.get("outro_penalty", 2))
                if any(n in channel for n in trusted_names):
                    interest += trusted_bonus
                if any(w in title for w in good_words):
                    interest += good_bonus
                if any(w in title for w in bad_words):
                    interest -= bad_pen
                interest = max(0.0, min(10.0, interest))
                if relevance >= min_rel and (not require or found_name):
                    score = score_clip(relevance, interest)
                    candidates.append(
                        {
                            "start": start_s,
                            "end": end_s,
                            "start_str": fmt_time(start_s),
                            "end_str": fmt_time(end_s),
                            "category": best_cat,
                            "what_happens": text[:220],
                            "key_quote": win_lines[0].get("text", "") if win_lines else "",
                            "why_it_fits": f"Matches {topic.get('topic', '')} ({best_cat}).",
                            "relevance": round(relevance, 2),
                            "interest": round(interest, 2),
                            "score": score,
                        }
                    )
        t += step

    candidates.sort(key=lambda c: -c["score"])
    picked = []
    for cand in candidates:
        if all(abs(cand["start"] - p["start"]) >= min_gap for p in picked):
            picked.append(cand)
        if len(picked) >= max_clips:
            break
    return picked
