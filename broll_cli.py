#!/usr/bin/env python3
"""Command-line entry for testing and debugging (the desktop app uses the same engine).

Examples:
  python broll_cli.py script.txt
  python broll_cli.py script.txt --max-moments 3
  echo "In 2009..." | python broll_cli.py --text -
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.pipeline import Pipeline
from engine.settings import ensure_user_files, load_settings
from engine.transcribe import transcribe_file


def main():
    ap = argparse.ArgumentParser(description="B-Roll Finder (command line, for testing)")
    ap.add_argument("input", nargs="?", help="script file (.txt/.md/.docx) or audio/video file")
    ap.add_argument("--text", help="paste script text directly (use - to read stdin)")
    ap.add_argument("--max-moments", type=int, default=None)
    ap.add_argument("--out-name", default="Script")
    args = ap.parse_args()
    data_dir = ensure_user_files()
    settings = load_settings(data_dir)
    if args.max_moments:
        settings["max_moments"] = args.max_moments
    if args.text is not None:
        script = sys.stdin.read() if args.text == "-" else args.text
    elif args.input:
        script = transcribe_file(args.input, settings["whisper_model"], data_dir / "cache")
    else:
        ap.error("give a script file or --text")
    pipe = Pipeline(settings, data_dir)
    out = pipe.run(script, args.out_name)
    print(f"Results in: {out}")


if __name__ == "__main__":
    main()
