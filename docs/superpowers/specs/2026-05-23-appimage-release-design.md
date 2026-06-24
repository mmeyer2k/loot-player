# Self-contained AppImage releases for loot-player

**Date:** 2026-05-23
**Status:** Approved (design)
**Branch:** `feat/appimage-release`

## Goal

Let us cut public releases of loot-player that any Linux user can run without
installing anything — including VLC. A release is a single
`loot-player-<version>-x86_64.AppImage` attached to a GitHub Release, produced
automatically by CI when we push a version tag.

## Context & constraints

- The app is a Python package (`loot_player/`) with entrypoint `main.py`.
  Third-party runtime deps: **PyQt6**, **python-vlc**, **qtawesome**.
- **python-vlc is only ctypes bindings.** At runtime it `dlopen`s `libvlc.so`
  and needs VLC's plugin tree (~200 `.so` files). Bundling these correctly is
  the central engineering challenge.
- python-vlc's `find_lib()` honors two environment variables:
  - `PYTHON_VLC_LIB_PATH` — absolute path to the `libvlc.so` to load.
  - `PYTHON_VLC_MODULE_PATH` — path to the VLC `plugins/` directory.
  Setting both removes all library-path guessing. This is the linchpin that
  makes bundling VLC tractable.
- PyQt6's pip wheel ships Qt itself (libraries + the `xcb` platform plugin), so
  we do not need a separate Qt-bundling tool. We only bundle Qt's few system
  prerequisites (`libxcb-cursor`, `libxkbcommon`).
- libVLC's `set_xwindow` needs the `xcb` platform plugin; under KDE Wayland we
  must force `QT_QPA_PLATFORM=xcb` (already handled in the Makefile for dev).
- Existing assets to reuse: `assets/loot.svg`, `packaging/loot.desktop.in`.
- Release flow chosen: **GitHub Actions on a tag** (no local-build requirement,
  but build logic lives in a script so it can be run/debugged locally).

## Decision: self-contained AppImage

Chosen over Flatpak (heaviest build — libVLC from source; doesn't fit
tag-driven releases) and over "AppImage relying on system VLC" (breaks the
"runs anywhere" promise). An AppImage is one file, `chmod +x`, run — matching
"broad reach" and "push a tag → downloadable file" exactly. Flatpak/Flathub
remains a viable *future* addition without invalidating this work.

## Architecture

### AppDir layout

```
AppDir/
├── AppRun                      # launcher: env setup + exec
├── loot-player.desktop         # generated from packaging/loot.desktop.in
├── loot-player.png             # 256x256, rasterized from assets/loot.svg
└── usr/
    ├── python/                 # relocatable CPython (python-build-standalone)
    │   └── lib/python3.x/site-packages/   # PyQt6, python-vlc, qtawesome, loot_player
    ├── lib/                    # libvlc.so, libvlccore.so + transitive .so deps
    │                           #   + Qt's xcb prerequisites (libxcb-cursor, libxkbcommon)
    └── lib/vlc/plugins/        # VLC plugins + regenerated plugins.dat cache
```

### AppRun responsibilities

`AppRun` is a thin shell launcher. In order:

1. Resolve `HERE="$(dirname "$(readlink -f "$0")")"`.
2. Export `PYTHON_VLC_LIB_PATH="$HERE/usr/lib/libvlc.so"`.
3. Export `PYTHON_VLC_MODULE_PATH="$HERE/usr/lib/vlc/plugins"`.
4. Prepend `$HERE/usr/lib` to `LD_LIBRARY_PATH`.
5. Replicate the Makefile's platform logic: if `$XDG_CURRENT_DESKTOP` matches
   `*KDE*`, export `QT_QPA_PLATFORM=xcb` (unless the user already set it).
6. `exec "$HERE/usr/python/bin/python3" -m loot_player "$@"` so CLI flags
   (`--version`, `--selfcheck`) pass through. A one-line
   `loot_player/__main__.py` calls `loot_player.app.main()`.

## Build pipeline — `packaging/build-appimage.sh`

A standalone script (CI invokes it; runnable locally for debugging). Steps:

1. **Python:** download a relocatable CPython (python-build-standalone) into
   `AppDir/usr/python`.
2. **Deps + package:** `pip install .` into that interpreter. A new minimal
   `pyproject.toml` declares the package and its three runtime deps (PyQt6,
   python-vlc, qtawesome), so this one command installs both `loot_player` and
   its dependencies into site-packages.
