# Self-contained AppImage Releases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship loot-player as a single `loot-player-<version>-x86_64.AppImage` — bundling Python, PyQt6, qtawesome, and libVLC + its plugins — built and published to GitHub Releases automatically when a `v*` tag is pushed.

**Architecture:** A relocatable CPython plus pip-installed deps and a hand-bundled libVLC live in an AppDir. An `AppRun` launcher points python-vlc at the bundled libVLC via `PYTHON_VLC_LIB_PATH` / `PYTHON_VLC_MODULE_PATH`, forces `xcb` under KDE, and runs `python -m loot_player`. A build script assembles the AppDir; a GitHub Actions workflow runs it on tag push and uploads the artifact after a `--selfcheck` smoke test.

**Tech Stack:** Python 3, PyQt6, python-vlc, qtawesome, setuptools/pyproject, python-build-standalone, appimagetool, GitHub Actions, bash.

**Design spec:** `docs/superpowers/specs/2026-05-23-appimage-release-design.md`

---

## A note on testing in this plan

The Python changes (Tasks 1–5) are developed test-first with pytest, run via
`python3 -m pytest`. The packaging artifacts (Tasks 6–9: `AppRun`, the build
script, the CI workflow) cannot be unit-tested with pytest — their honest test
is *building the AppImage and running its `--selfcheck`*. Those tasks specify
the exact command to run and the exact output to expect. Do not fabricate a
pytest test for a shell script; run the script and observe.

The dev machine has system VLC and PyQt6 installed (per `CLAUDE.md`), so the
pytest tests and a local build both work without extra setup.

---

## File Structure

**New files:**
- `pyproject.toml` — package metadata, runtime deps, console-script entry, dynamic version.
- `loot_player/version.py` — single source of truth for `__version__`.
- `loot_player/__main__.py` — enables `python -m loot_player`.
- `tests/test_cli.py` — tests for `--version`, `selfcheck()`, icon resolution.
- `packaging/AppRun` — AppImage launcher (env setup + exec).
- `packaging/build-appimage.sh` — assembles the AppDir and runs appimagetool.
- `.github/workflows/release.yml` — tag-triggered build + GitHub Release.

**Modified files:**
- `loot_player/app.py` — `main(argv)` with `--version`/`--selfcheck`, `selfcheck()`, `_icon_path()`.
- `loot_player/player.py` — guard a failed `vlc.Instance()` with a clear error.
- `main.py` — `sys.exit(main())`.
- `Makefile` — `appimage` target that runs the build script locally.
- `README.md` — install-from-AppImage and cut-a-release instructions.

---

## Task 1: Package metadata + version module

Establishes the version single-source and makes `pip install .` work, which the
build script depends on.

**Files:**
- Create: `loot_player/version.py`
- Create: `pyproject.toml`

- [ ] **Step 1: Create the version module**

`loot_player/version.py`:

```python
"""Single source of truth for the app version.

CI overwrites the literal below with the git tag value at release build time
(see .github/workflows/release.yml). Keep it a plain string assignment so
setuptools can read it statically (see pyproject.toml dynamic version).
"""

__version__ = "0.0.0+dev"
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "loot-player"
description = "Local media library and player"
readme = "README.md"
requires-python = ">=3.10"
license = { file = "LICENSE" }
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
```

- [ ] **Step 3: Verify the version is statically readable**

Run: `python3 -c "import loot_player.version as v; print(v.__version__)"`
Expected: `0.0.0+dev`

- [ ] **Step 4: Verify the package builds an sdist/wheel cleanly**

