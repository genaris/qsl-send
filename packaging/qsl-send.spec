# PyInstaller spec for the Windows build (one-folder).
#
# One-folder rather than one-file on purpose: it starts faster (one-file
# unpacks to a temp directory on every launch) and is flagged far less often
# by SmartScreen and antivirus.
#
# Build:  pyinstaller packaging/qsl-send.spec --noconfirm
import os

block_cipher = None

datas = [
    ("../qsl-send.example.yaml", "."),
    ("../template.jpg", "."),
    ("../README.md", "."),
]
datas = [(os.path.abspath(s), d) for s, d in datas if os.path.exists(s)]

a = Analysis(
    ["launcher.py"],
    pathex=[os.path.abspath("..")],
    binaries=[],
    datas=datas,
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    runtime_hooks=[],
    # requests is only needed for QRZ lookups; it stays in because the config
    # can enable them. Trim here if you want a smaller download.
    excludes=["pytest", "matplotlib", "numpy", "tkinter.test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QSL Sender",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no black console window for non-technical users
    icon=os.path.abspath("icon.ico") if os.path.exists("icon.ico") else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="QSL Sender",
)
