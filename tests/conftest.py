import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Keep tests away from the real settings and the desktop's theme portal."""
    monkeypatch.setenv("OPENMINE_CONFIG_DIR", str(tmp_path / "config"))
    try:
        import openmine.theme as theme
    except ImportError:  # PySide6 not installed: only the pure-Python tests run
        return

    class NoPortal:
        available = False
        scheme = None
        accent = None
        changed = type("Signal", (), {"connect": staticmethod(lambda *a: None)})()

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(theme, "Portal", NoPortal)
    monkeypatch.setattr(theme, "windows_color_scheme", lambda: None)
    monkeypatch.setattr(theme, "windows_accent", lambda: None)
