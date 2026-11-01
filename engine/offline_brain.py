"""
Offline Brain for B-Roll Finder — works with NO API key and NO internet AI.

It replaces the two AI steps of the pipeline with rules from brain_rules.yaml:

    plan_moments(script_text, brain)            -> same shape as the AI planner
    pick_clips(topic, video, lines, brain, n)   -> same shape as the AI clip picker

`lines` is the transcript as a list of {"start": seconds, "text": str}.
Returned clips use the same keys the rest of the app already expects:
start, end, category, what_happens, key_quote, why_it_fits, relevance, interest.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml


# --------------------------------------------------------------------------- brain
def load_brain(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_brain(data)
    return data


def validate_brain(b: dict) -> None:
    """Raise ValueError with a plain message if the brain file is broken."""
    if not isinstance(b, dict):
        raise ValueError("The brain file is empty or not valid YAML.")
    for key in ("script", "clips", "sources"):
        if key not in b:
            raise ValueError(f"The brain file is missing the '{key}:' section.")
    if not b["clips"].get("categories"):
        raise ValueError("The brain file has no clip categories.")
    if not b["script"].get("events"):
        raise ValueError("The brain file has no script events.")


# --------------------------------------------------------------------------- text helpers
@lru_cache(maxsize=4096)
def _phrase_re(phrase: str) -> re.Pattern:
    p = phrase.lower().strip()
    body = re.escape(p).replace(r"\ ", r"\s+")
    left = r"\b" if re.match(r"\w", p) else ""
    right = r"\b" if re.search(r"\w$", p) else ""
    return re.compile(left + body + right)


def count_phrase(text_lower: str, phrase: str) -> int:
    return len(_phrase_re(str(phrase)).findall(text_lower))


def has_phrase(text_lower: str, phrase: str) -> bool:
    return _phrase_re(str(phrase)).search(text_lower) is not None


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[\"“'A-Z0-9])", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


NAME_RE = re.compile(r"\b([A-Z][\w'’\-]*[a-zà-ÿ\w](?:\s+(?:[A-Z][\w'’\-]+|of|the|de|van|von|al|bin))*)")
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
QUOTE_RE = re.compile(r"[\"“]([^\"”]{2,60})[\"”]")


def mid_sentence_caps(sentences: list[str]) -> set[str]:
    """Words that appear capitalised somewhere other than the start of a sentence."""
    caps = set()
    for s in sentences:
        toks = re.findall(r"[\w'’\-]+", s)
        for w in toks[1:]:
            if w[:1].isupper():
                caps.add(re.sub(r"['’]s$", "", w))
    return caps


def extract_names(sentence: str, not_names: set[str], mid_caps: set[str] | None = None) -> list[str]:
    names = []
    lead = len(sentence) - len(sentence.lstrip(" \"“'"))
    for m in NAME_RE.finditer(sentence):
        words = m.group(1).split()
        # a single capitalised word that only starts the sentence is usually not a name
        if mid_caps is not None and m.start() <= lead and len(words) == 1 \
                and re.sub(r"['’]s$", "", words[0]) not in mid_caps:
            continue
        while words and (words[0] in not_names or words[0].lower() in {"of", "the"}):
            words = words[1:]
        while words and words[-1].lower() in {"of", "the", "de", "van", "von", "al", "bin"}:
            words = words[:-1]
        if not words:
            continue
        name = " ".join(words).rstrip("'’s").strip()
        name = re.sub(r"['’]s$", "", name)
        if len(name) < 2 or name.isdigit():
            continue
        names.append(name)
    for q in QUOTE_RE.findall(sentence):
        names.append(q.strip())
    out, seen = [], set()
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def find_events(sentence_lower: str, events: dict) -> list[tuple[str, str]]:
    """Return [(event_group, matched_word)] by priority: the order of groups in the
    brain file, with groups marked generic: true always after specific ones."""
    specific, generic = [], []
    for group, spec in events.items():
        for w in spec.get("words", []):
            if _phrase_re(str(w)).search(sentence_lower):
                (generic if spec.get("generic") else specific).append((group, str(w)))
                break
    return specific + generic


def _clean_query(words: list[str], max_words: int) -> str:
    out, seen = [], set()
    for chunk in words:
        for w in str(chunk).split():
            k = w.lower()
            if k and k not in seen:
                seen.add(k)
                out.append(w)
    return " ".join(out[:max_words])


# --------------------------------------------------------------------------- PART A
def plan_moments(script_text: str, brain: dict, max_topics: int = 15) -> dict:
    sb = brain["script"]
    not_names = set(sb.get("not_names", []))
    skip_res = [re.compile(p, re.I) for p in sb.get("skip_sentence_patterns", [])]
    events = sb["events"]

    sentences = [s for s in split_sentences(script_text) if not any(r.search(s) for r in skip_res)]
    mid_caps = mid_sentence_caps(sentences)

    # main subject = most mentioned name across the script
    counts = Counter()
    for s in sentences:
        for n in extract_names(s, not_names, mid_caps):
            counts[n] += 1
    # merge "Taylor" into "Taylor Swift" when one is part of the other
    for short in list(counts):
        for long in list(counts):
            if short != long and short in long.split():
                counts[long] += counts.pop(short, 0)
                break
    main = counts.most_common(1)[0][0] if counts else ""

    moments, carry_names, carry_year = [], [], ""
    i = 0
    max_sent = int(sb.get("max_sentences_per_moment", 2))
    while i < len(sentences):
        s = sentences[i]
        # "Then in May 2025, the story came full circle." -> join with the next sentence
        if i + 1 < len(sentences) and YEAR_RE.search(s) and not extract_names(s, not_names, mid_caps) \
                and not [g for g, _ in find_events(s.lower(), events) if not events[g].get("generic")]:
            sentences[i + 1] = s + " " + sentences[i + 1]
            i += 1
            continue
        low = s.lower()
        all_ev_words = {str(w).lower() for sp in events.values() for w in sp.get("words", [])}
        names = [n for n in extract_names(s, not_names, mid_caps)
                 if not (main and (n in main.split() or n == main))
                 and not any(part.lower() in all_ev_words for part in n.split())]
        years = YEAR_RE.findall(s)
        evs = find_events(low, events)
        specific_evs = [(g, w) for g, w in evs if not events[g].get("generic")]
        if not specific_evs and not years and not names:
            i += 1  # plain narration: nothing specific to show
            continue
        group = [s]
        my_groups = {g for g, _ in evs if not events[g].get("generic")}
        # pull in following sentences that continue this moment (no new event type, no new year)
        j = i + 1
        while len(group) < max_sent and j < len(sentences):
            nxt = sentences[j]
            nxt_groups = {g for g, _ in find_events(nxt.lower(), events) if not events[g].get("generic")}
            nxt_years = set(YEAR_RE.findall(nxt))
            if (nxt_groups - my_groups) or (nxt_years - set(years)):
                break
            group.append(nxt)
            j += 1
        if names:
            carry_names = names[:3] or carry_names
        if years:
            carry_year = years[0]
        moment_names = names[:2] or carry_names[:2]
        year = years[0] if years else carry_year
        ev_group, ev_word = evs[0] if evs else ("speech", "")
        group_low = " ".join(group).lower()
        spec_words = []
        for g, sp in events.items():
            if sp.get("generic"):
                continue
            for w in sp.get("words", []):
                w = str(w)
                if has_phrase(group_low, w) and not any(w in x or x in w for x in spec_words):
                    spec_words.append(w)
        if spec_words:
            ev_word = " ".join(spec_words[:2])
        spec = events.get(ev_group, {})
        extra = " ".join(spec.get("query_words", [])[:2])
        fill = {"main": main, "names": " ".join(moment_names), "year": year,
                "event": ev_word, "extra": extra}
        queries = []
        for tpl in sb.get("query_templates", []):
            q = _clean_query([tpl.format(**fill)], int(sb.get("max_query_words", 9)))
            if q and q.lower() not in [x.lower() for x in queries]:
                queries.append(q)
        queries = queries[: int(sb.get("queries_per_moment", 3))]
        keywords = list(dict.fromkeys(
            moment_names + ([main] if main else []) + ([year] if year else [])
            + [w for _, w in specific_evs] + spec_words[:4] + [q for q in QUOTE_RE.findall(s)]))
        topic_name = " ".join(x for x in [ev_word.title() if ev_word else "", year] if x) or \
            (moment_names[0] if moment_names else s[:40])
        if moment_names and ev_word:
            topic_name = f"{moment_names[0]}: {ev_word} {year}".strip()
        elif ev_word:
            topic_name = f"{ev_word.capitalize()} {year}".strip()
        moments.append({
            "id": len(moments) + 1,
            "script_line": " ".join(group),
            "topic": topic_name,
            "what_to_show": spec.get("show", "footage of this moment"),
            "search_queries": queries,
            "keywords": keywords,
            "_names": moment_names,
            "_main": main,
            "_year": year,
            "_events": list(dict.fromkeys([w for _, w in specific_evs] + spec_words[:4])),
        })
        i = j
        if len(moments) >= max_topics:
            break
    return {"main_subject": main, "topics": moments}


# --------------------------------------------------------------------------- PART B
def _segments(lines: list[dict]) -> list[dict]:
    segs = []
    clean = [l for l in lines if str(l.get("text", "")).strip()]
    for k, l in enumerate(clean):
        start = float(l["start"])
        end = float(clean[k + 1]["start"]) if k + 1 < len(clean) else start + 4
        text = re.sub(r"\s+", " ", str(l["text"]).replace("\n", " ")).strip()
        segs.append({"start": start, "end": max(end, start + 0.5), "text": text})
    return segs


def video_source_score(video: dict, brain: dict) -> tuple[float, float, list[str]]:
    """Return (interest_bonus, relevance_penalty, notes) for a whole video."""
    src = brain.get("sources", {})
    title = (video.get("title") or "").lower()
    channel = (video.get("channel") or "").lower()
    bonus, penalty, notes = 0.0, 0.0, []
    tc = src.get("trusted_channels", {})
    if any(n.strip() and n.lower().strip() in channel for n in tc.get("names", [])) or \
            any(n.lower() == " - topic" and channel.endswith(" - topic") for n in tc.get("names", [])):
        bonus += float(tc.get("bonus", 0))
        notes.append("trusted source")
    gw = src.get("good_title_words", {})
    if any(has_phrase(title, w) for w in gw.get("words", [])):
        bonus += float(gw.get("bonus", 0))
        notes.append("original/full footage")
    bw = src.get("bad_title_words", {})
    if any(str(w).lower() in title for w in bw.get("words", [])):
        penalty += float(bw.get("penalty", 0))
        notes.append("looks like commentary")
    return bonus, penalty, notes


def pick_clips(topic: dict, video: dict, lines: list[dict], brain: dict, max_clips: int = 3) -> list[dict]:
    cb = brain["clips"]
    prefs = brain.get("preferences", {}) or {}
    channel = (video.get("channel") or "").lower()
    if any(b and b.lower() in channel for b in prefs.get("blocked_channels", []) or []):
        return []

    segs = _segments(lines)
    if not segs:
        return []
    video_end = segs[-1]["end"]

    rp = cb.get("relevance_points", {})
    names = topic.get("_names") or []
    main = topic.get("_main") or ""
    year = topic.get("_year") or ""
    event_words = topic.get("_events") or []
    other = [k for k in topic.get("keywords", []) if k not in names and k != main and k != year
             and k not in event_words]
    kw_weights = ([(n, rp.get("name", 3)) for n in names]
                  + ([(main, rp.get("main_subject", 2))] if main else [])
                  + ([(year, rp.get("year", 2))] if year else [])
                  + [(e, rp.get("event_word", 2)) for e in event_words]
                  + [(o, rp.get("other_keyword", 1)) for o in other])
    # also match surnames alone ("West" for "Kanye West")
    for n in names + ([main] if main else []):
        parts = n.split()
        if len(parts) > 1 and len(parts[-1]) > 3:
            kw_weights.append((parts[-1], rp.get("name", 3) * 0.5))

    title_low = (video.get("title") or "").lower()
    title_bonus = rp.get("title_match", 1) * sum(1 for k, _ in kw_weights if has_phrase(title_low, k))
    src_bonus, src_penalty, src_notes = video_source_score(video, brain)

    cats = cb["categories"]
    pen = cb.get("penalties", {})
    boost = prefs.get("boost_phrases", []) or []
    win, step = float(cb.get("window_seconds", 30)), float(cb.get("step_seconds", 10))

    candidates = []
    t = segs[0]["start"]
    while t < video_end:
        in_win = [s for s in segs if s["start"] >= t and s["start"] < t + win]
        if in_win:
            text = " ".join(s["text"] for s in in_win)
            low = text.lower()
            # relevance
            matched = [(k, w) for k, w in kw_weights if has_phrase(low, k)]
            rel_raw = sum(w for _, w in {k: w for k, w in matched}.items()) + min(title_bonus, 3) - src_penalty
            # interest by category
            cat_scores, trig = {}, {}
            for cat, spec in cats.items():
                score, hits = 0.0, []
                for ph in spec.get("phrases", []):
                    c = count_phrase(low, ph)
                    if c:
                        score += float(spec.get("weight", 1)) * min(c, 2)
                        hits.append(str(ph))
                if score:
                    cat_scores[cat], trig[cat] = score, hits
            boost_raw = sum(2 for b in boost if has_phrase(low, b))
            pen_raw = sum(float(p.get("points", 0)) for p in pen.get("phrases", []) if has_phrase(low, p.get("phrase", "")))
            if t < float(pen.get("intro_seconds", 15)):
                pen_raw += float(pen.get("intro_penalty", 0))
            if t > video_end - float(pen.get("outro_seconds", 30)):
                pen_raw += float(pen.get("outro_penalty", 0))
            interest_raw = sum(cat_scores.values()) + boost_raw + src_bonus - pen_raw
            relevance = max(1.0, min(10.0, 1 + rel_raw * float(cb.get("relevance_per_point", 1.2)) - pen_raw * 0.5))
            interest = max(1.0, min(10.0, 1 + interest_raw * float(cb.get("interest_per_point", 1.0))))
            strong = {n.lower() for n in names + ([main] if main else []) + ([year] if year else [])}
            strong |= {n.split()[-1].lower() for n in names + ([main] if main else []) if len(n.split()) > 1}
            has_strong = any(k.lower() in strong for k, _ in matched)
            if relevance >= float(cb.get("min_relevance", 3)) and (has_strong or not cb.get("require_name_or_year", True)):
                category = max(cat_scores, key=cat_scores.get) if cat_scores else (
                    "Interview" if "interview" in title_low else "Background")
                candidates.append({
                    "t": t, "segs": in_win, "low": low, "relevance": round(relevance, 1),
                    "interest": round(interest, 1), "category": category,
                    "matched": [k for k, _ in matched], "triggers": trig.get(category, []),
                })
        t += step

    # turn every candidate window into a clip range, then keep the best non-overlapping ones
    candidates.sort(key=lambda c: c["relevance"] * 0.6 + c["interest"] * 0.4, reverse=True)
    gap = float(cb.get("min_gap_between_clips", 20))
    clips = []
    for c in candidates:
        segs_c = c["segs"]
        first = next((s for s in segs_c if any(has_phrase(s["text"].lower(), k) for k in c["matched"] + c["triggers"])), segs_c[0])
        start = max(0.0, first["start"] - float(cb.get("pre_roll", 2)))
        end = min(max(s["end"] for s in segs_c), start + float(cb.get("max_length", 40)))
        # keep going while the next lines still carry keywords or signals
        hit_words = c["matched"] + c["triggers"]
        for s_next in segs:
            if s_next["start"] < end - 0.01:
                continue
            if s_next["start"] - end > 3 or s_next["end"] - start > float(cb.get("max_length", 40)):
                break
            if any(has_phrase(s_next["text"].lower(), k) for k in hit_words):
                end = s_next["end"]
            else:
                break
        if end - start < float(cb.get("min_length", 8)):
            end = start + float(cb.get("min_length", 8))
        if any(start < o["end"] + gap and end > o["start"] - gap for o in clips):
            continue
        def seg_hits(s, c=c):
            low = s["text"].lower()
            return sum(1 for p in c["triggers"] + c["matched"] if has_phrase(low, p))
        best = max(segs_c, key=seg_hits)
        quote = " ".join(best["text"].split()[:20])
        kws = ", ".join(c["matched"][:4]) or "the topic"
        trig = ", ".join(dict.fromkeys(c["triggers"][:3]))
        why = f"Matches the script line ({kws})"
        if trig:
            why += f"; signals: {trig}"
        if src_notes:
            why += f"; {', '.join(src_notes)}"
        clips.append({
            "start": round(start, 1), "end": round(end, 1), "category": c["category"],
            "what_happens": f"{c['category']} moment mentioning {kws}.", "key_quote": quote,
            "why_it_fits": why + ".", "relevance": c["relevance"], "interest": c["interest"],
        })
        if len(clips) >= max_clips:
            break
    clips.sort(key=lambda x: x["start"])
    return clips
