"""The editable brain.txt used by Gemini / Claude modes.

Lines starting with '#' are notes for the user and are stripped.
Sections are marked '=== NAME ==='. Saving requires PART A and PART B.
"""
from __future__ import annotations

import re
from pathlib import Path

SECTION_RE = re.compile(r"^===\s*(.+?)\s*===\s*$")


def load_brain_text(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
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
