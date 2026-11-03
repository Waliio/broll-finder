# B-Roll Finder v2

Paste a script (or an audio/video/text file) → the app finds the exact
YouTube moments (B-roll clips) that match it, with timestamps and
scores → export Excel + JSON, optionally download the clips and find
images. No API key needed for the default Offline Brain mode.

Dark blue + orange techy interface. Version 2.0.0, clean rebuild.

## Get the Windows installer from GitHub (simple steps)

This app cannot be built on a Linux/Mac computer — the Windows
installer is built free on GitHub's Windows computer.

1. Open your repo on GitHub (for example `Waliio/broll-finder`).
2. Upload all files from this project to the repo, at the top level
   (not inside one extra folder). Make sure the hidden `.github`
   folder is included.
3. Click the **Actions** tab at the top of the repo.
4. On the left, click **Build Windows installer**.
5. Click **Run workflow**. Choose the type:
   - **private** = your own version. The BRAIN tab is visible.
     Artifact name: `BRollFinder-Setup`. **Do not give this to others.**
   - **public** = the version for other people. The BRAIN tab is
     hidden and the brain is locked. Artifact name:
     `BRollFinder-Setup-Public`. This is the file to give to others.
6. Wait about 10–20 minutes until the run shows a green tick.
7. Scroll to **Artifacts** at the bottom of that run page and click
   the artifact name. A zip downloads.
8. Unzip it. Inside is `BRollFinder-Setup-2.0.0.exe`.
9. Double-click it to install. No admin rights needed.
10. If Windows says "Windows protected your PC", click **More info**,
    then **Run anyway**. This first build is unsigned — that warning
    is expected. PCs with Smart App Control may block unsigned apps.

## Test it (one step at a time)

1. Uninstall any old B-Roll Finder first (Settings → Apps).
2. Install the **private** version.
3. Open the app. Click the **BRAIN** tab — the rules must already be
   filled in, not empty. If the box is empty, press **Restore default**.
4. Click **Mission** → **Try with a sample script** → leave the brain
   on **Offline (no key)** → **LAUNCH SCAN**.
5. Watch **Live**: moments should appear, then clips.
6. Open **Results**: a clip should open YouTube at the exact second.
   **Open Excel** should open the Excel file.

If a step fails, send a screenshot of that screen — do not just wait.

## What is inside

- `engine/` — the scan engine (Offline Brain, transcripts, YouTube,
  images, Excel/JSON export). The brain rules are embedded in
  `engine/default_brain.py` so the BRAIN tab can never start empty.
- `app/main.py` — the desktop app (pywebview + the engine).
- `frontend/` — React + TypeScript + Vite + Tailwind UI
  (Mission, Live, Results, Images, BRAIN, Settings, History).
- `installer/broll_finder.iss` — Inno Setup installer script.
- `.github/workflows/build.yml` — the GitHub Actions build.
- `tests/` — engine tests. Run them with: `python -m pytest tests -q`

## Private vs public — please read

The **public** build hides the BRAIN tab and locks the brain APIs,
and it writes no readable brain file to the user's PC. But the
GitHub repo itself is public, so the brain text in the repo is still
readable there. True secrecy needs the repo private or the brain
removed from it. The public build protects app users, not repo readers.

## Project map

```
engine/            scan engine + embedded brain
app/main.py        desktop app window + API
frontend/src/      React UI (dark blue #071426 + orange #FF6A00)
installer/         Inno Setup script
.github/workflows/ GitHub Actions build (private/public choice)
tests/             engine tests
resources/         icon + brain data files (private builds only)
samples/           Taylor Swift sample script
```
