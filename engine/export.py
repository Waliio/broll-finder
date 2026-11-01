"""Save results: Excel (Clips, Script Topics, Videos Checked, Images)
plus JSON. Rejected clips are hidden from exports. Clip links jump to
the exact second on YouTube.
"""
from __future__ import annotations

import json
from pathlib import Path

from .utils import fmt_time

CAT_COLORS = {"Scandal": "FDE2E2", "Controversy": "FDEBD3", "Key Statement": "E0EDFF",
              "Interview": "E3F4E8", "News Report": "EEE5FB", "Emotional Moment": "FFF6CC"}


def save_results(out_dir: Path, plan: dict, clips: list[dict],
                 videos_seen: list[dict], images: list[dict] | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kept = [c for c in clips if not c.get("rejected")]
    xlsx = out_dir / "broll_clips.xlsx"
    save_excel(xlsx, plan, kept, videos_seen, images or [])
    (out_dir / "broll_clips.json").write_text(json.dumps(
        {"main_subject": plan.get("main_subject", ""), "topics": plan.get("topics", []),
         "clips": kept, "videos_checked": videos_seen, "images": images or []},
        indent=2, ensure_ascii=False), encoding="utf-8")
    return {"excel": str(xlsx), "json": str(out_dir / "broll_clips.json"), "clips": len(kept)}


def save_excel(path: Path, plan, clips, videos_seen, images):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(name="Arial", bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", start_color="1F2937")
    body_font = Font(name="Arial", size=10)
    link_font = Font(name="Arial", size=10, color="0563C1", underline="single")
    wrap = Alignment(wrap_text=True, vertical="top")

    def write_sheet(ws, headers, rows, widths, link_cols=()):
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill, c.alignment = head_font, head_fill, Alignment(vertical="center", wrap_text=True)
        for row in rows:
            ws.append(row)
        for r in ws.iter_rows(min_row=2):
            for c in r:
                c.font, c.alignment = body_font, wrap
                if c.column in link_cols and isinstance(c.value, str) and c.value.startswith("http"):
                    c.hyperlink, c.font = c.value, link_font
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        if ws.max_row > 1 and ws.max_column > 0:
            ws.auto_filter.ref = ws.dimensions

    ws = wb.active
    ws.title = "Clips"
    rows = [[i, c["topic_id"], c["script_line"], c["category"], c["score"],
             c["start_str"], c["end_str"], round(c["end_s"] - c["start_s"]),
             c["clip_url"], c["video_title"], c["channel"], c["what_happens"],
             c["key_quote"], c["why_it_fits"], c.get("file", "")]
            for i, c in enumerate(clips, 1)]
    write_sheet(ws, ["#", "Topic #", "Script Line", "Category", "Score", "Start", "End",
                     "Length (s)", "Clip Link (jumps to time)", "Video Title", "Channel",
                     "What Happens", "Key Quote", "Why It Fits", "Downloaded File"],
                rows, [5, 8, 40, 15, 7, 8, 8, 9, 42, 40, 20, 45, 35, 40, 25], link_cols=(9,))
    for r in range(2, ws.max_row + 1):
        color = CAT_COLORS.get(ws.cell(r, 4).value)
        if color:
            ws.cell(r, 4).fill = PatternFill("solid", start_color=color)

    ws2 = wb.create_sheet("Script Topics")
    counts = {}
    for c in clips:
        counts[c["topic_id"]] = counts.get(c["topic_id"], 0) + 1
    rows2 = [[t["id"], t["script_line"], t["topic"], t["what_to_show"],
              " | ".join(t.get("search_queries", [])), counts.get(t["id"], 0)]
             for t in plan.get("topics", [])]
    write_sheet(ws2, ["Topic #", "Script Line", "Topic", "Ideal Footage", "Searches Used", "Clips Found"],
                rows2, [8, 50, 25, 40, 50, 10])

    ws3 = wb.create_sheet("Videos Checked")
    rows3 = [[v.get("topic_id"), v.get("title"), v.get("channel"),
              fmt_time(v.get("duration", 0)), v.get("views", 0), v.get("url"), v.get("status", "")]
             for v in videos_seen]
    write_sheet(ws3, ["Topic #", "Title", "Channel", "Length", "Views", "Link", "Status"],
                rows3, [8, 50, 22, 9, 12, 45, 30], link_cols=(6,))

    ws4 = wb.create_sheet("Images")
    rows4 = [[im.get("topic_id"), im.get("file", ""), im.get("url", ""), im.get("author", ""),
              im.get("license", ""), im.get("attribution", "")]
             for im in images]
    write_sheet(ws4, ["Topic #", "File", "Source URL", "Author", "License", "Attribution"],
                rows4, [8, 40, 45, 25, 15, 60], link_cols=(3,))
    wb.save(path)
