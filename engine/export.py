"""Excel + JSON export. Rejected clips are kept but hidden in Excel."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook


def save_results(out_dir: Path, run_name: str, clips: list[dict], topics: list[dict],
                 videos_checked: list[dict], images: list[dict]) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Clips"
    ws.append(["Topic", "Video", "Channel", "Start", "End", "Category", "Score",
               "What happens", "Key quote", "Why it fits", "Clip URL", "Video URL", "Rejected"])
    for c in clips:
        row = ws.max_row + 1
        ws.append([c.get("topic", ""), c.get("video_title", ""), c.get("channel", ""),
                   c.get("start_str", ""), c.get("end_str", ""), c.get("category", ""),
                   c.get("score", ""), c.get("what_happens", ""), c.get("key_quote", ""),
                   c.get("why_it_fits", ""), c.get("clip_url", ""), c.get("video_url", ""),
                   "Yes" if c.get("rejected") else ""])
        if c.get("rejected"):
            ws.row_dimensions[row].hidden = True
    ws2 = wb.create_sheet("Script Topics")
    ws2.append(["ID", "Topic", "Script line", "What to show", "Search queries"])
    for t in topics:
        ws2.append([t.get("id", ""), t.get("topic", ""), t.get("script_line", ""),
                    t.get("what_to_show", ""), " | ".join(t.get("search_queries", []))])
    ws3 = wb.create_sheet("Videos Checked")
    ws3.append(["Topic", "Video ID", "Title", "Channel", "Duration (s)"])
    for v in videos_checked:
        ws3.append([v.get("topic", ""), v.get("video_id", ""), v.get("title", ""),
                    v.get("channel", ""), v.get("duration", "")])
    ws4 = wb.create_sheet("Images")
    ws4.append(["Topic", "Title", "Source", "Author", "License", "URL", "Attribution"])
    for im in images:
        ws4.append([im.get("topic", ""), im.get("title", ""), im.get("source", ""),
                    im.get("author", ""), im.get("license", ""), im.get("url", ""),
                    im.get("attribution", "")])
    for sheet in wb.worksheets:
        for col in sheet.columns:
            width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
            sheet.column_dimensions[col[0].column_letter].width = min(60, max(12, width + 2))
    excel_path = out_dir / "broll_clips.xlsx"
    wb.save(excel_path)
    json_path = out_dir / "broll_clips.json"
    json_path.write_text(json.dumps({
        "run_name": run_name, "clips": clips, "topics": topics,
        "videos_checked": videos_checked, "images": images,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return excel_path
