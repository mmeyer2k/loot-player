from loot_player.app import main
from loot_player.version import __version__


def test_version_flag_prints_version_and_returns_zero(capsys):
    rc = main(["loot-player", "--version"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == __version__
