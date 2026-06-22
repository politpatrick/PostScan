# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'icon.png'), '.'),
    ],
    hiddenimports=[
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'sklearn.feature_extraction.text',
        'sklearn.metrics.pairwise',
        'rapidfuzz',
        'pikepdf',
        'requests',
        'google.genai',
        'xattr',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['win32com', 'pythoncom', 'pywintypes'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PostScan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='PostScan',
)

app = BUNDLE(
    coll,
    name='PostScan.app',
    icon=None,
    bundle_identifier='de.pkunze.postscan',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0',
    },
)
