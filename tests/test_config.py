import json

from openmine.config import (
    TOP_TIMES,
    Settings,
    Stats,
    config_dir,
    describe_key,
    format_time,
    stats_key,
)
from openmine.game import BEGINNER, EXPERT, custom_difficulty


def test_config_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMINE_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path


def test_config_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENMINE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "openmine"


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings.load(path)
    assert settings.difficulty == "beginner"
    settings.difficulty = "expert"
    settings.theme = "dark"
    settings.no_guess = True
    settings.save()
    loaded = Settings.load(path)
    assert loaded.difficulty == "expert"
    assert loaded.theme == "dark"
    assert loaded.no_guess is True
    assert loaded.current_difficulty() is EXPERT


def test_settings_survive_garbage(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert Settings.load(path).difficulty == "beginner"
    path.write_text(
        json.dumps(
            {
                "difficulty": "impossible",
                "theme": "purple",
                "animations": "yes",
                "custom_cols": 9999,
                "custom_rows": 2,
                "custom_mines": True,
                "window_geometry": 12,
            }
        )
    )
    settings = Settings.load(path)
    assert settings.difficulty == "beginner"
    assert settings.theme == "system"
    assert settings.animations is True
    assert settings.window_geometry is None
    custom = custom_difficulty(settings.custom_cols, settings.custom_rows, settings.custom_mines)
    assert (custom.cols, custom.rows, custom.mines) == (
        settings.custom_cols,
        settings.custom_rows,
        settings.custom_mines,
    )


def test_custom_settings_difficulty(tmp_path):
    settings = Settings.load(tmp_path / "s.json")
    settings.difficulty = "custom"
    settings.custom_cols, settings.custom_rows, settings.custom_mines = 20, 10, 50
    d = settings.current_difficulty()
    assert (d.cols, d.rows, d.mines) == (20, 10, 50)
    assert d.is_custom


def test_stats_records_and_ranks(tmp_path):
    path = tmp_path / "stats.json"
    stats = Stats(path)
    key = stats_key(BEGINNER, False)
    assert stats.record_game(key, True, 30.0) == 1
    assert stats.record_game(key, True, 20.0) == 1
    assert stats.record_game(key, True, 25.0) == 2
    assert stats.record_game(key, False, 3.0) == 0
    assert stats.record_game(key, True, 10.0, counts_for_times=False) == 0
    record = Stats(path).get(key)
    assert record.played == 5
    assert record.won == 4
    assert record.streak == 1
    assert record.best_streak == 3
    assert record.best_time == 20.0
    assert [t["time"] for t in record.times] == [20.0, 25.0, 30.0]
    assert record.average_time == (30 + 20 + 25) / 3  # the assisted win doesn't count


def test_stats_keep_top_times_only(tmp_path):
    stats = Stats(tmp_path / "stats.json")
    for t in range(TOP_TIMES + 5):
        stats.record_game("expert", True, 100.0 - t)
    record = stats.get("expert")
    assert len(record.times) == TOP_TIMES
    assert record.best_time == 100.0 - (TOP_TIMES + 4)
    assert stats.record_game("expert", True, 500.0) == 0


def test_stats_reset(tmp_path):
    stats = Stats(tmp_path / "stats.json")
    stats.record_game("beginner", True, 5)
    stats.record_game("expert", False, 5)
    stats.reset("beginner")
    assert stats.get("beginner").played == 0
    assert stats.get("expert").played == 1
    stats.reset()
    assert Stats(tmp_path / "stats.json").keys() == []


def test_corrupt_stats_are_ignored(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps({"records": {"beginner": {"played": "x", "times": [1, {"time": 3}]}, "bad": 5}}))
    stats = Stats(path)
    record = stats.get("beginner")
    assert record.played == 0
    assert record.times == [{"time": 3}]
    assert "bad" not in stats.keys()


def test_stats_keys_and_descriptions():
    assert stats_key(EXPERT, True) == "expert-noguess"
    custom = custom_difficulty(20, 10, 50)
    assert stats_key(custom, False) == "custom-20x10-50"
    assert describe_key("expert-noguess") == "Expert (no guessing)"
    assert describe_key("custom-20x10-50") == "Custom 20 × 10, 50 mines"


def test_format_time():
    assert format_time(None) == "—"
    assert format_time(9.94) == "9.9 s"
    assert format_time(75.25) == "1:15.2"


def test_format_time_never_shows_60_seconds():
    assert format_time(59.96) == "1:00.0"
    assert format_time(119.96) == "2:00.0"
    assert format_time(59.94) == "59.9 s"


def test_average_time_ignores_assisted_wins(tmp_path):
    stats = Stats(tmp_path / "stats.json")
    stats.record_game("beginner", True, 10.0)
    stats.record_game("beginner", True, 100.0, counts_for_times=False)
    record = stats.get("beginner")
    assert record.won == 2
    assert record.average_time == 10.0


def test_stats_with_records_list_do_not_crash(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps({"records": []}))
    assert Stats(path).keys() == []