3. **VLC:** `apt-get install -y vlc` on the build host, then:
   - copy `libvlc.so*`, `libvlccore.so*` into `AppDir/usr/lib`;
   - copy the system VLC `plugins/` tree into `AppDir/usr/lib/vlc/plugins`;
   - walk `ldd` over libvlc + libvlccore + every plugin, dedup, and copy each
     transitive `.so` dependency into `AppDir/usr/lib` (excluding the glibc/core
     libs that must come from the host);
   - run `vlc-cache-gen` against the bundled plugins dir to produce the cache.
4. **Qt prerequisites:** copy `libxcb-cursor`, `libxkbcommon` (+ any missing xcb
   libs the bundled `libqxcb.so` needs per `ldd`) into `AppDir/usr/lib`.
5. **Desktop integration:** rasterize `assets/loot.svg` → `loot-player.png`
   (256x256); render `packaging/loot.desktop.in` → `loot-player.desktop` with an
   AppImage-appropriate `Exec`/`Icon`; write `AppRun`.
6. **Package:** run `appimagetool` with `APPIMAGE_EXTRACT_AND_RUN=1` (CI has no
   FUSE) to emit `loot-player-<version>-x86_64.AppImage`.

The script takes the version string as input (arg or env) for the filename.

## CI / release flow — `.github/workflows/release.yml`

- **Trigger:** `push` on tags matching `v*`.
- **Runner:** `ubuntu-22.04` (glibc floor — see Reach below).
- **Permissions:** `contents: write` (to create the Release / upload the asset).
- **Steps:**
  1. `actions/checkout`.
  2. Install build deps (`vlc`, `librsvg2-bin` for rasterizing, `appimagetool`,
     xcb prerequisite packages).
  3. Derive version from the tag (`v0.2.0` → `0.2.0`); write it into
     `loot_player/version.py`.
  4. Run `packaging/build-appimage.sh <version>`.
  5. Smoke test: `xvfb-run ./loot-player-*.AppImage --selfcheck` (see below).
  6. `softprops/action-gh-release` to create the GitHub Release and upload the
     `.AppImage`.

**Releasing later:** `git tag v0.2.0 && git push origin v0.2.0`. Nothing else.

## Versioning

- New `loot_player/version.py` with `__version__ = "0.0.0+dev"` checked in;
  CI overwrites it with the tag value before building. `pyproject.toml` sources
  its version from this file (dynamic version) so the two never drift.
- `loot_player.app.main` gains a `--version` flag that prints it.

## Error handling & smoke test

- **`--selfcheck` hidden entrypoint:** imports PyQt6, imports `vlc`,
  instantiates `vlc.Instance()`, and asserts a non-zero plugin/module count,
  then exits 0. This exercises exactly what breaks when VLC bundling is wrong
  (plugins not found). CI runs it under `xvfb-run` and fails the release on a
  non-zero exit, so a broken bundle never ships.
- **libVLC init guard:** `main()` wraps libVLC instantiation so a load failure
  prints a clear, actionable message rather than a raw ctypes traceback.

## Reach tradeoff

An AppImage's minimum glibc equals the newest glibc any bundled binary was
built against. We copy VLC's libraries from the build host's apt, so building
on `ubuntu-22.04` sets the floor at **glibc 2.35** — covers Ubuntu 22.04+,
Debian 12+, Fedora 36+, recent Arch (all currently-supported mainstream
distros), but not ancient ones. Widening reach (e.g. a manylinux2014 container,
glibc 2.17) is real added complexity and deferred until someone asks.
**x86_64 only**; arm64 is a later addition.

## Repo changes

New files:
- `.github/workflows/release.yml`
- `packaging/build-appimage.sh`
- `pyproject.toml` — package metadata + runtime deps; version sourced from `version.py`.
- `loot_player/version.py`
- `loot_player/__main__.py` — one-liner so `python -m loot_player` works.

Touched files:
- `loot_player/app.py` — `--version` / `--selfcheck` flags, libVLC init guard.
- `README.md` — AppImage install instructions and how to cut a release.

## Out of scope (YAGNI)

- Flatpak / Flathub packaging (documented as a future option).
- `.deb` / PyPI distribution.
- arm64 builds.
- AppImage auto-update (zsync) integration.
- Older-glibc (manylinux) build base.
