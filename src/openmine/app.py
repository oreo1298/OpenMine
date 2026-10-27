"""Application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from openmine import APP_ID, APP_NAME, __version__

ASSETS = Path(__file__).resolve().parent / "assets"


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="openmine",
        description=f"{APP_NAME} — a free and open source Minesweeper.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--difficulty",
        choices=["beginner", "intermediate", "expert"],
        help="start with this difficulty",
    )
    parser.add_argument(
        "--theme", choices=["system", "light", "dark"], help="override the colour scheme for this run"
    )
    parser.add_argument(
        "--reset-window", action="store_true", help="forget the saved window size and position"
    )
    # Unknown arguments (e.g. Qt's -platform, -style) are passed on to Qt.
    return parser.parse_known_args(argv[1:])


def _app_icon():
    from PySide6.QtGui import QIcon

    from openmine.painting import app_icon_pixmap

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        png = ASSETS / f"{APP_ID}-{size}.png"
        if png.exists():
            icon.addFile(str(png))
    if icon.isNull():
        icon.addPixmap(app_icon_pixmap(256))
    return icon


def _windows_setup() -> None:
    # Group the taskbar button under our own icon instead of python.exe's.
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def main(argv: Optional[list[str]] = None) -> int:
    # Windowed builds (e.g. the Windows .exe) have no console streams.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    argv = list(sys.argv if argv is None else argv)
    args, qt_args = _parse_args(argv)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(
            f"{APP_NAME} needs PySide6 (Qt for Python) 6.5 or newer.\n"
            f"  Arch Linux:     sudo pacman -S pyside6\n"
            f"  Fedora:         sudo dnf install python3-pyside6\n"
            f"  Anything else:  run install.sh from the OpenMine repository, which sets it up for you\n"
            f"(import error: {exc})",
            file=sys.stderr,
        )
        return 1

    from openmine.config import Settings, Stats
    from openmine.theme import ThemeManager
    from openmine.window import MainWindow

    if sys.platform == "win32":
        _windows_setup()

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setDesktopFileName(APP_ID)
    # "openmine" becomes the X11 WM_CLASS instance name.
    app = QApplication(["openmine", *qt_args])
    app.setWindowIcon(_app_icon())

    settings = Settings.load()
    if args.difficulty:
        settings.difficulty = args.difficulty
    if args.reset_window:
        settings.window_geometry = None
    theme = ThemeManager(app, args.theme or settings.theme)
    stats = Stats()
    window = MainWindow(theme, settings, stats)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
