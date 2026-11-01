# PyInstaller spec: onedir mode (faster startup, fewer antivirus false
# positives than onefile), no UPX, console hidden. Run on Windows only:
#   pyinstaller broll_finder.spec
# The GitHub Actions workflow runs this on windows-latest.
# NOTE: This file cannot produce a Windows .exe when run on Linux/macOS.
# PyInstaller builds for the machine it runs on.
# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None
datas = [
    ('resources/brain.txt', 'resources'),
    ('resources/brain_rules.yaml', 'resources'),
    ('resources/icon.png', 'resources'),
    ('frontend/dist', 'frontend/dist'),
]
binaries = []
hiddenimports = ['engine', 'engine.pipeline', 'engine.offline_brain',
                 'engine.transcript_fallback', 'engine.youtube', 'engine.images',
                 'engine.export', 'engine.ai', 'engine.transcribe',
                 'engine.settings', 'engine.brain_text', 'engine.utils']
# faster-whisper / CTranslate2 / PyAV need their data files collected.
for pkg in ('ctranslate2', 'av', 'tokenizers', 'onnxruntime'):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

# CRITICAL: the entry script is app/main.py, but the engine package lives
# at the project root. With pathex=[] PyInstaller only searches app/ and
# silently leaves engine out of the bundle, so the installed app crashes
# with "No module named 'engine'". The workflow runs this from the repo
# root, so '.' is the project root here.
a = Analysis(
    ['app/main.py'],
    pathex=[os.path.abspath('.')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='BRollFinder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no console window, ever
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icon.ico',
    version='version_info.txt',
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[], name='BRollFinder',
)
