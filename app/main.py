#!/usr/bin/env python3
"""B-Roll Finder desktop app: pywebview window + React frontend + Python engine.

The window uses Microsoft Edge WebView2 on Windows 10/11 (the installer
installs the WebView2 runtime if it is missing). No console window ever
appears in the packaged app. Long scans run in a background thread and
push events to the UI; the UI polls for them, so it never freezes.
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# In the installed (PyInstaller) app, bundled data lives in sys._MEIPASS
# (the _internal folder); in source mode, the project root is app/'s parent.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import __version__ as APP_VERSION  # noqa: E402
from engine.ai import AIProvider  # noqa: E402
from engine.brain_text import validate_brain_text  # noqa: E402
from engine.images import download_image, find_images_for_moment  # noqa: E402
from engine.offline_brain import load_brain, plan_moments, validate_brain  # noqa: E402
from engine.pipeline import Pipeline  # noqa: E402
from engine.settings import (ensure_user_files, is_public_build, load_settings,  # noqa: E402
                             resource_path, save_settings)
from engine.transcribe import transcribe_file  # noqa: E402


def _open_path(path: str):
    p = Path(path)
    try:
        if os.name == "nt":
            os.startfile(str(p))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception:
        return False


class Api:
    def __init__(self):
        self.data_dir = ensure_user_files()
        self.settings = load_settings(self.data_dir)
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.pipeline: Pipeline | None = None
        self.thread: threading.Thread | None = None
        self.current_run: dict | None = None
        self.status = "Idle"

    # -- helpers ------------------------------------------------------------
    def choose_file(self):
        """Native file picker (the browser file input cannot hand a real
        audio/video path to Python, so the app uses this instead)."""
        window = getattr(self, "window", None)
        if window is None:
            return {"ok": False, "error": "File picker is not available yet."}
        try:
            import webview
            picked = window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("Media and text files",
                            "*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg;*.opus;*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.txt;*.md;*.docx"))
            if picked:
                return {"ok": True, "path": picked[0]}
            return {"ok": False, "error": "No file chosen."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def _emit(self, event: dict):
        with self.lock:
            self.events.append(event)

    def _log(self, msg: str):
        self._emit({"type": "log", "text": msg})

    def poll_events(self):
        with self.lock:
            out, self.events = self.events, []
        return {"events": out, "status": self.status}

    def get_version(self):
        return {"version": APP_VERSION, "status": self.status}

    # -- settings / brain ---------------------------------------------------
    def get_settings(self):
        return dict(self.settings)

    def save_settings(self, new: dict):
        self.settings.update({k: v for k, v in new.items() if k in self.settings})
        save_settings(self.settings, self.data_dir)
        return {"ok": True}

    def get_build_mode(self):
        """Public builds hide the BRAIN tab; private builds show it."""
        return {"public": is_public_build()}

    def get_brain(self, mode: str = "offline"):
        if is_public_build():
            return {"text": "", "mode": mode, "ok": False,
                    "error": "Brain is locked in this version."}
        name = "brain_rules.yaml" if mode == "offline" else "brain.txt"
        path = self.data_dir / name
        try:
            ensure_user_files(self.data_dir)
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                # Empty user file survived ensure_user_files: rewrite it.
                from engine.settings import bundled_brain_text
                fallback = bundled_brain_text(name)
                if fallback:
                    path.write_text(fallback, encoding="utf-8")
                    text = fallback
            if not text.strip():
                return {"text": "", "mode": mode, "ok": False,
                        "error": "Brain file is empty and no default could be loaded."}
            return {"text": text, "mode": mode, "ok": True}
        except Exception as e:  # noqa: BLE001
            # Never raise: a raised call fails silently in the UI and the
            # BRAIN tab just stays empty with no explanation.
            return {"text": "", "mode": mode, "ok": False, "error": str(e)}

    def save_brain(self, text: str, mode: str = "offline"):
        if is_public_build():
            return {"ok": False, "error": "Brain is locked in this version."}
        name = "brain_rules.yaml" if mode == "offline" else "brain.txt"
        path = self.data_dir / name
        try:
            if mode == "offline":
                import yaml
                validate_brain(yaml.safe_load(text))
            else:
                tmp = self.data_dir / "_brain_check.txt"
                tmp.write_text(text, encoding="utf-8")
                validate_brain_text(tmp)
                tmp.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        path.write_text(text, encoding="utf-8")
        return {"ok": True}

    def restore_brain(self, mode: str = "offline"):
        if is_public_build():
            return {"text": "", "ok": False,
                    "error": "Brain is locked in this version."}
        name = "brain_rules.yaml" if mode == "offline" else "brain.txt"
        dest = self.data_dir / name
        try:
            from engine.settings import bundled_brain_text
            text = bundled_brain_text(name)
            if text:
                dest.write_text(text, encoding="utf-8")
                return {"text": text, "ok": True}
            return {"text": "", "ok": False,
                    "error": "Default brain file could not be found in the app."}
        except Exception as e:  # noqa: BLE001
            return {"text": "", "ok": False, "error": str(e)}

    def test_brain(self, text: str, sample_text: str = ""):
        if is_public_build():
            return {"ok": False, "error": "Brain is locked in this version."}
        """Show which moments the Offline Brain finds in a sample script.
        `text` is the brain YAML; the sample script is separate, so testing
        the brain never mistakes the brain file itself for a script."""
        if not sample_text:
            sample_text = (
                "In 2009, a 19-year-old Taylor Swift won her first MTV VMA, but Kanye West "
                "stormed the stage, grabbed the microphone and said Beyonce deserved the award. "
                "In 2019, Taylor lost the rights to her first six albums when Scooter Braun "
                "bought her old record label. Instead of giving up, she re-recorded all of them.")
        try:
            import yaml
            brain = yaml.safe_load(text)
            validate_brain(brain)
            plan = plan_moments(sample_text, brain, 15)
            return {"ok": True, "main_subject": plan["main_subject"],
                    "topics": [{"topic": t["topic"], "script_line": t["script_line"],
                                "search_queries": t["search_queries"]} for t in plan["topics"]]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # -- scans ---------------------------------------------------------------
    def start_scan(self, script_text: str, options: dict):
        if self.thread and self.thread.is_alive():
            return {"ok": False, "error": "A scan is already running."}
        for k in ("ai_provider", "max_moments", "videos_per_moment", "min_score",
                  "also_find_images", "auto_download_clips"):
            if k in options:
                self.settings[k] = options[k]
        save_settings(self.settings, self.data_dir)
        if self.settings["ai_provider"] != "offline" and not (
                self.settings.get("gemini_api_key") or self.settings.get("claude_api_key")):
            return {"ok": False,
                    "error": "You picked an AI mode but no key is saved. "
                             "Add a key in Settings, or switch back to Offline Brain (no key)."}
        self.status = "Scanning"
        self.current_run = {"script": script_text, "options": options}
        self.thread = threading.Thread(target=self._run_scan, args=(script_text,), daemon=True)
        self.thread.start()
        return {"ok": True}

    def _run_scan(self, script_text: str):
        try:
            pipe = Pipeline(self.settings, self.data_dir, log=self._log, emit=self._emit,
                            image_func=(lambda t: find_images_for_moment(
                                t, self.settings.get("commercial_images_only", True))
                                if self.settings.get("also_find_images") else []))
            self.pipeline = pipe
            out = pipe.run(script_text, "Scan")
            self.current_run = {**self.current_run, "out_dir": str(out)}
            if self.settings.get("auto_download_clips"):
                data = json.loads((out / "broll_clips.json").read_text())
                pipe.download_all(out, data["clips"])
            self.status = "Idle"
        except Exception as e:  # noqa: BLE001
            self._log(f"Scan failed: {e}")
            self._emit({"type": "error", "text": str(e)})
            self.status = "Idle"

    def start_scan_from_file(self, file_path: str, options: dict):
        try:
            script = transcribe_file(file_path, self.settings["whisper_model"], self.data_dir / "cache", log=self._log)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        return self.start_scan(script, options)

    def stop_scan(self):
        if self.pipeline:
            self.pipeline.stop()
        self.status = "Idle"
        return {"ok": True}

    def resume_scan(self, out_dir: str):
        resume_path = Path(out_dir) / "resume.json"
        if not resume_path.exists():
            return {"ok": False, "error": "No saved run found there to resume."}
        resume = json.loads(resume_path.read_text())
        self.status = "Scanning"
        # Pass the saved transcript back so run() does not overwrite it.
        orig = Path(out_dir) / "script_transcript.txt"
        script = orig.read_text(encoding="utf-8") if orig.exists() else ""
        def _run2():
            try:
                pipe = Pipeline(self.settings, self.data_dir, log=self._log, emit=self._emit)
                self.pipeline = pipe
                # Temporarily keep run() from clobbering the script file: it writes
                # the same text back, because we pass the saved transcript.
                pipe.run(script, "Scan", resume_from=resume)
            except Exception as e:  # noqa: BLE001
                self._log(f"Resume failed: {e}")
            self.status = "Idle"
        self.thread = threading.Thread(target=_run2, daemon=True)
        self.thread.start()
        return {"ok": True}

    # -- history / results ---------------------------------------------------
    def list_history(self):
        root = Path(self.settings.get("output_folder") or "")
        out = []
        if root.exists():
            for folder in sorted(root.iterdir(), reverse=True):
                jf = folder / "broll_clips.json"
                if folder.is_dir() and jf.exists():
                    try:
                        data = json.loads(jf.read_text())
                        out.append({"out_dir": str(folder), "name": folder.name,
                                    "clips": len(data.get("clips", [])),
                                    "main_subject": data.get("main_subject", "")})
                    except Exception:
                        continue
        return {"runs": out}

    def get_run(self, out_dir: str):
        jf = Path(out_dir) / "broll_clips.json"
        if not jf.exists():
            return {"ok": False, "error": "Run not found."}
        return {"ok": True, "data": json.loads(jf.read_text())}

    def set_clip_rejected(self, out_dir: str, clip_index: int, rejected: bool):
        jf = Path(out_dir) / "broll_clips.json"
        data = json.loads(jf.read_text())
        if 0 <= int(clip_index) < len(data["clips"]):
            data["clips"][int(clip_index)]["rejected"] = bool(rejected)
            jf.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return {"ok": True}
        return {"ok": False, "error": "Clip not found."}

    def download_all_clips(self, out_dir: str):
        data = self.get_run(out_dir)
        if not data.get("ok"):
            return data
        pipe = Pipeline(self.settings, self.data_dir, log=self._log, emit=self._emit)
        summary = pipe.download_all(Path(out_dir), data["data"]["clips"])
        self._emit({"type": "download_done", "summary": summary})
        return {"ok": True, "summary": summary}

    def download_all_images(self, out_dir: str):
        data = self.get_run(out_dir)
        if not data.get("ok"):
            return data
        img_dir = Path(out_dir) / "images"
        img_dir.mkdir(exist_ok=True)
        done, failed = 0, 0
        for i, im in enumerate(data["data"].get("images", []), 1):
            dest = img_dir / f"{i:02d}_Moment{im.get('topic_id', '')}_{im.get('source', 'img')}.jpg"
            if dest.exists():
                done += 1
                continue
            if download_image(im, dest):
                im["file"] = dest.name
                done += 1
            else:
                failed += 1
        jf = Path(out_dir) / "broll_clips.json"
        jf.write_text(json.dumps(data["data"], indent=2), encoding="utf-8")
        return {"ok": True, "summary": {"downloaded": done, "failed": failed}}

    def open_folder(self, path: str):
        return {"ok": _open_path(path)}

    def open_excel(self, out_dir: str):
        return {"ok": _open_path(str(Path(out_dir) / "broll_clips.xlsx"))}

    def test_key(self):
        return {"ok": AIProvider(self.settings).test_key()}

    def update_ytdlp(self):
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                           check=False, capture_output=True, timeout=300)
            return {"ok": True, "message": "YouTube engine update attempted. Restart the app if it changed."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


def main():
    import webview
    api = Api()
    frontend = ROOT / "frontend" / "dist" / "index.html"
    if not frontend.exists():
        # Dev fallback: serve the source folder if the built frontend is missing.
        frontend = ROOT / "frontend" / "index.html"
    window = webview.create_window(
        f"B-Roll Finder {APP_VERSION}", url=str(frontend), js_api=api,
        width=1280, height=800, min_size=(1024, 640))
    api.window = window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
