from loot_player.app import main, selfcheck
from loot_player.version import __version__


def test_version_flag_prints_version_and_returns_zero(capsys):
    rc = main(["loot-player", "--version"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == __version__


def test_selfcheck_passes_with_system_vlc():
    # Dev box and CI both have system VLC + PyQt6 installed.
    assert selfcheck() == 0
