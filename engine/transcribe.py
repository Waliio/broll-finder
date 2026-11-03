"""Read a script file, or transcribe audio/video with faster-whisper."""

from __future__ import annotations

import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET


def read_text_file(path: str | Path) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(p) as zf:
            xml = zf.read("word/document.xml")
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        root = ET.fromstring(xml)
        paras = []
        for para in root.findall(".//w:p", ns):
            texts = [t.text or "" for t in para.findall(".//w:t", ns)]
            paras.append("".join(texts))
        return "\n".join(paras)
    return p.read_text(encoding="utf-8", errors="ignore")


def transcribe_file(path: str | Path, model: str, cache_dir: Path, log=print) -> str:
    p = Path(path)
    if p.suffix.lower() in (".txt", ".md", ".docx"):
        return read_text_file(p)
    from faster_whisper import WhisperModel

    log(f"Transcribing {p.name} with Whisper ({model})...")
    m = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _ = m.transcribe(str(p))
    return " ".join(seg.text.strip() for seg in segments if seg.text.strip())
