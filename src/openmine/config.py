"""Settings and statistics persistence (plain JSON files).

Linux:   $XDG_CONFIG_HOME/openmine/   (usually ~/.config/openmine/)
Windows: %APPDATA%\\OpenMine\\
macOS:   ~/Library/Application Support/OpenMine/
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

from openmine.game import PRESETS, Difficulty, custom_difficulty

THEMES = ("system", "light", "dark")
TOP_TIMES = 10


def config_dir() -> Path:
    override = os.environ.get("OPENMINE_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / "OpenMine"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenMine"
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "openmine"


def _load(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _coerce(value: Any, default: Any) -> Any:
    """Return ``value`` if it has the same type as ``default``, else ``default``."""
    if default is None:
        return value if isinstance(value, str) else None
    if isinstance(default, bool) or isinstance(value, bool):
        return value if isinstance(value, bool) and isinstance(default, bool) else default
    if isinstance(default, float) and isinstance(value, int):
        return float(value)
    return value if isinstance(value, type(default)) else default


def _save(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:  # never crash the game because a file can't be written
        print(f"openmine: could not save {path}: {exc}", file=sys.stderr)


@dataclass
class Settings:
    difficulty: str = "beginner"
    custom_cols: int = 20
    custom_rows: int = 12
    custom_mines: int = 40
    theme: str = "system"
    question_marks: bool = False
    no_guess: bool = False
    animations: bool = True
    chord_on_click: bool = True
    window_geometry: Optional[str] = None

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        path = path or config_dir() / "settings.json"
        data = _load(path)
        settings = cls()
        for f in fields(cls):
            if f.name in data:
                setattr(settings, f.name, _coerce(data[f.name], getattr(settings, f.name)))
        if settings.theme not in THEMES:
            settings.theme = "system"
        if settings.difficulty not in PRESETS and settings.difficulty != "custom":
            settings.difficulty = "beginner"
        custom = custom_difficulty(settings.custom_cols, settings.custom_rows, settings.custom_mines)
        settings.custom_cols, settings.custom_rows, settings.custom_mines = (
            custom.cols,
            custom.rows,
            custom.mines,
        )
        settings._path = path
        return settings

    def save(self) -> None:
        _save(getattr(self, "_path", None) or config_dir() / "settings.json", asdict(self))

    def current_difficulty(self) -> Difficulty:
        if self.difficulty in PRESETS:
            return PRESETS[self.difficulty]
        return custom_difficulty(self.custom_cols, self.custom_rows, self.custom_mines)


def stats_key(difficulty: Difficulty, no_guess: bool) -> str:
    """Records are kept separately per board size and per no-guess mode."""
    if difficulty.is_custom:
        key = f"custom-{difficulty.cols}x{difficulty.rows}-{difficulty.mines}"
    else:
        key = difficulty.key
    return key + ("-noguess" if no_guess else "")


@dataclass
class Record:
    played: int = 0
    won: int = 0
    streak: int = 0
    best_streak: int = 0
    total_win_time: float = 0.0
    times: list = field(default_factory=list)  # [{"time": float, "date": str}], fastest first

    @property
    def best_time(self) -> Optional[float]:
        return self.times[0]["time"] if self.times else None

    @property
    def win_rate(self) -> float:
        return self.won / self.played if self.played else 0.0

    @property
    def average_time(self) -> Optional[float]:
        return self.total_win_time / self.won if self.won else None


class Stats:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or config_dir() / "stats.json"
        self.records: dict[str, Record] = {}
        for key, raw in _load(self.path).get("records", {}).items():
            if not isinstance(raw, dict):
                continue
            record = Record()
            for f in fields(Record):
                if f.name in raw:
                    setattr(record, f.name, _coerce(raw[f.name], getattr(record, f.name)))
            record.times = [
                t for t in record.times if isinstance(t, dict) and isinstance(t.get("time"), (int, float))
            ]
            self.records[key] = record

    def get(self, key: str) -> Record:
        return self.records.get(key) or Record()

    def keys(self) -> list[str]:
        return list(self.records)

    def record_game(self, key: str, won: bool, seconds: float, counts_for_times: bool = True) -> int:
        """Store a finished game. Returns the rank (1-based) of a winning time, or 0."""
        record = self.records.setdefault(key, Record())
        record.played += 1
        rank = 0
        if won:
            record.won += 1
            record.streak += 1
            record.best_streak = max(record.best_streak, record.streak)
            record.total_win_time += seconds
            if counts_for_times:
                entry = {"time": round(seconds, 3), "date": time.strftime("%Y-%m-%d %H:%M")}
                record.times.append(entry)
                record.times.sort(key=lambda t: t["time"])
                del record.times[TOP_TIMES:]
                if entry in record.times:
                    rank = record.times.index(entry) + 1
        else:
            record.streak = 0
        self.save()
        return rank

    def reset(self, key: Optional[str] = None) -> None:
        if key is None:
            self.records.clear()
        else:
            self.records.pop(key, None)
        self.save()

    def save(self) -> None:
        _save(self.path, {"version": 1, "records": {k: asdict(v) for k, v in self.records.items()}})


def describe_key(key: str) -> str:
    """Human readable name for a stats key."""
    no_guess = key.endswith("-noguess")
    base = key[: -len("-noguess")] if no_guess else key
    if base in PRESETS:
        label = PRESETS[base].label
    elif base.startswith("custom-"):
        try:
            dims, mines = base[len("custom-") :].split("-")
            cols, rows = dims.split("x")
            label = f"Custom {cols} × {rows}, {mines} mines"
        except ValueError:
            label = base
    else:
        label = base
    return label + (" (no guessing)" if no_guess else "")


def format_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}"

