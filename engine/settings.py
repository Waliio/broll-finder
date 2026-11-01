"""Where the app stores its own files, and user settings.

Never writes inside the install folder. On Windows this is
%APPDATA%\\BRollFinder, on macOS ~/Library/Application Support/BRollFinder,
on Linux ~/.local/share/BRollFinder. Results go to Documents/B-Roll Finder
by default and can be changed in Settings.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

APP_NAME = "BRollFinder"
VERSION = "1.0.0"

DEFAULTS = {
    "ai_provider": "offline",  # offline | gemini | claude -- offline is the default, no key needed
    "gemini_api_key": "",
    "claude_api_key": "",
    "gemini_model": "gemini-flash-latest",
    "gemini_fallback_model": "gemini-flash-lite-latest",
    "claude_model": "claude-sonnet-4-5",
    "output_folder": "",
    "whisper_model": "small",
    "whisper_fallback_model": "base",
    "whisper_max_minutes": 20,
    "use_whisper_fallback": True,
    "max_moments": 15,
    "videos_per_moment": 4,
    "results_per_search": 5,
    "clips_per_video": 3,
    "min_score": 6.0,
    "max_video_minutes": 90,
    "safe_mode": True,
    "max_youtube_requests": 40,
    "delay_seconds": 1.5,
    "also_find_images": True,
    "commercial_images_only": True,
    "auto_download_clips": False,
    "cookies_from_browser": "",
    "proxy": "",
    "check_updates_url": "",
}


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if os.name == "posix" and "darwin" in os.uname().sysname.lower():
        return Path.home() / "Library" / "Application Support" / APP_NAME
    try:
        from platformdirs import user_data_dir as _pdd
        return Path(_pdd(APP_NAME))
    except Exception:
        return Path.home() / ".local" / "share" / APP_NAME


def documents_dir() -> Path:
    return Path.home() / "Documents" / "B-Roll Finder"


def resource_path(name: str) -> Path:
    """Bundled file: next to the frozen app, else next to this package."""
    here = Path(__file__).resolve()
    for cand in (here.parent.parent / "resources" / name,
                 Path.cwd() / "resources" / name):
        if cand.exists():
            return cand
    return here.parent.parent / "resources" / name


def ensure_user_files(data_dir: Path | None = None) -> Path:
    """Copy bundled brains to the user folder on first run. Returns data dir."""
    data_dir = Path(data_dir) if data_dir else user_data_dir()
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    for name in ("brain_rules.yaml", "brain.txt"):
        dest = data_dir / name
        if not dest.exists():
            src = resource_path(name)
            if src.exists():
                shutil.copyfile(src, dest)
    return data_dir


def load_settings(data_dir: Path | None = None) -> dict:
    data_dir = ensure_user_files(data_dir)
    path = data_dir / "settings.json"
    settings = dict(DEFAULTS)
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except Exception:
            pass
    if not settings["output_folder"]:
        settings["output_folder"] = str(documents_dir())
    return settings


def save_settings(settings: dict, data_dir: Path | None = None) -> Path:
    data_dir = ensure_user_files(data_dir)
    path = data_dir / "settings.json"
    clean = {k: settings.get(k, v) for k, v in DEFAULTS.items()}
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return path
