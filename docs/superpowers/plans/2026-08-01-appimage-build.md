# AppImage Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `make appimage` produces a single-file `dist/loot-<version>-x86_64.AppImage` that runs on any glibc 2.34+ x86_64 Linux with VLC installed.

**Architecture:** A bash script assembles an AppDir inside an `ubuntu:22.04` container: a relocatable CPython from python-build-standalone, `pip install .` on top of it, a Qt prune, an `ldd`-driven copy of the xcb libraries Qt's platform plugin needs, then `appimagetool`. libVLC is deliberately not bundled; `AppRun` preflights for it and shows a dialog when it is missing. CI runs the same script rather than a second build path.

**Tech Stack:** bash, podman/docker, python-build-standalone 3.13.14, appimagetool (`continuous`), setuptools, PyQt6, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-01-appimage-build-design.md`

## Global Constraints

- **glibc floor is 2.34.** Set by the only x86_64 Linux PyQt6 wheel tag, `manylinux_2_34_x86_64`. Not negotiable, not ours to choose.
- **Build container is `ubuntu:22.04`** (glibc 2.35). Never build the AppImage on the dev host (Ubuntu 26.04, glibc 2.43).
- **x86_64 only.** No aarch64 anywhere in this plan.
- **libVLC is never bundled.** No `libvlc.so*`, no `libvlccore.so*`, no `vlc/plugins/` tree in the AppDir. `vlc.py` (the pure-Python ctypes binding) is bundled; the library it binds to is not.
- **Pinned, never floating:** CPython `3.13.14+20260728`, asset `cpython-3.13.14+20260728-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz`. appimagetool tag `continuous`, asset `appimagetool-x86_64.AppImage`.
- **No new runtime dependencies.** The app's deps stay exactly `PyQt6`, `python-vlc`, `qtawesome`.
- **Existing modules stay untouched:** `db.py`, `scanner.py`, `player.py`, `matching.py`, `models.py`, and everything under `ui/`.
- **Tests:** `python3 -m pytest tests/ -v` must pass after every task.
- **Commit style** (from `CLAUDE.md`): lowercase scoped prefix (`feat(pkg):`, `fix:`, `docs:`), body explains *why*. Do not use the word "land".

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata. Makes `pip install .` possible, which is the whole basis of the build. |
| `loot_player/version.py` | The single version string. Read by pyproject, `--version`, and the CI tag guard. |
| `loot_player/__main__.py` | `python -m loot_player` entrypoint. AppRun uses this, not the console script. |
| `loot_player/vlc_check.py` | Detects missing libVLC and renders the user-facing message. Pure message-building split from Qt display so it is testable. |
| `loot_player/assets/loot.svg` | Icon, moved inside the package so it survives installation. |
| `packaging/appimage-excludelist` | Vendored AppImage denylist. Stops us bundling libc/libstdc++/libGL. |
| `packaging/AppRun` | AppImage entrypoint. Environment setup and the VLC preflight. |
| `packaging/loot-appimage.desktop` | Desktop entry for the AppImage (distinct from `loot.desktop.in`, which is for source checkouts). |
| `packaging/build-appimage.sh` | The build. Container-only. |
| `.github/workflows/appimage.yml` | Tag-triggered release build plus two smoke tests. |

---

### Task 1: Package metadata, version, and `--version`

Nothing can be installed into an AppDir until the project is installable. This task makes `pip install .` work and adds the flag CI uses to prove the AppImage's import graph is intact.

**Files:**
- Create: `pyproject.toml`
- Create: `loot_player/version.py`
- Create: `loot_player/__main__.py`
- Create: `tests/test_version.py`
- Modify: `loot_player/app.py` (imports near line 26, `main()` at line 760)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `loot_player.version.__version__: str` — dotted three-part release string.
  - `python3 -m loot_player --version` — prints `loot <version>` to stdout, exits 0.
  - `pip install .` — installs the `loot_player` package with `assets/*.svg` as package data.

- [ ] **Step 1: Write the failing test**

Create `tests/test_version.py`:

```python
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
```

The third test is the one that matters for CI: it strips `DISPLAY` from the environment and proves `--version` returns before `QApplication` is constructed. If someone later moves the flag handling below `QApplication(sys.argv)`, this fails.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_version.py -v`
Expected: FAIL, collection error `ModuleNotFoundError: No module named 'loot_player.version'`

- [ ] **Step 3: Create the version module**

Create `loot_player/version.py`:

```python
"""Single source of truth for the release version.

Read by pyproject.toml (dynamic version), the ``--version`` flag, and the
release workflow's tag guard. Bump this, then tag ``v<version>``.
"""

__version__ = "0.1.0"
```

- [ ] **Step 4: Create the module entrypoint**

Create `loot_player/__main__.py`:

```python
"""``python -m loot_player`` entrypoint.

AppRun invokes the app this way rather than through the ``loot-player``
console script, because a generated script's shebang is an absolute path
baked in at install time and does not survive relocation into an AppImage.
"""

from loot_player.app import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add the `--version` flag**

In `loot_player/app.py`, add to the import block (after the `from loot_player.ui.queue_panel import QueuePanel` line at line 26):

```python
from loot_player.version import __version__
```

Then replace `main()` (line 760) with:

```python
def main():
    # Handled before QApplication so `--version` works with no display. The
    # AppImage smoke test relies on this.
    if "--version" in sys.argv[1:]:
        print(f"{APP_BRAND} {__version__}")
        return
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = QIcon(str(_LOGO_PATH))
    app.setWindowIcon(icon)
    w = MainWindow()
    w.setWindowIcon(icon)
    w.show()
    w.video.attach()
    sys.exit(app.exec())
```

- [ ] **Step 6: Create pyproject.toml**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "loot-player"
description = "Local media library and player"
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "Mike" }]
dynamic = ["version"]
dependencies = [
    "PyQt6",
    "python-vlc",
    "qtawesome",
]

[project.scripts]
loot-player = "loot_player.app:main"

[tool.setuptools.dynamic]
version = { attr = "loot_player.version.__version__" }

[tool.setuptools.packages.find]
include = ["loot_player*"]

[tool.setuptools.package-data]
loot_player = ["assets/*.svg"]
```

`package-data` already points at `loot_player/assets/`, which Task 2 creates. That is deliberate: it is inert until the file moves, and it means Task 2 does not have to come back and edit this file.

- [ ] **Step 7: Ignore build output**

In `.gitignore`, add below the existing `.venv/` line:

```
dist/
build/
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: PASS, including the three new tests in `tests/test_version.py`.

- [ ] **Step 9: Verify the project is installable**

Run:
```bash
python3 -m pip install --dry-run --no-deps . 2>&1 | tail -5
```
Expected: no error, and output naming `loot_player-0.1.0`. This proves the build backend can read the dynamic version.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml loot_player/version.py loot_player/__main__.py \
        loot_player/app.py tests/test_version.py .gitignore
git commit -m "feat(pkg): add pyproject, version module, and --version

The AppImage build installs the app with pip, which needs real packaging
metadata. The stale gitignored egg-info described exactly this; it was
lost at some point and is recovered here.

--version returns before QApplication so the release workflow can smoke
test the AppImage without a display."
```

---

### Task 2: Move the icon inside the package

`app.py:31` resolves the logo relative to `parent.parent`, which is the repo root in a checkout and `site-packages` once installed. In the AppImage the icon would silently fail to load. Moving the asset inside the package and resolving it with `importlib.resources` fixes both cases.

**Files:**
- Move: `assets/loot.svg` to `loot_player/assets/loot.svg`
- Modify: `loot_player/app.py:5` (imports), `loot_player/app.py:31` (`_LOGO_PATH`)
- Modify: `packaging/loot.desktop.in` (`Icon=` line)
- Modify: `packaging/install-desktop.sh` (trailing `echo`)
- Modify: `README.md` (architecture tree, line 82 onward)
- Create: `tests/test_assets.py`

**Interfaces:**
- Consumes: `pyproject.toml`'s `[tool.setuptools.package-data]` from Task 1, which already declares `loot_player = ["assets/*.svg"]`.
- Produces: `loot_player.app._LOGO_PATH: pathlib.Path` — absolute path to an existing SVG, valid both in a checkout and when installed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_assets.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_assets.py -v`
Expected: `test_logo_lives_inside_the_package` FAILS. `test_logo_resolves_to_an_existing_file` still passes at this point, because the checkout layout happens to work. That is exactly the trap this task removes.

- [ ] **Step 3: Move the asset**

```bash
mkdir -p loot_player/assets
git mv assets/loot.svg loot_player/assets/loot.svg
rmdir assets
```

- [ ] **Step 4: Resolve it through importlib.resources**

In `loot_player/app.py`, change the stdlib import block (line 3-6) to add `files`:

```python
import os
import sys
from importlib.resources import files
from pathlib import Path
from typing import Optional
```

Then replace line 31:

```python
_LOGO_PATH = Path(str(files("loot_player") / "assets" / "loot.svg"))
```

`files()` returns a `Traversable`; for a normal filesystem package that is already a path, and `Path(str(...))` keeps `_LOGO_PATH` a `Path` so the existing `QIcon(str(_LOGO_PATH))` call in `main()` is unchanged.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: PASS, all three asset tests included.

- [ ] **Step 6: Update the source-checkout desktop entry**

In `packaging/loot.desktop.in`, change:

```
Icon=@REPO@/assets/loot.svg
```

to:

```
Icon=@REPO@/loot_player/assets/loot.svg
```

In `packaging/install-desktop.sh`, change the last line:

```bash
echo "Icon:      $REPO/loot_player/assets/loot.svg"
```

- [ ] **Step 7: Update the architecture tree in the README**

In `README.md`, in the `## Architecture (one-line tour)` block, add the new files. The `loot_player/` listing becomes:

```
loot_player/
├── app.py              # MainWindow, transport bar, all the wiring
├── db.py               # LibraryDB — schema, migrations, every SQL query
├── scanner.py          # Scanner QThread — os.scandir + matching.parse
├── matching.py         # parse_movie / parse_tv / parse_music / parse_generic
├── models.py           # FileRow dataclass + QueueModel
├── player.py           # VlcWidget (QFrame hosting libVLC)
├── version.py          # __version__, single source of truth
├── vlc_check.py        # "VLC not found" preflight used by the AppImage
├── assets/loot.svg     # app icon (in-package so it survives installation)
└── ui/
    ├── library_tree.py # The tree on the left (search + tree + "+ New Library")
    ├── library_editor.py
    └── queue_panel.py
```

`vlc_check.py` is listed here even though Task 3 creates it. That keeps the README from needing a third edit; if the tasks are run in order the gap lasts one commit.

- [ ] **Step 8: Verify the desktop installer still works**

Run: `make install-desktop`
Expected: prints `Installed: ...loot.desktop` and `Icon: <repo>/loot_player/assets/loot.svg`. Confirm the icon path it prints exists:
```bash
test -f "$(grep -oP '(?<=^Icon=).*' ~/.local/share/applications/loot.desktop)" && echo OK
```
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add -A loot_player/assets loot_player/app.py packaging/loot.desktop.in \
          packaging/install-desktop.sh tests/test_assets.py README.md
git commit -m "fix: resolve the app icon through importlib.resources

_LOGO_PATH used Path(__file__).parent.parent, which is the repo root in a
checkout but site-packages once installed, so the icon silently vanished
in a packaged build. Move the asset into the package and look it up the
way an installed package has to."
```

---

### Task 3: libVLC preflight

> **Correction, made during Task 4.** This section originally said `vlc.py`
> raises `NotImplementedError` at import time when `libvlc.so.5` is absent.
> That is wrong, and the error propagated into the shipped code before it was
> caught. `import vlc` **succeeds with no VLC installed**: on Linux `vlc.py`
> calls `ctypes.CDLL(find_library("vlc"))`, `find_library` returns None, and
> `ctypes.CDLL(None)` is `dlopen(NULL)`, which returns the running program's
> own symbol table rather than raising. The `libvlc.so.5` fallback that would
> raise is never reached. The real failure is the first libvlc symbol lookup,
> so the probe must call one. The code blocks below are corrected in place;
> the shipped files are the source of truth.

`loot_player.app` imports `player`, which imports `vlc`, so a missing VLC breaks before any window exists. From a desktop menu that is a silent no-op. This module turns it into something a user can act on.

**Files:**
- Create: `loot_player/vlc_check.py`
- Create: `tests/test_vlc_check.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `loot_player.vlc_check.HEADLINE: str`
  - `loot_player.vlc_check.INSTALL_HINTS: tuple[tuple[str, str], ...]` — `(distro_label, install_command)` pairs.
  - `loot_player.vlc_check.libvlc_available() -> bool`
  - `loot_player.vlc_check.missing_vlc_message() -> str`
  - `loot_player.vlc_check.main() -> int` — always returns 1. Prints to stderr; shows a `QMessageBox` only when a display is present.
  - `python3 -m loot_player.vlc_check` — exits 1. Task 4's `AppRun` invokes exactly this.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vlc_check.py`:

```python
import subprocess
import sys
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
    # always has it.
    assert libvlc_available() is True


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
```

The last test is the one that keeps CI from hanging. A `QMessageBox.exec()` under a headless CI runner blocks forever with nobody to click it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_vlc_check.py -v`
Expected: FAIL, collection error `ModuleNotFoundError: No module named 'loot_player.vlc_check'`

- [ ] **Step 3: Write the module**

Create `loot_player/vlc_check.py`:

```python
"""Preflight for a usable libVLC.

``loot_player.app`` imports ``vlc`` transitively through ``player``. Inside
an AppImage that happens before any window exists, so launching from a
desktop menu does nothing visible at all.

Detecting the missing library takes more than ``import vlc``, which succeeds
on a machine with no VLC installed. On Linux ``vlc.py`` does
``ctypes.CDLL(find_library("vlc"))``, and with VLC absent ``find_library``
returns None, so that call is ``ctypes.CDLL(None)``. That is ``dlopen(NULL)``,
which hands back the running program's own symbol table rather than raising,
so the fallback to ``libvlc.so.5`` never runs and the module imports cleanly.
The first lookup of a real libvlc symbol is where it actually breaks. Probe
by calling one.

The AppImage deliberately does not bundle libVLC (see
docs/superpowers/specs/2026-08-01-appimage-build-design.md), so AppRun calls
this module when the probe fails and the user gets a dialog instead of a
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
    """True when libVLC is present and can actually be called into.

    Calls a symbol rather than just importing. See the module docstring for
    why the import alone succeeds with no VLC installed.
    """
    try:
        import vlc

        vlc.libvlc_get_version()
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Eyeball the dialog once**

Run: `python3 -m loot_player.vlc_check; echo "exit=$?"`
Expected: the message on stderr, a dialog appears, and after dismissing it `exit=1`. This is the only manual check in the task; the dialog is the whole point of the module.

- [ ] **Step 6: Commit**

```bash
git add loot_player/vlc_check.py tests/test_vlc_check.py
git commit -m "feat: add a libVLC preflight with a real error dialog

The AppImage links against the host's VLC rather than bundling it, so a
missing VLC is a supported failure mode and needs to say so. import vlc
raises at import time, before any window exists, which from a desktop
menu looks like the app simply did not start.

Skips the dialog when there is no display, so the headless release smoke
test cannot block on a modal nobody can dismiss."
```

---

### Task 4: Build the AppImage

The build itself. Ends with a runnable file.

> **Correction, made during Task 4.** The build script below bundles glib as a
> side effect of the `ldd` walk on `libqxcb.so`, and that breaks the host's VLC
> plugins: 8 of 382 failed with `undefined symbol: g_dir_unref`, including
> `libavcodec_plugin.so` and `libavformat_plugin.so`. No glib-family library
> may enter the AppDir, because this AppImage dlopens the host's libVLC. The
> shipped script adds `packaging/appimage-extra-excludes`, strips trailing
> comments before matching the vendored list, skips libraries already inside
> the AppDir, gates on Ubuntu 22.04, and fails the build if libvlc or glib
> appears. See the spec's "why glib may never be bundled". The shipped files
> are the source of truth, not the blocks below.

**Files:**
- Create: `packaging/appimage-excludelist`
- Create: `packaging/AppRun`
- Create: `packaging/loot-appimage.desktop`
- Create: `packaging/build-appimage.sh`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `pip install .` (Task 1), `python -m loot_player --version` (Task 1), `loot_player/assets/loot.svg` (Task 2), `python -m loot_player.vlc_check` (Task 3).
- Produces: `dist/loot-<version>-x86_64.AppImage`, and the `appimage` / `appimage-clean` make targets.

- [ ] **Step 1: Vendor the AppImage excludelist**

```bash
curl -fsSL https://raw.githubusercontent.com/AppImage/pkg2appimage/master/excludelist \
  -o packaging/appimage-excludelist
grep -c . packaging/appimage-excludelist
grep -qx 'libc.so.6' packaging/appimage-excludelist && echo "contains libc.so.6"
```
Expected: a non-zero line count (53 non-comment entries at the time of writing) and `contains libc.so.6`.

Vendored rather than fetched at build time so builds are reproducible and work offline. This file is what stops the `ldd` walk in step 4 from bundling libc, libstdc++, libgcc_s, libGL and libdrm. Bundled C++ and graphics libraries loaded next to the host's GPU driver is the classic way an AppImage segfaults on one machine and works on another.

- [ ] **Step 2: Write AppRun**

Create `packaging/AppRun`:

```bash
#!/usr/bin/env bash
# AppImage entrypoint. Everything runs from a read-only squashfs mount, so
# every path is relative to $APPDIR.
set -euo pipefail

APPDIR="${APPDIR:-$(dirname "$(readlink -f "$0")")}"
PY="$APPDIR/usr/bin/python3"

# libVLC's set_xwindow needs a real X11 window handle, which a native Wayland
# Qt session does not hand out. A no-op on X11, since xcb is the default there.
# Defaulted rather than forced so it can still be overridden.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

# A KDE session exports these pointing at the host's Qt 6. The bundled Qt
# loading host plugins mixes ABIs and crashes on startup.
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH

export LD_LIBRARY_PATH="$APPDIR/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# libVLC is deliberately not bundled. Without this the failure surfaces deep
# in the import graph and a desktop-menu launch shows nothing on screen.
#
# Corrected during Task 4: probe by calling a libvlc symbol, not by importing.
# `import vlc` succeeds with no VLC installed; see the Task 3 correction note.
if ! "$PY" -c "import vlc; vlc.libvlc_get_version()" >/dev/null 2>&1; then
    exec "$PY" -m loot_player.vlc_check
fi

exec "$PY" -m loot_player "$@"
```

Then: `chmod +x packaging/AppRun`

- [ ] **Step 3: Write the AppImage desktop entry**

Create `packaging/loot-appimage.desktop`:

```
[Desktop Entry]
Type=Application
Name=loot
GenericName=Media Player
Comment=Local media library and player
Exec=AppRun
Icon=loot
Terminal=false
Categories=AudioVideo;Player;Video;
StartupWMClass=loot-player
```

This is separate from `packaging/loot.desktop.in` on purpose. That one is templated with an absolute `@REPO@` path for source checkouts; this one uses the AppImage-relative `Exec=AppRun` and a bare `Icon=loot` that must match the `loot.svg` basename at the AppDir root.

- [ ] **Step 4: Write the build script**

Create `packaging/build-appimage.sh`:

```bash
#!/usr/bin/env bash
# Build dist/loot-<version>-x86_64.AppImage.
#
# CONTAINER ONLY. Run it through `make appimage`, which starts ubuntu:22.04
# for you. It apt-installs build dependencies and expects to be root.
#
# Why 22.04: PyQt6 publishes exactly one x86_64 Linux wheel tag,
# manylinux_2_34, so glibc 2.34 is the floor no matter what. 22.04 ships
# glibc 2.35, which sits at that floor. Building on a newer host produces a
# binary that runs on almost nothing.
#
# libVLC is deliberately NOT bundled; the AppImage links against the host's
# VLC. See docs/superpowers/specs/2026-08-01-appimage-build-design.md.

set -euo pipefail

PYTHON_VERSION="3.13.14"
PYTHON_MINOR="3.13"
PYTHON_BUILD="20260728"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_BUILD}/cpython-${PYTHON_VERSION}+${PYTHON_BUILD}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$REPO/build"
APPDIR="$BUILD/AppDir"
CACHE="$BUILD/cache"
DIST="$REPO/dist"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO/loot_player/version.py")"
[ -n "$VERSION" ] || { echo "could not read __version__" >&2; exit 1; }
OUT="$DIST/loot-${VERSION}-x86_64.AppImage"

log() { printf '\n==> %s\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
    log "Installing build dependencies"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    # curl/ca-certificates to fetch, file/desktop-file-utils for appimagetool,
    # and the xcb runtime so ldd can resolve the Qt platform plugin's needs.
    apt-get install -y -qq --no-install-recommends \
        curl ca-certificates file desktop-file-utils \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxkbcommon-x11-0 libsm6 libice6 libgl1 libegl1 \
        libfontconfig1 libdbus-1-3 >/dev/null
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr" "$CACHE" "$DIST"

log "Fetching CPython ${PYTHON_VERSION}"
PBS_TAR="$CACHE/cpython-${PYTHON_VERSION}-${PYTHON_BUILD}.tar.gz"
[ -f "$PBS_TAR" ] || curl -fsSL "$PBS_URL" -o "$PBS_TAR"
tar -xf "$PBS_TAR" -C "$APPDIR/usr" --strip-components=1

PY="$APPDIR/usr/bin/python3"
"$PY" -V

log "Installing loot and its dependencies"
"$PY" -m pip install --no-cache-dir --quiet --upgrade pip setuptools
"$PY" -m pip install --no-cache-dir --quiet "$REPO"

SITE="$APPDIR/usr/lib/python${PYTHON_MINOR}/site-packages"
QT6="$SITE/PyQt6/Qt6"
[ -d "$QT6" ] || { echo "PyQt6/Qt6 missing at $QT6" >&2; exit 1; }

# libVLC must never end up inside the AppDir.
if find "$APPDIR" -name 'libvlc*.so*' -print -quit | grep -q .; then
    echo "libvlc found in AppDir; it must not be bundled" >&2
    exit 1
fi

log "Pruning unused Qt modules"
# loot imports QtCore, QtGui and QtWidgets only.
rm -rf "$QT6/qml" "$QT6/translations" "$QT6/plugins/qmltooling"
rm -f "$QT6"/lib/libQt6Quick*.so* "$QT6"/lib/libQt6Qml*.so*

log "Deploying xcb libraries for the Qt platform plugin"
mkdir -p "$APPDIR/usr/lib"
QXCB="$QT6/plugins/platforms/libqxcb.so"
[ -f "$QXCB" ] || { echo "libqxcb.so missing at $QXCB" >&2; exit 1; }

if ldd "$QXCB" | grep -q 'not found'; then
    echo "unresolved dependencies for libqxcb.so:" >&2
    ldd "$QXCB" | grep 'not found' >&2
    echo "add the providing package to the apt-get list above" >&2
    exit 1
fi

while read -r lib; do
    base="$(basename "$lib")"
    grep -qxF "$base" "$REPO/packaging/appimage-excludelist" && continue
    [ -e "$APPDIR/usr/lib/$base" ] && continue
    cp -L "$lib" "$APPDIR/usr/lib/$base"
    echo "    + $base"
done < <(ldd "$QXCB" | awk '/=> \//{print $3}' | sort -u)

log "Writing AppDir metadata"
install -Dm755 "$REPO/packaging/AppRun" "$APPDIR/AppRun"
install -Dm644 "$REPO/packaging/loot-appimage.desktop" "$APPDIR/loot.desktop"
install -Dm644 "$REPO/loot_player/assets/loot.svg" "$APPDIR/loot.svg"
install -Dm644 "$REPO/packaging/loot-appimage.desktop" \
    "$APPDIR/usr/share/applications/loot.desktop"
install -Dm644 "$REPO/loot_player/assets/loot.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/loot.svg"

log "Packaging"
TOOL="$CACHE/appimagetool-x86_64.AppImage"
if [ ! -f "$TOOL" ]; then
    curl -fsSL "$APPIMAGETOOL_URL" -o "$TOOL"
    chmod +x "$TOOL"
fi
rm -f "$OUT"
# No /dev/fuse in the build container, so appimagetool has to unpack itself.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOL" "$APPDIR" "$OUT" >/dev/null

log "Built $OUT ($(du -h "$OUT" | cut -f1))"
```

Then: `chmod +x packaging/build-appimage.sh`

Two guards worth noticing. The `find ... libvlc*` check enforces the central design decision mechanically rather than by memory. The `ldd | grep 'not found'` check turns a missing apt package into a build failure with a clear message, instead of an AppImage that fails at Qt init on a user's machine.

- [ ] **Step 5: Add the make targets**

In `Makefile`, add `appimage` and `appimage-clean` to the `.PHONY` line, and append:

```make
# Prefer podman; docker works too. Override with CONTAINER_ENGINE=docker.
CONTAINER_ENGINE ?= $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
APPIMAGE_IMAGE ?= docker.io/library/ubuntu:22.04

# Built in ubuntu:22.04 because PyQt6's only x86_64 wheel is manylinux_2_34,
# so glibc 2.34 is the floor. Building on the host would target its glibc.
appimage:
	@test -n "$(CONTAINER_ENGINE)" || { echo "need podman or docker"; exit 1; }
	$(CONTAINER_ENGINE) run --rm -v "$(CURDIR)":/src:Z -w /src \
	  $(APPIMAGE_IMAGE) /src/packaging/build-appimage.sh

appimage-clean:
	rm -rf build dist
```

The `.PHONY` line becomes:

```make
.PHONY: run test install-desktop clean appimage appimage-clean
```

- [ ] **Step 6: Build it**

Run: `make appimage`
Expected: the script's `==>` progress lines, a list of `+ libxcb-*.so.*` copies, and a final `==> Built /src/dist/loot-0.1.0-x86_64.AppImage (NNM)`.

If the `ldd ... not found` guard trips, add the named package to the `apt-get install` list in the script and rerun. That is the guard doing its job.

- [ ] **Step 7: Verify it runs**

```bash
chmod +x dist/loot-0.1.0-x86_64.AppImage
./dist/loot-0.1.0-x86_64.AppImage --appimage-extract-and-run --version
```
Expected: `loot 0.1.0`

`--appimage-extract-and-run` is used because Ubuntu 24.04 and later, including this dev machine, do not install FUSE 2 by default. If `libfuse2t64` is present the bare invocation works too; try it and note which applies.

- [ ] **Step 8: Verify it actually plays media**

Run: `./dist/loot-0.1.0-x86_64.AppImage --appimage-extract-and-run`

Check, in order:
1. The window opens and the titlebar icon is the loot logo. This is the case Task 2 fixed; a generic icon means `_LOGO_PATH` is still wrong.
2. The existing library tree is populated. The AppImage reads the same `~/.local/share/loot-player/library.db` as a source checkout.
3. Play a video file. Confirm picture and sound.
4. Play an audio file. Confirm sound.
5. Toggle fullscreen with `F`, then `Esc`.

Step 3 is the real test of the "do not bundle libVLC" decision. If video plays, the host's libVLC and its plugins are being found correctly through the bundled `vlc.py`.

- [ ] **Step 9: Verify the missing-VLC path**

```bash
podman run --rm -v "$PWD":/src -w /src docker.io/library/ubuntu:22.04 \
  ./dist/loot-0.1.0-x86_64.AppImage --appimage-extract-and-run --version; echo "exit=$?"
```
Expected: the `loot could not find VLC.` headline and the three install commands on stderr, then `exit=1`. No traceback, and no hang. A clean `ubuntu:22.04` has no VLC and no display, which is exactly the case this must handle.

- [ ] **Step 10: Commit**

```bash
git add packaging/appimage-excludelist packaging/AppRun \
        packaging/loot-appimage.desktop packaging/build-appimage.sh Makefile
git commit -m "feat(packaging): build a single-file AppImage

Bundles a relocatable CPython, PyQt6 and the app, and links against the
host's VLC rather than shipping libvlc plus ~400 plugins. The plugin tree
is where AppImages break and the failures are silent at runtime, so the
trade is one apt install against a whole class of bugs.

Built in ubuntu:22.04 because PyQt6's only x86_64 wheel is
manylinux_2_34; building on the dev host would target glibc 2.43 and run
almost nowhere."
```

---

### Task 5: Release workflow

**Files:**
- Create: `.github/workflows/appimage.yml`

**Interfaces:**
- Consumes: `make appimage` (Task 4), `loot_player.version.__version__` (Task 1), the `--version` flag (Task 1), the missing-VLC exit code (Task 3).
- Produces: a GitHub release with the AppImage attached, on every `v*` tag.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/appimage.yml`:

```yaml
name: appimage

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4

      - name: Tag must match loot_player/version.py
        if: startsWith(github.ref, 'refs/tags/v')
        run: |
          set -euo pipefail
          file_version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' loot_player/version.py)"
          tag_version="${GITHUB_REF_NAME#v}"
          if [ "$file_version" != "$tag_version" ]; then
            echo "tag $GITHUB_REF_NAME does not match __version__ $file_version" >&2
            exit 1
          fi
          echo "version $file_version matches tag $GITHUB_REF_NAME"

      # Same script the developer runs. A CI-only build path is a build path
      # that breaks without anyone noticing.
      - name: Build
        run: make appimage CONTAINER_ENGINE=docker

      - name: Smoke test with VLC installed
        run: |
          set -euo pipefail
          docker run --rm -v "$PWD":/src -w /src ubuntu:22.04 bash -euo pipefail -c '
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq --no-install-recommends vlc >/dev/null
            appimage="$(ls dist/loot-*-x86_64.AppImage)"
            expected="loot $(sed -n "s/^__version__ = \"\(.*\)\"$/\1/p" loot_player/version.py)"
            actual="$("$appimage" --appimage-extract-and-run --version)"
            echo "expected: $expected"
            echo "actual:   $actual"
            [ "$actual" = "$expected" ]
          '

      - name: Smoke test without VLC installed
        run: |
          set -euo pipefail
          docker run --rm -v "$PWD":/src -w /src ubuntu:22.04 bash -euo pipefail -c '
            appimage="$(ls dist/loot-*-x86_64.AppImage)"
            if "$appimage" --appimage-extract-and-run --version; then
              echo "expected a nonzero exit when VLC is absent" >&2
              exit 1
            fi
          ' 2>&1 | tee /tmp/novlc.log
          grep -q "could not find VLC" /tmp/novlc.log

      - name: Publish release
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v2
        with:
          files: dist/*.AppImage
          generate_release_notes: true
```

Two notes on why this looks the way it does.

There is no `xvfb`. `--version` returns before `QApplication` is constructed, and `vlc_check.main()` skips its dialog when there is no display, so neither smoke test needs one. Adding a virtual display would only create a way for a modal to block the runner forever. The spec called for `xvfb`; this is a deliberate simplification, and `tests/test_version.py::test_version_flag_does_not_need_a_display` is what keeps it true.

The second smoke test runs in a container with nothing installed but the base image. That is the actual assertion being made: the AppImage's only host dependency is the one documented.

- [ ] **Step 2: Validate the workflow parses**

Run:
```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/appimage.yml')); print('valid yaml')"
```
Expected: `valid yaml`

If `actionlint` is available, run it as well: `actionlint .github/workflows/appimage.yml`

- [ ] **Step 3: Verify the tag guard logic locally**

```bash
file_version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' loot_player/version.py)"
echo "reads: $file_version"
test "$file_version" = "0.1.0" && echo "guard would pass for tag v0.1.0"
```
Expected: `reads: 0.1.0` and `guard would pass for tag v0.1.0`. This is the same `sed` expression the workflow and the build script use, so a mismatch here means all three are wrong together.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/appimage.yml
git commit -m "ci: build and publish the AppImage on version tags

Runs the same containerized make target as a developer machine rather
than a second CI-only build path. Smoke tests the result twice: once with
VLC installed to prove the import graph survives packaging, once in a
bare container to prove the missing-VLC path exits cleanly instead of
tracebacking.

Refuses to publish when the tag and version.py disagree."
```

---

### Task 6: README install instructions

**Files:**
- Modify: `README.md` (`## Setup` at line 9 and `## Run` at line 23 become `## Install` and `## Run`; a build note goes next to `## Tests`)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code depends on.

- [ ] **Step 1: Replace the Setup section**

In `README.md`, replace the whole `## Setup` section (line 9 through the blank line before `## Run` at line 23) with the following. Note the outer fence is four backticks; the content itself contains three-backtick blocks that belong in the README verbatim.

````markdown
## Install

### AppImage

VLC is required either way. loot plays through the VLC libraries already
on your system rather than shipping its own copy:

```bash
sudo apt install vlc        # Debian / Ubuntu
sudo dnf install vlc        # Fedora
sudo pacman -S vlc          # Arch
```

Then grab the AppImage from
[Releases](https://github.com/mmeyer2k/loot-player/releases), make it
executable, and run it:

```bash
chmod +x loot-*-x86_64.AppImage
./loot-*-x86_64.AppImage
```

Requires glibc 2.34 or newer: Ubuntu 22.04+, Debian 12+, Fedora 35+,
RHEL 9+, current Arch. x86_64 only.

AppImages need FUSE 2, which Ubuntu 24.04 and later do not install by
default. Either install it:

```bash
sudo apt install libfuse2t64
```

or skip it per-run:

```bash
./loot-*-x86_64.AppImage --appimage-extract-and-run
```

### From source

System packages (Ubuntu / Debian):

```bash
sudo apt install -y vlc python3-pyqt6 python3-vlc python3-qtawesome python3-pytest
```

Arch / KDE:

```bash
sudo pacman -S vlc python python-pyqt6 python-vlc python-qtawesome python-pytest
```
````

The releases URL above is `mmeyer2k/loot-player`, taken from `git remote get-url origin`.

- [ ] **Step 2: Add the build note**

In `README.md`, immediately before the `## Tests` section, insert the following. Four-backtick outer fence again; the inner three-backtick block is README content.

````markdown
## Building the AppImage

```bash
make appimage        # -> dist/loot-<version>-x86_64.AppImage
```

Needs podman or docker. The build runs inside `ubuntu:22.04` rather than
on your machine: PyQt6 publishes exactly one x86_64 Linux wheel tag,
`manylinux_2_34`, so glibc 2.34 is the floor, and building against a
newer glibc produces a binary that runs almost nowhere.

libVLC is not bundled. The AppImage links against the host's VLC, which
keeps ~400 VLC plugins and their codec dependencies out of the bundle.
`packaging/AppRun` checks for it at startup and explains what to install
if it is absent.

Set `CONTAINER_ENGINE=docker` to override the default of podman.
`make appimage-clean` removes `build/` and `dist/`.
````

- [ ] **Step 3: Verify the rendered structure**

Run: `grep -n '^#\{1,3\} ' README.md`
Expected, in order: `# loot`, `## Install`, `### AppImage`, `### From source`, `## Run`, `## Features`, `## Hotkeys`, `## Where state lives`, `## Architecture (one-line tour)`, `## Building the AppImage`, `## Tests`.

- [ ] **Step 4: Verify no stale asset path survives**

Run: `grep -rn 'assets/loot.svg' README.md packaging/ loot_player/ | grep -v 'loot_player/assets'`
Expected: no output. Any hit is a path Task 2 missed.

- [ ] **Step 5: Run the full test suite one final time**

Run: `python3 -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document AppImage install and build

Leads with the AppImage since that is now the shortest path to a running
player. Names the VLC requirement up front rather than leaving it to the
error dialog, and calls out the glibc 2.34 floor and the FUSE 2 gap on
Ubuntu 24.04+ because both produce confusing failures otherwise."
```

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task:

| Spec section | Task |
|---|---|
| Decision: system VLC | 3 (preflight), 4 (`find libvlc*` guard) |
| Decision: glibc 2.34 floor | 4 (container), Global Constraints |
| Decision: hand-rolled script | 4 |
| Decision: one build path | 5 |
| Build pipeline steps 1-7 | 4 |
| Excludelist | 4 step 1 |
| AppDir layout | 4 step 4 |
| AppRun | 4 step 2 |
| `pyproject.toml` | 1 |
| `version.py` | 1 |
| Asset move | 2 |
| `__main__.py` | 1 |
| `--version` flag | 1 |
| Makefile targets | 4 step 5 |
| CI | 5 |
| README | 2 (tree), 6 (install, build) |
| Verification table | 4 steps 6-9, 5 steps 2-3, 6 step 5 |

**Deliberate deviations from the spec**, both flagged in-plan:
1. The spec put `vlc_check` behavior inside AppRun; the plan makes it a package module so the message text is unit-testable and AppRun stays a dozen lines.
2. The spec's CI used `xvfb`. The plan drops it, because `--version` returns before `QApplication` and `vlc_check` skips its dialog without a display. `tests/test_version.py::test_version_flag_does_not_need_a_display` enforces the first half; `tests/test_vlc_check.py::test_module_run_exits_nonzero_without_a_display` enforces the second.

**Type and name consistency.** `__version__` (Task 1) is read by the same `sed -n 's/^__version__ = "\(.*\)"$/\1/p'` expression in Task 4's build script and Task 5's workflow. `_LOGO_PATH` stays a `pathlib.Path` so `main()`'s existing `QIcon(str(_LOGO_PATH))` is unchanged. `python -m loot_player.vlc_check` (Task 3) is the exact command AppRun invokes (Task 4). `packaging/appimage-excludelist` is spelled identically in Task 4 steps 1 and 4.

**One ordering note.** Task 2 step 7 adds `vlc_check.py` to the README architecture tree before Task 3 creates it. Called out at that step; the gap is one commit and avoids a third README edit.
