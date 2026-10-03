# -*- mode: python ; coding: utf-8 -*-
# Build:  uv run --group build pyinstaller replay_helper.spec   ->  dist/DCSReplayHelper.exe
# One file, no console. The DCS hook is bundled so Tools > Install / update DCS hook works.

a = Analysis(
    ['packaging/run_replay_helper.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/replay_helper/hook/ReplayHelper.lua', 'replay_helper/hook')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules the app does not use; keeps the exe smaller.
    excludes=['PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtXml',
              'PySide6.QtConcurrent', 'PySide6.QtDBus', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
              'PySide6.QtPrintSupport', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'tkinter', 'lupa'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DCSReplayHelper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
