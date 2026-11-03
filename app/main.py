#!/usr/bin/env python3
"""B-Roll Finder v2 desktop app: pywebview window + React frontend + engine.

Edge WebView2 on Windows 10/11. No console window in the packaged app.
Long scans run in a background thread and push events; the UI polls.
Every API method returns a visible ok/error result — never a silent fail.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# Frozen app: bundled files live under sys._MEIPASS. Source mode: project root.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import __version__ as APP_VERSION  # noqa: E402
from engine.ai import AIProvider  # noqa: E402
from engine.brain_text import validate_brain_text  # noqa: E402
from engine.images import find_images_for_moment  # noqa: E402
from engine.offline_brain import load_brain, plan_moments, validate_brain  # noqa: E402
from engine.pipeline import Pipeline  # noqa: E402
from engine.settings import (  # noqa: E402
    bundled_brain_text, ensure_user_files, is_public_build, load_settings, save_settings,
)
from engine.transcribe import transcribe_file  # noqa: E402
from engine.youtube import download_all_clips  # noqa: E402

SAMPLE_SCRIPT = (
    "In 2009, a 19-year-old Taylor Swift won her first MTV VMA, but Kanye West "
    "stormed the stage, grabbed the microphone and said Beyonce deserved the award. "
    "In 2019, Taylor lost the rights to her first six albums when Scooter Braun "
    "bought her old record label. Instead of giving up, she re-recorded all of them."
)


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
        return {"public": is_public_build()}

    def get_brain(self, mode: str = "offline"):
        if is_public_build():
            return {"text": "", "mode": mode, "ok": False, "error": "Brain is locked in this version."}
        name = "brain_rules.yaml" if mode == "offline" else "brain.txt"
        path = self.data_dir / name
        try:
            ensure_user_files(self.data_dir)
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                fallback = bundled_brain_text(name)
                if fallback:
                    path.write_text(fallback, encoding="utf-8")
                    text = fallback
            if not text.strip():
                return {"text": "", "mode": mode, "ok": False,
                        "error": "Brain file is empty and no default could be loaded."}
            return {"text": text, "mode": mode, "ok": True}
        except Exception as e:  # noqa: BLE001
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
            return {"text": "", "ok": False, "error": "Brain is locked in this version."}
        name = "brain_rules.yaml" if mode == "offline" else "brain.txt"
        dest = self.data_dir / name
        try:
            text = bundled_brain_text(name)
            if text:
                dest.write_text(text, encoding="utf-8")
                return {"text": text, "ok": True}
            return {"text": "", "ok": False, "error": "Default brain file could not be found in the app."}
        except Exception as e:  # noqa: BLE001
            return {"text": "", "ok": False, "error": str(e)}

    def test_brain(self, text: str, sample_text: str = ""):
        if is_public_build():
            return {"ok": False, "error": "Brain is locked in this version."}
        if not sample_text:
            sample_text = SAMPLE_SCRIPT
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
    def choose_file(self):
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

    def start_scan(self, script_text: str, options: dict):
        if self.thread and self.thread.is_alive():
            return {"ok": False, "error": "A scan is already running."}
        self.status = "Scanning"
        self.current_run = {"script": script_text, "options": options}
        self.thread = threading.Thread(target=self._run_scan, args=(script_text, options), daemon=True)
        self.thread.start()
        return {"ok": True}

    def _run_scan(self, script_text: str, options: dict):
        try:
            settings = dict(self.settings)
            settings.update({k: v for k, v in options.items() if k in settings})
            file_path = options.get("file_path", "")
            if file_path:
                script_text = transcribe_file(file_path, settings["whisper_model"],
                                              self.data_dir / "cache", log=self._log)
            import re
            from datetime import datetime

            run_name = re.sub(r"[^A-Za-z0-9_-]+", "_", (script_text[:40] or "run")).strip("_") or "run"
            run_name = f"{datetime.now().strftime('%Y%m%d_%H%M')}_{run_name[:30]}"
            pipe = Pipeline(settings, self.data_dir, log=self._log, emit=self._emit)
            self.pipeline = pipe
            out_dir = pipe.run(script_text, run_name)
            self.current_run = {"script": script_text, "options": options, "out_dir": str(out_dir), "run_name": run_name}
            self.status = "Done"
        except Exception as e:  # noqa: BLE001
            self._log(f"Scan failed: {e}")
            self._emit({"type": "error", "text": str(e)})
            self.status = "Error"

    def stop_scan(self):
        if self.pipeline:
            self.pipeline.stop()
        self.status = "Idle"
        return {"ok": True}

    def resume_scan(self):
        if not self.current_run:
            return {"ok": False, "error": "No run to resume."}
        out_dir = Path(self.current_run.get("out_dir", ""))
        resume_file = out_dir / "resume.json"
        if not resume_file.exists():
            return {"ok": False, "error": "No resume file found for the last run."}
        self.status = "Scanning"
        self.thread = threading.Thread(target=self._run_resume, args=(resume_file,), daemon=True)
        self.thread.start()
        return {"ok": True}

    def _run_resume(self, resume_file: Path):
        try:
            settings = dict(self.settings)
            script_text = self.current_run.get("script", "") if self.current_run else ""
            run_name = self.current_run.get("run_name", "run") if self.current_run else "run"
            pipe = Pipeline(settings, self.data_dir, log=self._log, emit=self._emit)
            self.pipeline = pipe
            pipe.run(script_text, run_name, resume_from=resume_file)
            self.status = "Done"
        except Exception as e:  # noqa: BLE001
            self._log(f"Resume failed: {e}")
            self.status = "Error"

    # -- results / history ---------------------------------------------------
    def history(self):
        out_root = Path(self.settings.get("output_folder") or (Path.home() / "Documents" / "B-Roll Finder"))
        runs = []
        if out_root.exists():
            for folder in sorted(out_root.iterdir(), reverse=True):
                jf = folder / "broll_clips.json"
                if folder.is_dir() and jf.exists():
                    try:
                        data = json.loads(jf.read_text(encoding="utf-8"))
                        runs.append({"run_name": folder.name, "out_dir": str(folder),
                                     "clips": len(data.get("clips", [])), "topics": len(data.get("topics", []))})
                    except Exception:
                        continue
        return {"runs": runs}

    def get_run(self, out_dir: str):
        try:
            data = json.loads((Path(out_dir) / "broll_clips.json").read_text(encoding="utf-8"))
            return {"ok": True, **data}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def set_clip_rejected(self, out_dir: str, clip_url: str, rejected: bool):
        try:
            jf = Path(out_dir) / "broll_clips.json"
            data = json.loads(jf.read_text(encoding="utf-8"))
            for c in data.get("clips", []):
                if c.get("clip_url") == clip_url:
                    c["rejected"] = bool(rejected)
            jf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def download_all_clips(self, out_dir: str):
        try:
            data = json.loads((Path(out_dir) / "broll_clips.json").read_text(encoding="utf-8"))
            kept = [c for c in data.get("clips", []) if not c.get("rejected")]
            done = download_all_clips(kept, Path(out_dir) / "downloads", log=self._log)
            return {"ok": True, "downloaded": len(done)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def download_images(self, topic: str):
        try:
            imgs = find_images_for_moment(topic, commercial_only=bool(self.settings.get("commercial_images_only", True)))
            return {"ok": True, "images": imgs}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def open_folder(self, out_dir: str):
        return {"ok": _open_path(out_dir)}

    def open_excel(self, out_dir: str):
        return {"ok": _open_path(str(Path(out_dir) / "broll_clips.xlsx"))}

    def test_key(self):
        provider = self.settings.get("ai_provider", "offline")
        if provider == "offline":
            return {"ok": True, "message": "Offline Brain needs no key."}
        try:
            ai = AIProvider(self.settings)
            res = ai.ask_json("You are a test.", 'Return {"ok": true}.', max_tokens=100)
            return {"ok": bool(res), "message": "Key works." if res else "Key test returned nothing."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def update_ytdlp(self):
        try:
            res = subprocess.run(["yt-dlp", "-U"], capture_output=True, text=True, timeout=120)
            return {"ok": res.returncode == 0, "output": (res.stdout or res.stderr or "")[-500:]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


def main():
    api = Api()
    index = ROOT / "frontend" / "dist" / "index.html"
    if not index.exists():
        print(f"Frontend not built: {index} — run: cd frontend && npm run build")
        return 1
    import webview

    window = webview.create_window("B-Roll Finder 2.0", url=str(index), js_api=api,
                                   width=1280, height=820, text_select=True)
    api.window = window
    webview.start(gui="edgechromium", debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
