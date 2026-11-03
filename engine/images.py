"""Images from Wikimedia Commons + Openverse. No keys required."""

from __future__ import annotations

import urllib.parse
import urllib.request
import json

COMMERCIAL_LICENSES = {"cc-by", "cc-by-sa", "cc0", "pdm", "public-domain", "by", "by-sa"}


def _get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "BRollFinder/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ok_license(lic: str, commercial_only: bool) -> bool:
    if not commercial_only:
        return True
    return lic.lower().replace(" ", "") in COMMERCIAL_LICENSES or "cc-by" in lic.lower() or "public" in lic.lower()


def search_wikimedia(query: str, limit: int = 8, commercial_only: bool = True) -> list[dict]:
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": "6", "gsrlimit": str(limit),
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1280",
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except Exception:
        return []
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if int(info.get("width", 0)) < 1280:
            continue
        meta = info.get("extmetadata", {})
        lic = str(meta.get("LicenseShortName", {}).get("value", ""))
        if not _ok_license(lic, commercial_only):
            continue
        artist = str(meta.get("Artist", {}).get("value", ""))
        out.append(
            {
                "title": page.get("title", ""),
                "url": info.get("thumburl") or info.get("url", ""),
                "source": "Wikimedia Commons",
                "author": artist,
                "license": lic,
                "attribution": f"{page.get('title', '')} — {artist} ({lic}), Wikimedia Commons",
            }
        )
    return out


def search_openverse(query: str, limit: int = 8, commercial_only: bool = True) -> list[dict]:
    params = {"q": query, "page_size": str(limit)}
    if commercial_only:
        params["license_type"] = "commercial"
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except Exception:
        return []
    out = []
    for item in data.get("results", []):
        if int(item.get("width", 0) or 0) < 1280:
            continue
        lic = str(item.get("license", ""))
        if not _ok_license(lic, commercial_only):
            continue
        out.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": "Openverse",
                "author": item.get("creator", ""),
                "license": lic,
                "attribution": item.get("attribution", "") or f"{item.get('title', '')} ({lic})",
            }
        )
    return out


def find_images_for_moment(topic: str, limit: int = 6, commercial_only: bool = True) -> list[dict]:
    seen, out = set(), []
    for fn in (search_wikimedia, search_openverse):
        for img in fn(topic, limit=limit, commercial_only=commercial_only):
            if img["url"] and img["url"] not in seen:
                seen.add(img["url"])
                out.append(img)
    return out[:limit]
