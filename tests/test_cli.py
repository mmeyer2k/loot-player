from loot_player.app import main, selfcheck, _icon_path, _LOGO_PATH
from loot_player.version import __version__


def test_version_flag_prints_version_and_returns_zero(capsys):
    rc = main(["loot-player", "--version"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == __version__


def test_selfcheck_passes_with_system_vlc():
    # Dev box and CI both have system VLC + PyQt6 installed.
    assert selfcheck() == 0


def test_icon_path_prefers_env_when_file_exists(tmp_path, monkeypatch):
    icon = tmp_path / "loot.png"
    icon.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setenv("LOOT_PLAYER_ICON", str(icon))
    assert _icon_path() == str(icon)


def test_icon_path_falls_back_when_env_unset(monkeypatch):
    monkeypatch.delenv("LOOT_PLAYER_ICON", raising=False)
    assert _icon_path() == str(_LOGO_PATH)


def test_icon_path_falls_back_when_env_points_at_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOT_PLAYER_ICON", str(tmp_path / "nope.png"))
    assert _icon_path() == str(_LOGO_PATH)
