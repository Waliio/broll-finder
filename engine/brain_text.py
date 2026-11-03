"""The editable brain.txt used by Gemini / Claude modes.

Lines starting with '#' are notes for the user and are stripped.
Sections are marked '=== NAME ==='. Saving requires PART A and PART B.
"""
from __future__ import annotations

import re
from pathlib import Path

SECTION_RE = re.compile(r"^===\s*(.+?)\s*===\s*$")


def parse_brain_text(text: str) -> dict:
    sections, current = {}, None
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        m = SECTION_RE.match(line.strip())
        if m:
            current = m.group(1).upper()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def load_brain_text_for_run(data_dir: str | Path) -> dict:
    """AI-brain sections for a scan. Public builds use the embedded
    brain.txt only; private builds use the user's editable file."""
    try:
        from engine.settings import is_public_build
        public = is_public_build()
    except Exception:
        public = False
    if public:
        from engine.default_brain import DEFAULT_BRAIN_TXT
        return parse_brain_text(DEFAULT_BRAIN_TXT)
    return load_brain_text(Path(data_dir) / "brain.txt")


def load_brain_text(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    return parse_brain_text(text)


def validate_brain_text(path: str | Path) -> None:
    sections = load_brain_text(path)
    missing = [n for n in ("PART A", "PART B") if not any(k.startswith(n) for k in sections)]
    if missing:
        raise ValueError(
            "The brain file is missing: " + ", ".join(missing) +
            ". Restore the default brain, then edit it again.")


def brain_part(sections: dict, *names: str) -> str:
    parts = []
    for name in names:
        for key, text in sections.items():
            if key.startswith(name) and text:
                parts.append(f"## {key}\n{text}")
    return "\n\n".join(parts)
