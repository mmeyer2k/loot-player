import subprocess
import sys
import types
from pathlib import Path

from loot_player.vlc_check import (
    HEADLINE,
    INSTALL_HINTS,
    libvlc_available,
    missing_vlc_message,
)

REPO = Path(__file__).resolve().parent.parent


def test_message_names_every_install_command():
    message = missing_vlc_message()
    for _, command in INSTALL_HINTS:
        assert command in message


def test_install_hints_cover_apt_dnf_and_pacman():
    commands = " ".join(command for _, command in INSTALL_HINTS)
    assert "apt" in commands
    assert "dnf" in commands
    assert "pacman" in commands


def test_message_blames_vlc_not_the_python_binding():
    # python-vlc is bundled; the thing the user is missing is VLC itself.
    # Naming the binding would send them to the wrong package.
    message = f"{HEADLINE}\n{missing_vlc_message()}"
    assert "VLC" in message
    assert "python-vlc" not in message


def test_libvlc_available_reports_true_where_vlc_is_installed():
    # The README requires vlc for the from-source path, so a dev checkout
    # always has it. On its own this proves little: the old import-only probe
    # also returned True with no VLC at all. The two False cases below are
    # what give this one meaning.
    assert libvlc_available() is True


def test_libvlc_available_reports_false_when_the_symbol_is_missing(monkeypatch):
    # The real no-VLC shape. vlc.py imports cleanly off a dlopen(NULL) handle
    # and the symbol lookup is the thing that fails, so an import-only probe
    # misses it. Simulated because CI machines that do have VLC cannot
    # otherwise reach this branch.
    stub = types.ModuleType("vlc")

    def _missing():
        raise NameError("no function 'libvlc_get_version'")

    stub.libvlc_get_version = _missing
    monkeypatch.setitem(sys.modules, "vlc", stub)

    assert libvlc_available() is False


def test_libvlc_available_reports_false_when_the_import_fails(monkeypatch):
    # A None entry in sys.modules makes `import vlc` raise ImportError.
    monkeypatch.setitem(sys.modules, "vlc", None)

    assert libvlc_available() is False


def test_module_run_exits_nonzero_without_a_display():
    proc = subprocess.run(
        [sys.executable, "-m", "loot_player.vlc_check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )
    assert proc.returncode == 1
    assert HEADLINE in proc.stderr
    # No DISPLAY means no dialog, so this must not block.
