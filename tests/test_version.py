import re
import subprocess
import sys
from pathlib import Path

from loot_player.version import __version__

REPO = Path(__file__).resolve().parent.parent


def test_version_is_a_three_part_release_string():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_module_entrypoint_prints_version_and_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "loot_player", "--version"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"loot {__version__}"


def test_version_flag_does_not_need_a_display():
    proc = subprocess.run(
        [sys.executable, "-m", "loot_player", "--version"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )
    assert proc.returncode == 0, proc.stderr
