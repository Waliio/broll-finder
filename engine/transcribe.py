"""Read a script file, or transcribe audio/video locally with faster-whisper.

Text files (.txt/.md/.docx) are read directly. Audio/video is transcribed
on the user's own PC -- no key, no upload. Transcriptions are cached so a
second run on the same file is instant.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

AUDIO_VIDEO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
                   ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
TEXT_EXT = {".txt", ".md"}


def read_script_text(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() in TEXT_EXT:
        return p.read_text(encoding="utf-8", errors="ignore")
    if p.suffix.lower() == ".docx":
        from docx import Document
        doc = Document(str(p))
        return "\n".join(par.text for par in doc.paragraphs)
    raise ValueError(f"Unsupported script file type: {p.suffix}")


def transcribe_file(path: str | Path, model_name: str = "small",
                    cache_dir: str | Path | None = None,
                    log=print) -> str:
    p = Path(path)
    if p.suffix.lower() in TEXT_EXT or p.suffix.lower() == ".docx":
        return read_script_text(p)
    if p.suffix.lower() not in AUDIO_VIDEO_EXT:
        raise ValueError(f"Unsupported file type: {p.suffix}")
    cache_dir = Path(cache_dir) if cache_dir else Path(".broll_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(p.read_bytes()[:1_000_000]).hexdigest()[:12]
    cache = cache_dir / f"script_{p.stem}_{digest}.txt"
    if cache.exists():
        log("Using saved transcription from earlier run.")
        return cache.read_text(encoding="utf-8")
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "Speech transcription is not installed in this build. "
            "Paste the script text instead, or use a .txt script.") from e
    log(f"Transcribing {p.name} with Whisper '{model_name}' "
        "(first run downloads the model, one time only)...")
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segments, info = model.transcribe(str(p), vad_filter=True, beam_size=1)
    log(f"Detected language: {getattr(info, 'language', '?')}")
    text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
    cache.write_text(text, encoding="utf-8")
    return text
