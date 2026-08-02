from pathlib import Path

import loot_player
from loot_player.app import _LOGO_PATH


def test_logo_resolves_to_an_existing_file():
    assert _LOGO_PATH.is_file(), _LOGO_PATH


def test_logo_lives_inside_the_package():
    # parent.parent path resolution broke the moment the package was
    # installed rather than run from a checkout. Keep the asset in-package.
    package_root = Path(loot_player.__file__).resolve().parent
    assert package_root in _LOGO_PATH.resolve().parents


def test_logo_is_svg():
    assert _LOGO_PATH.suffix == ".svg"
    assert "<svg" in _LOGO_PATH.read_text()