Run: `python3 -m pip install --quiet build && python3 -m build --wheel 2>&1 | tail -3`
Expected: ends with `Successfully built loot_player-0.0.0+dev-py3-none-any.whl` (version may render as `0.0.0.dev0` — that's fine). Then clean up: `rm -rf dist build *.egg-info`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml loot_player/version.py
git commit -m "build: add pyproject metadata and version module"
```

---

## Task 2: `main(argv)` refactor, `--version`, and `python -m loot_player`

**Files:**
- Modify: `loot_player/app.py:760-769` (the `main()` function) and imports near `loot_player/app.py:28`
- Create: `loot_player/__main__.py`
- Modify: `main.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
from loot_player.app import main
from loot_player.version import __version__


def test_version_flag_prints_version_and_returns_zero(capsys):
    rc = main(["loot-player", "--version"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == __version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `main()` currently takes no args / builds a QApplication (TypeError or attempts to open a display).

- [ ] **Step 3: Add the version import**

In `loot_player/app.py`, just below the existing `from loot_player...` imports (around line 26), add:

```python
from loot_player.version import __version__
```

- [ ] **Step 4: Rewrite `main()` to accept argv and handle `--version`**

Replace the existing `main()` (`loot_player/app.py:760-769`) with:

```python
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]

    if "--version" in args:
        print(__version__)
        return 0

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    icon = QIcon(str(_LOGO_PATH))
    app.setWindowIcon(icon)
    w = MainWindow()
    w.setWindowIcon(icon)
    w.show()
    w.video.attach()
    return app.exec()
```

(`--selfcheck` and `_icon_path()` are added in later tasks; keep this minimal for now.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Create `loot_player/__main__.py`**

```python
import sys

from loot_player.app import main

sys.exit(main())
```

- [ ] **Step 7: Update `main.py` to propagate the exit code**

Replace the body of `main.py` with:

```python
"""loot-player entrypoint. See loot_player.app.main for the real code."""

import sys

from loot_player.app import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Verify `python -m loot_player --version` works**

Run: `python3 -m loot_player --version`
Expected: prints `0.0.0+dev`

- [ ] **Step 9: Commit**

```bash
git add loot_player/app.py loot_player/__main__.py main.py tests/test_cli.py
git commit -m "feat: add --version flag and python -m loot_player entrypoint"
```

---

## Task 3: `--selfcheck` smoke test

A hidden flag that exercises the exact things AppImage bundling can break:
PyQt6 imports, libVLC loads, and VLC plugins are discoverable.

**Files:**
- Modify: `loot_player/app.py` (add `selfcheck()`, wire into `main()`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
from loot_player.app import selfcheck


def test_selfcheck_passes_with_system_vlc():
    # Dev box and CI both have system VLC + PyQt6 installed.
    assert selfcheck() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py::test_selfcheck_passes_with_system_vlc -v`
Expected: FAIL — `ImportError: cannot import name 'selfcheck'`

- [ ] **Step 3: Implement `selfcheck()`**

Add to `loot_player/app.py` (just above `main()`):

```python
def selfcheck() -> int:
    """Smoke-test the runtime so a broken bundle never ships.

    Verifies Qt is importable, libVLC loads, and VLC plugins are discoverable
    (an empty/blank plugin path yields no audio-output modules). Returns 0 on
    success, 1 otherwise. Run in CI as `--selfcheck` under xvfb.
    """
    try:
        import PyQt6.QtWidgets  # noqa: F401  (import-only Qt check)
        import vlc
    except Exception as exc:  # pragma: no cover - import failure path
        print(f"selfcheck: import failed: {exc}", file=sys.stderr)
        return 1

    inst = vlc.Instance(["--quiet"])
    if inst is None:
        print("selfcheck: vlc.Instance() returned None (libVLC/plugins not loadable)",
              file=sys.stderr)
        return 1

    if inst.audio_output_list_get() is None:
        print("selfcheck: no VLC audio output modules found (PYTHON_VLC_MODULE_PATH wrong?)",
              file=sys.stderr)
        return 1

    print(f"selfcheck OK: loot-player {__version__}, "
          f"libvlc {vlc.libvlc_get_version().decode(errors='replace')}")
    return 0
```

- [ ] **Step 4: Wire `--selfcheck` into `main()`**

In `main()`, immediately after the `--version` block, add:

```python
    if "--selfcheck" in args:
        return selfcheck()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS (both CLI tests)

- [ ] **Step 6: Verify the flag end to end**

Run: `python3 -m loot_player --selfcheck; echo "rc=$?"`
Expected: prints `selfcheck OK: loot-player 0.0.0+dev, libvlc <version>` and `rc=0`

- [ ] **Step 7: Commit**

```bash
git add loot_player/app.py tests/test_cli.py
git commit -m "feat: add --selfcheck runtime smoke test"
```

---

## Task 4: Bundle-aware window-icon resolution

In an installed/bundled layout `loot_player` lives in site-packages, so the
existing `_LOGO_PATH` (`__file__/../../assets/loot.svg`) won't resolve. `AppRun`
will export `LOOT_PLAYER_ICON` pointing at the bundled PNG; honor it with a
fallback to the repo path so dev runs are unaffected.

**Files:**
- Modify: `loot_player/app.py` (add `_icon_path()`, use it in `main()`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
from pathlib import Path

from loot_player.app import _icon_path, _LOGO_PATH


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -k icon_path -v`
Expected: FAIL — `ImportError: cannot import name '_icon_path'`

- [ ] **Step 3: Implement `_icon_path()`**

Add to `loot_player/app.py` (just above `main()`):

```python
def _icon_path() -> str:
    """Window-icon path. Honors LOOT_PLAYER_ICON (set by the AppImage AppRun),
    falling back to the in-repo SVG for source runs."""
    env = os.environ.get("LOOT_PLAYER_ICON")
    if env and Path(env).is_file():
        return env
    return str(_LOGO_PATH)
```

- [ ] **Step 4: Use it in `main()`**

In `main()`, change `icon = QIcon(str(_LOGO_PATH))` to:

```python
    icon = QIcon(_icon_path())
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS (all CLI tests)

- [ ] **Step 6: Commit**

```bash
git add loot_player/app.py tests/test_cli.py
git commit -m "feat: resolve window icon from LOOT_PLAYER_ICON for bundled runs"
```

---

## Task 5: Graceful libVLC init failure

If libVLC can't load, `vlc.Instance(...)` returns `None` and the next line
(`media_player_new()`) raises a cryptic `AttributeError`. Turn that into a clear
message.

**Files:**
- Modify: `loot_player/player.py:24` (guard the Instance) 
- Modify: `loot_player/app.py` (catch in `main()`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
import pytest


def test_vlcwidget_raises_clear_error_when_libvlc_unavailable(monkeypatch):
    import loot_player.player as player

    monkeypatch.setattr(player.vlc, "Instance", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="libVLC"):
        player.VlcWidget()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py::test_vlcwidget_raises_clear_error_when_libvlc_unavailable -v`
Expected: FAIL — currently raises `AttributeError: 'NoneType' object has no attribute 'media_player_new'`, not `RuntimeError`.

> Note: constructing a bare `VlcWidget()` (a `QFrame`) requires a `QApplication`. If the test errors with "QWidget: Must construct a QApplication before a QWidget", add this fixture at the top of `tests/test_cli.py`:
> ```python
> import pytest
> from PyQt6.QtWidgets import QApplication
>
> @pytest.fixture(scope="session", autouse=True)
> def _qapp():
>     app = QApplication.instance() or QApplication([])
>     yield app
> ```
> The CI selfcheck job runs under `xvfb`, and local runs have a display.

- [ ] **Step 3: Add the guard in `player.py`**

In `loot_player/player.py`, replace line 24:

```python
        self.instance = vlc.Instance(["--no-video-title-show", "--quiet"])
```

with:

```python
        self.instance = vlc.Instance(["--no-video-title-show", "--quiet"])
        if self.instance is None:
            raise RuntimeError(
                "Could not initialize libVLC. VLC's libraries or plugins are "
                "missing or unloadable. If running from source, install VLC "
                "(e.g. `sudo apt install vlc`)."
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py::test_vlcwidget_raises_clear_error_when_libvlc_unavailable -v`
Expected: PASS

- [ ] **Step 5: Catch it in `main()` so the user sees a clean message**

In `loot_player/app.py` `main()`, replace the line `w = MainWindow()` with:

```python
    try:
        w = MainWindow()
    except RuntimeError as exc:
        print(f"loot-player: {exc}", file=sys.stderr)
        QMessageBox.critical(None, APP_BRAND, str(exc))
        return 1
```

(`QMessageBox` and `APP_BRAND` are already imported/defined in `app.py`.)

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (all tests, including pre-existing matching/db tests)

- [ ] **Step 7: Commit**

```bash
git add loot_player/player.py loot_player/app.py tests/test_cli.py
git commit -m "fix: surface a clear error when libVLC fails to initialize"
```

---

## Task 6: The `AppRun` launcher

**Files:**
- Create: `packaging/AppRun`

- [ ] **Step 1: Write `packaging/AppRun`**

```bash
#!/usr/bin/env bash
# AppImage entrypoint. Points python-vlc at the bundled libVLC, ensures the
# bundled libs and the xcb platform plugin load, then runs the app.
set -euo pipefail

HERE="$(dirname "$(readlink -f "${0}")")"

export PYTHON_VLC_LIB_PATH="${HERE}/usr/lib/libvlc.so"
export PYTHON_VLC_MODULE_PATH="${HERE}/usr/lib/vlc/plugins"
export LD_LIBRARY_PATH="${HERE}/usr/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export LOOT_PLAYER_ICON="${HERE}/loot-player.png"

# libVLC's set_xwindow needs the xcb platform plugin; force it under KDE
# (mirrors the dev Makefile) unless the user already chose a platform.
if [ -z "${QT_QPA_PLATFORM:-}" ]; then
    case "${XDG_CURRENT_DESKTOP:-}" in
        *KDE*) export QT_QPA_PLATFORM=xcb ;;
    esac
fi

exec "${HERE}/usr/python/bin/python3" -m loot_player "$@"
```

- [ ] **Step 2: Make it executable and shell-check it**

Run: `chmod +x packaging/AppRun && bash -n packaging/AppRun && echo OK`
Expected: `OK` (no syntax errors). If `shellcheck` is installed, also run `shellcheck packaging/AppRun` and address warnings.

- [ ] **Step 3: Commit**

```bash
git add packaging/AppRun
git commit -m "build: add AppImage AppRun launcher"
```

---

## Task 7: The build script `packaging/build-appimage.sh`

Assembles the AppDir and produces the AppImage. Sourced libVLC + plugins come
from the host's apt-installed VLC; transitive `.so` deps are resolved with
`ldd`. Designed to run on `ubuntu-22.04` (CI) or the dev box.

**Files:**
- Create: `packaging/build-appimage.sh`

- [ ] **Step 1: Write the script**

`packaging/build-appimage.sh`:

```bash
#!/usr/bin/env bash
# Build a self-contained loot-player AppImage.
#
# Usage: packaging/build-appimage.sh [VERSION]
#   VERSION defaults to loot_player.version.__version__.
#
# Requires (apt): vlc, librsvg2-bin, file, patchelf, wget, ca-certificates.
# Downloads python-build-standalone and appimagetool on first run.
set -euo pipefail

REPO="$(cd "$(dirname "${0}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import loot_player.version as v; print(v.__version__)')}"
ARCH="x86_64"

# Pinned tool versions (bump deliberately).
PY_VERSION="3.11.9"
PBS_TAG="20240415"   # astral-sh/python-build-standalone release date tag
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PY_VERSION}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"

BUILD="${REPO}/build/appimage"
APPDIR="${BUILD}/AppDir"
rm -rf "${BUILD}"
mkdir -p "${APPDIR}/usr/lib/vlc" "${BUILD}/tools"

echo ">> Fetching relocatable CPython ${PY_VERSION}"
wget -qO "${BUILD}/python.tar.gz" "${PBS_URL}"
tar -xzf "${BUILD}/python.tar.gz" -C "${BUILD}"
mv "${BUILD}/python" "${APPDIR}/usr/python"
PYBIN="${APPDIR}/usr/python/bin/python3"

echo ">> Installing loot-player and deps into the bundle"
"${PYBIN}" -m pip install --upgrade pip
"${PYBIN}" -m pip install "${REPO}"

echo ">> Locating system libVLC"
LIBVLC="$(ldconfig -p | awk '/libvlc\.so/{print $NF; exit}')"
LIBVLCCORE="$(ldconfig -p | awk '/libvlccore\.so/{print $NF; exit}')"
VLC_PLUGINS="$(dirname "${LIBVLC}")/vlc/plugins"
[ -d "${VLC_PLUGINS}" ] || VLC_PLUGINS="/usr/lib/x86_64-linux-gnu/vlc/plugins"
[ -d "${VLC_PLUGINS}" ] || { echo "VLC plugins dir not found"; exit 1; }

echo ">> Copying libVLC + plugin tree"
cp -L "${LIBVLC}"* "${APPDIR}/usr/lib/" 2>/dev/null || cp -L "${LIBVLC}" "${APPDIR}/usr/lib/libvlc.so"
cp -L "${LIBVLCCORE}" "${APPDIR}/usr/lib/" || true
ln -sf "$(basename "${LIBVLC}")" "${APPDIR}/usr/lib/libvlc.so" 2>/dev/null || true
cp -a "${VLC_PLUGINS}" "${APPDIR}/usr/lib/vlc/plugins"

echo ">> Resolving transitive .so dependencies via ldd"
# Libraries that must come from the host (glibc family, GL, X server side).
EXCLUDE='^(libc|libm|libdl|libpthread|librt|libresolv|ld-linux.*|libutil|libgcc_s|libGL|libGLX|libEGL|libdrm|libGLdispatch|libX11|libxcb)\.so'
collect_deps() {
  for f in "$@"; do
    ldd "${f}" 2>/dev/null | awk '/=> \//{print $3}'
  done
}
mapfile -t SCAN < <(find "${APPDIR}/usr/lib" -name '*.so*' -type f)
collect_deps "${SCAN[@]}" | sort -u | while read -r dep; do
  base="$(basename "${dep}")"
  if echo "${base}" | grep -Eq "${EXCLUDE}"; then continue; fi
  [ -e "${APPDIR}/usr/lib/${base}" ] || cp -L "${dep}" "${APPDIR}/usr/lib/"
done

echo ">> Bundling Qt's xcb platform-plugin prerequisites"
for lib in libxcb-cursor.so.0 libxkbcommon.so.0 libxkbcommon-x11.so.0; do
  p="$(ldconfig -p | awk -v l="${lib}" '$1==l{print $NF; exit}')"
  [ -n "${p}" ] && cp -L "${p}" "${APPDIR}/usr/lib/" || true
done

echo ">> Regenerating the VLC plugin cache"
CACHEGEN="$(find /usr/lib -name vlc-cache-gen -type f 2>/dev/null | head -n1)"
[ -n "${CACHEGEN}" ] && "${CACHEGEN}" "${APPDIR}/usr/lib/vlc/plugins" || \
  echo "WARN: vlc-cache-gen not found; plugins will be scanned at startup"

echo ">> Desktop integration (icon + .desktop + AppRun)"
rsvg-convert -w 256 -h 256 "${REPO}/assets/loot.svg" -o "${APPDIR}/loot-player.png"
sed -e "s|^Exec=.*|Exec=AppRun|" \
    -e "s|^Icon=.*|Icon=loot-player|" \
    "${REPO}/packaging/loot.desktop.in" \
  | sed -e "s|@REPO@||g" \
  > "${APPDIR}/loot-player.desktop"
cp "${REPO}/packaging/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

echo ">> Packaging with appimagetool"
wget -qO "${BUILD}/tools/appimagetool" "${APPIMAGETOOL_URL}"
chmod +x "${BUILD}/tools/appimagetool"
OUT="${REPO}/loot-player-${VERSION}-${ARCH}.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="${ARCH}" \
  "${BUILD}/tools/appimagetool" "${APPDIR}" "${OUT}"

echo ">> Built: ${OUT}"
```

- [ ] **Step 2: Make it executable and syntax-check it**

Run: `chmod +x packaging/build-appimage.sh && bash -n packaging/build-appimage.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add packaging/build-appimage.sh
git commit -m "build: add AppImage build script"
```

---

## Task 8: Local build verification (the real integration test)

This is the moment of truth: build the AppImage on the dev box and prove it
runs self-contained. No pytest here — run the artifact.

**Files:** none (verification only)

- [ ] **Step 1: Ensure host build deps are present**

Run: `sudo apt-get install -y vlc librsvg2-bin patchelf wget file`
Expected: installed (most already present on the dev box).

- [ ] **Step 2: Build the AppImage**

Run: `packaging/build-appimage.sh 0.0.0-local`
Expected: ends with `>> Built: <repo>/loot-player-0.0.0-local-x86_64.AppImage`. Investigate any non-zero exit before continuing — do not skip failures.

- [ ] **Step 3: Run the bundled self-check (proves VLC plugins are found)**

Run: `chmod +x loot-player-0.0.0-local-x86_64.AppImage && ./loot-player-0.0.0-local-x86_64.AppImage --selfcheck; echo "rc=$?"`
Expected: `selfcheck OK: loot-player 0.0.0-local, libvlc <version>` and `rc=0`.

If `rc=1` with "no VLC audio output modules", the plugin path/cache is wrong —
revisit Task 7's plugin copy / `vlc-cache-gen` step. This is exactly the failure
the self-check exists to catch.

- [ ] **Step 4: Confirm it does not leak the host's Python/VLC**

Run: `./loot-player-0.0.0-local-x86_64.AppImage --version`
Expected: `0.0.0-local`

- [ ] **Step 5: (Optional, with a display) launch the GUI**

Run: `./loot-player-0.0.0-local-x86_64.AppImage`
Expected: the window opens and video playback works. Close it when satisfied.

- [ ] **Step 6: Clean up the local artifact and build dir**

Run: `rm -rf build loot-player-0.0.0-local-x86_64.AppImage`
Expected: removed. (`build/` and `*.AppImage` are git-ignored in the next task.)

> No commit in this task — it produces no tracked files. If Task 7 needed fixes
> to get here, amend/commit those under Task 7's message.

---

## Task 9: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `.gitignore` (ignore build output)

- [ ] **Step 1: Ignore build artifacts**

Append to `.gitignore`:

```
build/
*.AppImage
```

- [ ] **Step 2: Write the workflow**

`.github/workflows/release.yml`:

```yaml
name: Release AppImage

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  appimage:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4

      - name: Install build dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y vlc librsvg2-bin patchelf wget file \
            libxcb-cursor0 libxkbcommon-x11-0 xvfb

      - name: Stamp version from tag
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          echo "VERSION=${VERSION}" >> "$GITHUB_ENV"
          printf '__version__ = "%s"\n' "${VERSION}" > loot_player/version.py

      - name: Build AppImage
        run: packaging/build-appimage.sh "${VERSION}"

      - name: Smoke-test the AppImage
        run: |
          chmod +x "loot-player-${VERSION}-x86_64.AppImage"
          xvfb-run -a "./loot-player-${VERSION}-x86_64.AppImage" --selfcheck

      - name: Publish GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: loot-player-${{ env.VERSION }}-x86_64.AppImage
          generate_release_notes: true
```

- [ ] **Step 3: Lint the workflow**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('yaml OK')"`
Expected: `yaml OK`. If `actionlint` is available, run it too and address findings.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml .gitignore
git commit -m "ci: build and publish AppImage on version tag"
```

---

## Task 10: Makefile target + README

**Files:**
- Modify: `Makefile`
- Modify: `README.md`

- [ ] **Step 1: Add a local build target to the Makefile**

In `Makefile`, add `appimage` to the `.PHONY` line and append this target:

```make
appimage:
	./packaging/build-appimage.sh
```

- [ ] **Step 2: Verify the target is wired (dry run)**

Run: `make -n appimage`
Expected: prints `./packaging/build-appimage.sh`

- [ ] **Step 3: Document installing and releasing in `README.md`**

Add a section to `README.md` (place it near the existing install/run docs):

```markdown
## Install (AppImage)

Download the latest `loot-player-<version>-x86_64.AppImage` from the
[Releases](https://github.com/mmeyer2k/loot-player/releases) page, then:

```bash
chmod +x loot-player-*-x86_64.AppImage
./loot-player-*-x86_64.AppImage
```

It bundles libVLC, so no system VLC install is required. Works on
glibc 2.35+ distros (Ubuntu 22.04+, Debian 12+, Fedora 36+, recent Arch).

## Cutting a release

Releases are built by CI (`.github/workflows/release.yml`) on tag push:

```bash
git tag v0.1.0
git push origin v0.1.0
```

CI builds the AppImage, runs `--selfcheck`, and attaches it to a new GitHub
Release. To build one locally for debugging: `make appimage`.
```

- [ ] **Step 4: Commit**

```bash
git add Makefile README.md
git commit -m "docs: document AppImage install and release process"
```

---

## Final verification

- [ ] **Step 1: Full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 2: Confirm clean tree and review the branch diff**

Run: `git status --short && git log --oneline master..HEAD`
Expected: clean working tree (aside from the pre-existing `Makefile`/`library_tree.py` edits that predate this branch), and a tidy series of commits for Tasks 1–10.

- [ ] **Step 3: Hand off**

The branch `feat/appimage-release` is ready. Open a PR, or push a real `v*` tag
to exercise the workflow end to end and confirm the Release artifact appears.

---

## Notes for the implementer

- **Tool version pins** (`PY_VERSION`, `PBS_TAG` in the build script) are
  examples chosen at plan time — if a download 404s, check the
  `astral-sh/python-build-standalone` releases page for a current tag and adjust.
- **glibc floor:** building on `ubuntu-22.04` targets glibc 2.35. Do not "fix"
  this by building on a newer runner — that would *raise* the floor and shrink
  reach. Older reach is explicitly out of scope (see spec).
- **The `EXCLUDE` denylist** in Task 7 is the conventional AppImage set (glibc
  family, GL, core X libs). If the self-check fails with a missing-symbol error
  at load, a needed lib was over-excluded; if the AppImage crashes only on other
  machines, a host-specific lib was under-excluded. Adjust the regex accordingly.
```
