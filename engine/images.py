"""Images with no API keys (Final Update section 7).

Sources: Wikimedia Commons API and Openverse API (anonymous), both with a
proper User-Agent. Filters: long side >= 1280 px, commercial-use licences
only when that setting is ON (CC0, Public Domain, CC BY, CC BY-SA),
no duplicates, no logos. Image requests do NOT count toward the
YouTube request limit.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

USER_AGENT = "BRollFinder/1.0 (https://example.com/broll-finder; contact: support@example.com)"
COMMERCIAL_LICENSES = {"cc0", "public domain", "pdm", "cc by", "cc by-sa", "cc-by", "cc-by-sa"}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _ok_license(lic: str, commercial_only: bool) -> bool:
    if not commercial_only:
        return True
    low = (lic or "").lower()
    return any(k in low for k in COMMERCIAL_LICENSES)


def search_wikimedia(query: str, limit: int = 8, commercial_only: bool = True) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search",
              "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": limit,
              "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1280}
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except Exception:
        return []
    out, seen = [], set()
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        width, height = info.get("width", 0), info.get("height", 0)
        if max(width, height) < 1280:
            continue
        meta = info.get("extmetadata", {}) or {}
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        if not _ok_license(lic, commercial_only):
            continue
        src = info.get("url", "")
        if not src or src in seen or "logo" in (page.get("title", "").lower()):
            continue
        seen.add(src)
        artist = (meta.get("Artist", {}) or {}).get("value", "")
        out.append({"source": "Wikimedia Commons", "url": src, "page_url": info.get("descriptionurl", ""),
                    "title": page.get("title", ""), "author": artist,
                    "license": lic or "Unknown",
                    "attribution": f"{page.get('title', '')} - {artist} - {lic} - {src}".strip()})
    return out


def search_openverse(query: str, limit: int = 8, commercial_only: bool = True) -> list[dict]:
    params = {"q": query, "page_size": limit,
              "license_type": "commercial" if commercial_only else "all",
              "filter_dead": "false"}
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except Exception:
        return []
    out, seen = [], set()
    for item in data.get("results", []) or []:
        src = item.get("url", "")
        if not src or src in seen:
            continue
        seen.add(src)
        out.append({"source": "Openverse", "url": src, "page_url": item.get("foreign_landing_url", ""),
                    "title": item.get("title", ""), "author": item.get("creator", ""),
                    "license": item.get("license", ""),
                    "attribution": item.get("attribution", "") or
                    f"{item.get('title', '')} by {item.get('creator', '')} ({item.get('license', '')})"})
    return out


def find_images_for_moment(topic: dict, commercial_only: bool = True) -> list[dict]:
    """Search with the moment's names, event words and year."""
    queries = []
    for part in (topic.get("_names") or []) + (topic.get("_events") or []):
        queries.append(str(part))
    if topic.get("_year"):
        queries.append(f"{topic.get('_main', '')} {topic['_year']}".strip())
    queries.append(topic.get("topic", ""))
    out, seen = [], set()
    for q in queries:
        if not q:
            continue
        for img in search_wikimedia(q, commercial_only=commercial_only) + \
                search_openverse(q, commercial_only=commercial_only):
            if img["url"] not in seen:
                seen.add(img["url"])
                out.append({**img, "topic_id": topic.get("id")})
            if len(out) >= 12:
                return out
    return out


def download_image(img: dict, dest) -> bool:
    try:
        req = urllib.request.Request(img["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return True
    except Exception:
        return False
