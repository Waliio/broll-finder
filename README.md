# B-Roll Finder — in simple words

**What it does:** You paste a video script (or give it an audio/video file).
It finds the moments in your script that need B-roll, searches YouTube for
each moment, reads what is said in those videos, and gives you the best
clips with the exact start and end time, a link that jumps to that second,
and an Excel file. It can also download the clips and find images.

**No API key needed.** The default brain is the **Offline Brain**: it works
by rules, on your own PC, for free. Gemini (free key) and Claude (paid key)
are optional upgrades in Settings — never required.

## How to get the Windows setup file (read this first)

**Honest answer: this project cannot make a Windows `.exe` on a Linux or
Mac computer.** PyInstaller only builds an app for the computer it runs on,
and Inno Setup (the installer maker) only runs on Windows. So the setup
file is built on a free Windows computer in the cloud, using GitHub
Actions. That is what `.github/workflows/build.yml` does. It is free for a
public repo.

### Click-by-click: get BRollFinder-Setup.exe from GitHub

1. Go to **github.com** and sign in (make a free account if you do not have one).
2. Click the **+** (top right) → **New repository**.
3. Name it `broll-finder`, choose **Public**, click **Create repository**.
4. On the new repo page, click **uploading an existing file**.
5. Drag the whole contents of the project zip into the page (not the zip
   itself — unzip it first on your PC), then click **Commit changes**.
   - Tip: if GitHub says a file is too big, upload in two batches.
6. Click the **Actions** tab at the top of the repo.
7. On the left, click **Build Windows installer**.
8. Click the **Run workflow** button (right side), then the green
   **Run workflow** button again.
9. Wait about 10–20 minutes. The run turns green with a tick when it is done.
   - If it turns red, click the failed run, click the red step, and read the
     error at the bottom. The most common cause is a network hiccup while
     downloading ffmpeg — just run it again.
10. On the finished run page, scroll to the bottom to **Artifacts** and
    click **BRollFinder-Setup**. It downloads a zip.
11. Unzip it. Inside is **BRollFinder-Setup-1.0.0.exe**.
12. Double-click it to install, just like CapCut. No Python, no command line.

### If you already have a Windows PC

On Windows 10/11 with Python 3.12 installed:

```
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The installer appears in `installer-output\BRollFinder-Setup-1.0.0.exe`.

## Important: the first .exe will be UNSIGNED

Until you buy a code-signing certificate, Windows will warn you:

- **SmartScreen:** it may say “Windows protected your PC”. Click
  **More info → Run anyway**. This is normal for a new, unsigned app.
- **Smart App Control** (on some Windows 11 PCs): it may block an unsigned
  app completely, with no “Run anyway”. Only a signed app runs there.

The build already has a signing step ready: add your certificate as the
GitHub Secrets `WINDOWS_CERT_PFX` and `WINDOWS_CERT_PASSWORD`, and the
workflow signs the app automatically. Do not buy a certificate until you
have tested the unsigned build and are sure you want to send it to students.

## How to test it (no key, 2 minutes)

1. Install the app and open it.
2. On the **Mission** screen, click **Try with a sample script**
   (the Taylor Swift / Kanye West story).
3. Leave the brain on **Offline (no key)** and click **LAUNCH SCAN**.
4. Watch the **Live** screen: moments turn from Searching → Scoring → Done,
   and clips slide into the live feed.
5. On **Results**, click **Watch clip** — YouTube opens at the exact second.
6. Click **Open Excel** — the file opens with Clips, Script Topics,
   Videos Checked and Images sheets.

If YouTube blocks transcripts on your internet, the status bar says
“Local transcription mode (YouTube is blocking transcripts). Slower but
working.” The app then listens to the video audio itself and still finds
clips. If *search itself* is blocked, you will see: “YouTube is limiting
requests from your internet. Wait 30–60 minutes or switch networks
(for example a mobile hotspot). Your results so far are saved; press
Resume later.” Nothing is lost: press **Resume** to continue the same run.

## What is inside

```
app/            Desktop window (pywebview) + the bridge to Python
engine/         The brain: planning, YouTube search, transcripts, scoring, export
  offline_brain.py      Offline Brain (no key) — tested code from your package
  transcript_fallback.py  Cache -> transcript API -> subtitles -> local Whisper
  pipeline.py           The full scan, safe mode, partial save + Resume
  youtube.py            Search, safe-mode budget, Download All Clips
  images.py             Wikimedia + Openverse images, no key
  export.py             Excel + JSON (rejected clips are hidden)
  ai.py                 Optional Gemini / Claude (same JSON interface)
  transcribe.py         Local Whisper transcription for your own files
  settings.py           Settings + user files (never inside the install folder)
frontend/       React + TypeScript + Vite + Tailwind command-center UI
installer/      Inno Setup script (per-user install, no admin needed)
.github/workflows/build.yml   Free Windows build on GitHub
build_windows.ps1       Same build, on your own Windows PC
tests/          Unit tests (run: python -m pytest tests -q)
resources/      brain.txt, brain_rules.yaml, icon
samples/        The Taylor Swift sample script
```

## For developers: run the tests

```
python -m pytest tests -q
cd frontend && npm ci && npm run build
```

## Help / support files

If a run fails, send the log from the **Live** screen (Copy log button).
Logs are also saved in the app's data folder (Settings shows the results
folder; the data folder is `%APPDATA%\BRollFinder` on Windows).
