# PyInstaller spec for the Windows build (one-folder).
#
# One-folder rather than one-file on purpose: it starts faster (one-file
# unpacks to a temp directory on every launch) and is flagged far less often
# by SmartScreen and antivirus.
#
# Build:  pyinstaller packaging/qsl-send.spec --noconfirm
import os

# Resolve everything against the spec file's own directory, never the working
# directory. PyInstaller may be invoked from the repository root or from
# packaging/, and os.path.abspath("..") silently pointed outside the project
# when run from the root — so the package was never analysed and the built
# application failed with "No module named qsl_send".
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

block_cipher = None

datas = [
    (os.path.join(PROJECT_ROOT, "qsl-send.example.yaml"), "."),
    (os.path.join(PROJECT_ROOT, "template.jpg"), "."),
    (os.path.join(PROJECT_ROOT, "README.md"), "."),
]
datas = [(s, d) for s, d in datas if os.path.exists(s)]

a = Analysis(
    [os.path.join(SPEC_DIR, "launcher.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    # qsl_send is listed explicitly as a safety net: the launcher now imports
    # it at module level, but naming it here means a future refactor of the
    # launcher cannot silently drop the package from the bundle again.
    hiddenimports=[
        "PIL._tkinter_finder",
        "qsl_send",
        "qsl_send.cli",
        "qsl_send.gui",
        "qsl_send.adif",
        "qsl_send.config",
        "qsl_send.contacts",
        "qsl_send.detect",
        "qsl_send.fields",
        "qsl_send.i18n",
        "qsl_send.mailer",
        "qsl_send.pipeline",
        "qsl_send.qrz",
        "qsl_send.render",
        "qsl_send.report",
        "qsl_send.sending",
        "qsl_send.settings_io",
        "qsl_send.workspace",
    ],
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
    icon=(
        os.path.join(SPEC_DIR, "icon.ico")
        if os.path.exists(os.path.join(SPEC_DIR, "icon.ico"))
        else None
    ),
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
