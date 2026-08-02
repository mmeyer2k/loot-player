"""Preflight for a usable libVLC.

``vlc.py`` raises NotImplementedError at import time when libvlc.so.5 is
absent, and ``loot_player.app`` imports it transitively through ``player``.
Inside an AppImage that happens before any window exists, so launching from
a desktop menu does nothing visible at all.

The AppImage deliberately does not bundle libVLC (see
docs/superpowers/specs/2026-08-01-appimage-build-design.md), so AppRun calls
this module when the import fails and the user gets a dialog instead of a
traceback nobody sees.
"""

from __future__ import annotations

import os
import sys

HEADLINE = "loot could not find VLC."

INSTALL_HINTS = (
    ("Debian / Ubuntu", "sudo apt install vlc"),
    ("Fedora", "sudo dnf install vlc"),
    ("Arch", "sudo pacman -S vlc"),
)


def libvlc_available() -> bool:
    """True when the VLC shared library can be loaded."""
    try:
        import vlc  # noqa: F401
    except Exception:
        return False
    return True


def missing_vlc_message() -> str:
    """The body of the 'install VLC' message, without the headline."""
    lines = [
        "loot plays media through the VLC libraries installed on your "
        "system, and they do not appear to be present.",
        "",
        "Install VLC, then start loot again:",
        "",
    ]
    lines += [f"    {label}:  {command}" for label, command in INSTALL_HINTS]
    return "\n".join(lines)


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main() -> int:
    body = missing_vlc_message()
    print(f"{HEADLINE}\n\n{body}", file=sys.stderr)

    # Headless: printing is all we can do. Never construct a dialog here, a
    # modal exec() with nobody to dismiss it blocks forever under CI.
    if not _has_display():
        return 1

    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except Exception:
        return 1

    app = QApplication.instance() or QApplication([])
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("loot")
    box.setText(HEADLINE)
    box.setInformativeText(body)
    box.exec()
    del app
    return 1


if __name__ == "__main__":
    sys.exit(main())
