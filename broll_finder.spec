# PyInstaller spec: onedir, no console, no UPX. Windows only:
#   pyinstaller broll_finder.spec
# The GitHub Actions workflow runs this on windows-latest.
# NOTE: This cannot produce a Windows .exe on Linux/macOS.
# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None
datas = [
    ('resources/icon.png', 'resources'),
    ('frontend/dist', 'frontend/dist'),
]
if os.environ.get('BROLL_PUBLIC_BUILD') != '1':
    # Private build only: plain brain files ship normally.
    # Public builds must NOT contain a readable brain file in the
    # install folder; scans use the embedded brain in default_brain.py.
    datas += [
        ('resources/brain.txt', 'resources'),
        ('resources/brain_rules.yaml', 'resources'),
    ]
binaries = []
hiddenimports = ['engine', 'engine.pipeline', 'engine.offline_brain',
                 'engine.transcript_fallback', 'engine.youtube', 'engine.images',
                 'engine.export', 'engine.ai', 'engine.transcribe',
                 'engine.settings', 'engine.brain_text', 'engine.utils',
                 'engine.default_brain', 'engine.build_mode']
for pkg in ('ctranslate2', 'av', 'tokenizers', 'onnxruntime'):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

# CRITICAL (v1 lesson): the entry script is app/main.py, but the engine
# package lives at the project root. pathex MUST point at the project
# root, or PyInstaller silently leaves engine out and the installed app
# crashes with "No module named 'engine'".
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
    console=False,
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
