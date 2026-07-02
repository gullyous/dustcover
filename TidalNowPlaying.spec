# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('CHANGELOG.md', '.')]   # in-app release notes (Settings > Updates)
binaries = []
hiddenimports = []
for _pkg in ('winsdk', 'tidalapi', 'pynput', 'pycaw', 'comtypes', 'psutil'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass  # optional dependency not installed; skip

# The app only uses QtCore / QtGui / QtWidgets. Exclude the heavy Qt modules
# PyInstaller would otherwise bundle (QtWebEngineCore alone is ~195 MB), plus
# common libraries we never import. This is the main exe-size win.
excludes = [
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick', 'PySide6.QtWebEngine',
    'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtWebView',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
    'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtSpatialAudio',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras', 'PySide6.Qt3DLogic',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtSql', 'PySide6.QtDesigner', 'PySide6.QtHelp',
    'PySide6.QtTest', 'PySide6.QtUiTools',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning',
    'PySide6.QtSerialPort', 'PySide6.QtSensors',
    'PySide6.QtTextToSpeech', 'PySide6.QtRemoteObjects',
    'PySide6.QtScxml', 'PySide6.QtStateMachine',
    'PySide6.QtNetworkAuth', 'PySide6.QtHttpServer',
    'tkinter',
    'numpy', 'PIL', 'pandas', 'matplotlib', 'scipy', 'pytest', 'IPython',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TidalNowPlaying',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
