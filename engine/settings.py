"""Where the app stores its own files, and user settings.

Never writes inside the install folder. On Windows this is
%APPDATA%\\BRollFinder, on macOS ~/Library/Application Support/BRollFinder,
on Linux ~/.local/share/BRollFinder. Results go to Documents/B-Roll Finder
by default and can be changed in Settings.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "BRollFinder"
VERSION = "2.0.0"

DEFAULTS = {
    "ai_provider": "offline",
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


def is_public_build() -> bool:
    try:
        from engine.build_mode import PUBLIC_BUILD

        return bool(PUBLIC_BUILD)
    except Exception:
        return False


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    try:
        from platformdirs import user_data_dir as _pdd

        return Path(_pdd(APP_NAME))
    except Exception:
        return Path.home() / ".local" / "share" / APP_NAME


def documents_dir() -> Path:
    return Path.home() / "Documents" / "B-Roll Finder"


def resource_path(name: str) -> Path:
    """Bundled file. In the frozen app, sys._MEIPASS comes first."""
    here = Path(__file__).resolve()
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "resources" / name)
    candidates += [here.parent.parent / "resources" / name, Path.cwd() / "resources" / name]
    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]


def bundled_brain_text(name: str) -> str | None:
    """Brain text from the bundled file if present and non-empty, else
    from the embedded copy. Returns None only if both are unavailable."""
    src = resource_path(name)
    if src.exists():
        try:
            text = src.read_text(encoding="utf-8")
            if text.strip():
                return text
        except Exception:
            pass
    try:
        from engine.default_brain import DEFAULT_BRAIN_TXT, DEFAULT_BRAIN_YAML

        if name == "brain_rules.yaml":
            return DEFAULT_BRAIN_YAML
        if name == "brain.txt":
            return DEFAULT_BRAIN_TXT
    except Exception:
        pass
    return None


def ensure_user_files(data_dir: Path | None = None) -> Path:
    """Create the user folder and brain files on first run.

    Public builds: never write a readable brain file to the PC.
    Private builds: a missing OR empty brain file is rewritten from
    the bundled/embedded default; a non-empty user file is never touched.
    """
    data_dir = Path(data_dir) if data_dir else user_data_dir()
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    if is_public_build():
        return data_dir
    for name in ("brain_rules.yaml", "brain.txt"):
        dest = data_dir / name
        needs = True
        if dest.exists():
            try:
                needs = not dest.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                needs = True
        if needs:
            text = bundled_brain_text(name)
            if text is not None:
                dest.write_text(text, encoding="utf-8")
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
