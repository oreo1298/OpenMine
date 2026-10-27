# PyInstaller spec for the Windows build.
#
#   pip install pyinstaller PySide6-Essentials
#   pyinstaller --noconfirm packaging/windows/openmine.spec
#
# Produces dist/OpenMine/OpenMine.exe (a folder build: starts fast and lets
# users replace the LGPL Qt libraries if they want to).

import re
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821 (SPECPATH is set by PyInstaller)
HERE = ROOT / "packaging" / "windows"
VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "src" / "openmine" / "__init__.py").read_text()
).group(1)


def version_resource():
    try:
        from PyInstaller.utils.win32.versioninfo import (
            FixedFileInfo,
            StringFileInfo,
            StringStruct,
            StringTable,
            VarFileInfo,
            VarStruct,
            VSVersionInfo,
        )
    except ImportError:
        return None
    numbers = tuple(int(x) for x in re.findall(r"\d+", VERSION)[:3]) + (0,)
    numbers = (numbers + (0, 0, 0, 0))[:4]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "OpenMine contributors"),
                            StringStruct("FileDescription", "OpenMine"),
                            StringStruct("FileVersion", VERSION),
                            StringStruct("InternalName", "OpenMine"),
                            StringStruct("LegalCopyright", "GPL-3.0-or-later"),
                            StringStruct("OriginalFilename", "OpenMine.exe"),
                            StringStruct("ProductName", "OpenMine"),
                            StringStruct("ProductVersion", VERSION),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


a = Analysis(  # noqa: F821
    [str(HERE / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "openmine" / "assets"), "openmine/assets")],
    # QtDBus is only used on Linux; the rest is never imported by the game.
    excludes=["tkinter", "PySide6.QtDBus", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenMine",
    icon=str(HERE / "openmine.ico"),
    version=version_resource(),
    console=False,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="OpenMine",
    upx=False,
)
