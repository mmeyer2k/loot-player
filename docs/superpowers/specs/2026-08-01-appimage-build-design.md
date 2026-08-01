# AppImage Build — Design

**Status:** approved, pending implementation plan
**Date:** 2026-08-01

## Problem

loot is distributed as a git checkout. Running it means installing five system
packages by hand (`vlc python3-pyqt6 python3-vlc python3-qtawesome`), cloning,
and running `packaging/install-desktop.sh` to get a menu entry that points at
the repo path. Move or rename the repo and the desktop entry breaks.

There is no way to hand someone a single file they can run.

## Scope

In:

- `make appimage` produces `dist/loot-<version>-x86_64.AppImage`.
- Bundled: a relocatable CPython, PyQt6, qtawesome, python-vlc, the app itself,
  and the handful of xcb system libraries Qt's platform plugin needs.
- Not bundled: libVLC and its plugin tree. The AppImage links against the host's
  installed VLC.
- A GitHub Actions workflow that builds on `v*` tags and attaches the result to
  a release.
- The minimum app changes packaging forces: `pyproject.toml`, a version module,
  an asset-path fix, `__main__.py`, a `--version` flag.
- README install instructions covering both the AppImage and the from-source path.

Out (explicit non-goals):

- **Bundling libVLC.** See "Decision: system VLC" below.
- **aarch64.** PyQt6 ships `manylinux_2_39_aarch64`, a different glibc floor
  needing a second container. x86_64 only.
- **Flatpak, .deb, AUR.** One distribution format.
- **AppStream metainfo and zsync delta updates.** Worth adding once releases are
  routine. Not now.
- **Bundling a Python that matches the host's.** The AppImage carries its own
  3.13 regardless of what the host has.

## Decisions

### Decision: system VLC, not bundled

The AppImage requires the user to have VLC installed.

Bundling means shipping `libvlc.so.5`, `libvlccore.so.9`, and roughly 400
plugin `.so` files, each dragging its own codec, X11, and PulseAudio
dependencies, plus a `plugins.dat` cache regenerated at build time. That plugin
tree is the single largest source of AppImage breakage, and failures are silent
at runtime: a pruned demuxer means a file type just does not play.

Requiring system VLC costs the user one `apt install` and removes that entire
failure class. loot is a libVLC frontend, so the dependency is honest.

`vlc.py` honors `PYTHON_VLC_LIB_PATH` and `PYTHON_VLC_MODULE_PATH`, so a user
with VLC in a non-standard prefix can still point the AppImage at it.

### Decision: glibc floor is 2.34, and it is not ours to choose

PyQt6 6.11.0 publishes exactly one x86_64 Linux wheel:
`pyqt6-6.11.0-cp310-abi3-manylinux_2_34_x86_64.whl`. PyQt6-Qt6 6.11.1 matches.
glibc 2.34 is therefore the floor no matter how we build.

Building in `ubuntu:22.04` (glibc 2.35) sits at that floor and reaches
everything reachable. Building natively on the dev machine (Ubuntu 26.04,
glibc 2.43) would produce a binary that runs on almost nothing.

Reach: Ubuntu 22.04+, Debian 12+, RHEL 9+, Fedora 35+, current Arch,
openSUSE Leap 15.5+.

### Decision: hand-rolled script over linuxdeploy or python-appimage

`packaging/build-appimage.sh` does the assembly explicitly. It matches the
existing `packaging/install-desktop.sh` style, and every step is greppable when
something breaks. The alternatives push the critical Python-bundling step into
a third-party plugin (`linuxdeploy-plugin-python`) or a tool whose layout
opinions we would have to work around to inject the extra xcb libraries.

### Decision: one build path, not two

CI does not use a `ubuntu-22.04` runner image. It runs the same containerized
`make appimage` as the developer machine. A CI-only build path is a build path
that breaks without anyone noticing.

## Build pipeline

`make appimage` runs the container; `packaging/build-appimage.sh` runs inside it.

| Step | What happens |
|---|---|
| 1. Interpreter | Download pinned `cpython-3.13.14+20260728-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz` from `astral-sh/python-build-standalone`, extract to `AppDir/usr`. Relocatable by construction. |
| 2. Install | `AppDir/usr/bin/python3 -m pip install --no-cache-dir .` Pulls PyQt6, PyQt6-Qt6, PyQt6-sip, qtawesome, qtpy, python-vlc from wheels. |
| 3. Prune Qt | Delete `Qt6/qml`, `Qt6/lib/libQt6Quick*`, `Qt6/lib/libQt6Qml*`, `Qt6/plugins/qmltooling`, `Qt6/translations`. The app imports only QtCore, QtGui, QtWidgets. |
| 4. Deploy xcb libs | `ldd` on `PyQt6/Qt6/plugins/platforms/libqxcb.so`, copy resolved libraries to `AppDir/usr/lib`, filtered through the vendored AppImage excludelist. |
| 5. Metadata | Write `AppRun`, `loot.desktop`, `loot.svg` at AppDir root, and the same desktop file and icon under `usr/share/applications/` and `usr/share/icons/hicolor/scalable/apps/`. appimagetool wants the root copies; desktop integration tools read the `usr/share` ones. |
| 6. Package | `APPIMAGE_EXTRACT_AND_RUN=1 appimagetool-x86_64.AppImage AppDir dist/loot-<version>-x86_64.AppImage` |
| 7. Report | Print the finished size. |

Pinned versions live in variables at the top of the script. Nothing floats on
`latest`.

### Step 4 detail: the excludelist

Copying every library `ldd` reports would bundle `libc`, `libstdc++`,
`libgcc_s`, `libGL`, and `libdrm`. Bundled graphics and C++ libraries loaded
alongside the host's GPU driver is the classic way an AppImage segfaults on one
machine and works on another.

The [AppImage excludelist](https://raw.githubusercontent.com/AppImage/pkg2appimage/master/excludelist)
(53 entries) is the canonical denylist for exactly this. It gets vendored into
`packaging/appimage-excludelist` rather than fetched at build time, so builds
are reproducible and work offline.

What survives the filter is a short list dominated by `libxcb-cursor.so.0`,
the library Ubuntu does not install by default and the direct cause of the
"could not load the Qt platform plugin xcb" error.

## AppDir layout

```
AppDir/
├── AppRun
├── loot.desktop
├── loot.svg
└── usr/
    ├── bin/python3                     (python-build-standalone 3.13.14)
    ├── lib/
    │   ├── libxcb-cursor.so.0          (+ whatever else survives the excludelist)
    │   └── python3.13/site-packages/
    │       ├── PyQt6/                  (Qt6 pruned)
    │       ├── qtawesome/  qtpy/
    │       ├── vlc.py                  (ctypes binding only, no libvlc)
    │       └── loot_player/
    │           └── assets/loot.svg
    └── share/
        ├── applications/loot.desktop
        └── icons/hicolor/scalable/apps/loot.svg
```

## AppRun

```
APPDIR resolved from $0 if not already set
QT_QPA_PLATFORM defaults to xcb, overridable by the user
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH
LD_LIBRARY_PATH="$APPDIR/usr/lib:$LD_LIBRARY_PATH"
preflight: "$APPDIR/usr/bin/python3" -c "import vlc"
   exit 0  -> exec python3 -m loot_player "$@"
   nonzero -> print to stderr, show Qt dialog, exit 1
```

### Why `QT_QPA_PLATFORM=xcb`

Same reason the Makefile's `run` target sets it: libVLC's `set_xwindow` needs an
X11 window handle, which does not exist under a native Wayland Qt session. It is
a no-op on X11. Defaulted rather than forced, so a user can override it.

### Why unset the Qt path variables

A KDE session exports `QT_PLUGIN_PATH` pointing at the host's Qt 6. If the
bundled Qt picks those up it loads host plugins against bundled libraries and
crashes. PyQt6 resolves its own plugins relative to the package, so clearing
these is both safe and necessary.

### Why the VLC preflight

`vlc.py:191` raises `NotImplementedError("Cannot find libvlc lib")` at import
time when `libvlc.so.5` is absent. `loot_player.app` imports `player`, which
imports `vlc`, so a missing VLC is an unhandled traceback before any window
exists. Launched from a desktop menu that is a silent no-op with nothing to
diagnose.

Because PyQt6 is bundled, the fallback dialog can be a `QMessageBox` and is
always available. No dependency on `zenity` or `kdialog` being installed. The
dialog names the install command for apt, dnf, and pacman.

The preflight runs for every invocation, including `--version`. loot cannot do
anything useful without libVLC, so there is no invocation worth letting through.
This is what makes the missing-VLC verification a plain `--version` run that
expects exit 1.

## App changes

Packaging forces five changes. Nothing else in the package is touched:
`db.py`, `scanner.py`, `player.py`, `matching.py`, `models.py`, and everything
under `ui/` are unmodified.

### `pyproject.toml` (new)

setuptools backend. Name `loot-player`, description "Local media library and
player", `requires-python = ">=3.10"`, dependencies `PyQt6`, `python-vlc`,
`qtawesome`, console script `loot-player = loot_player.app:main`, version read
dynamically from `loot_player/version.py`, package data includes `assets/*.svg`.

This reproduces what the stale, gitignored `loot_player.egg-info/` already
describes. The metadata existed once and was lost; this recovers it.

### `loot_player/version.py` (new)

```python
__version__ = "0.1.0"
```

Single source of truth. `pyproject.toml` reads it dynamically. CI checks the
git tag against it.

### `assets/loot.svg` moves to `loot_player/assets/loot.svg`

`app.py:31` currently computes:

```python
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "loot.svg"
```

In a checkout `parent.parent` is the repo root and this works. Once installed,
`parent.parent` is `site-packages` and the icon silently does not load.

Replaced with `importlib.resources.files("loot_player") / "assets" / "loot.svg"`,
which resolves correctly in both cases. Requires the file to live inside the
package, hence the move.

Consequential edits: `packaging/loot.desktop.in` (`Icon=` line),
`packaging/install-desktop.sh` (the trailing `echo`), and the architecture tree
in `README.md`.

### `loot_player/__main__.py` (new)

Three lines, so `python -m loot_player` works. AppRun uses it instead of the
console script because it does not depend on `bin/` shebang rewriting surviving
relocation.

### `--version` flag on `main()`

Prints `loot <version>` and exits 0 before constructing `QApplication`. The
module-level PyQt6 and vlc imports still run, which is the point: it proves the
interpreter, the package, and the whole import graph are intact inside the
AppImage without needing a display or a media file.

## Makefile

Two new targets:

- `appimage` — runs the container build. Honors `CONTAINER_ENGINE`, defaulting
  to `podman` and falling back to `docker`.
- `appimage-clean` — removes `build/AppDir` and `dist/`.

## CI

`.github/workflows/appimage.yml`, triggered on `push: tags: ['v*']`. This is the
repo's first workflow.

| Job step | Detail |
|---|---|
| Guard | Fail if `${GITHUB_REF_NAME#v}` differs from `loot_player.version.__version__`. A mislabeled binary is worse than a failed build. |
| Build | `make appimage`, the same containerized script the developer runs. |
| Smoke test | In a clean `ubuntu:22.04` with only `vlc` and `xvfb` installed, run `xvfb-run ./dist/loot-*.AppImage --version`. Assert exit 0 and that the printed version matches the tag. |
| Release | Attach the AppImage to a GitHub release for the tag. |

The smoke test container installing nothing but `vlc` is the real assertion:
it proves the AppImage's only host dependency is the one we documented.

## README changes

A rewritten install section, AppImage first:

```
## Install

### AppImage (recommended)

VLC is required — loot plays through libVLC:

    sudo apt install vlc        # Debian / Ubuntu
    sudo dnf install vlc        # Fedora
    sudo pacman -S vlc          # Arch

Then download, mark executable, run:

    chmod +x loot-x86_64.AppImage
    ./loot-x86_64.AppImage

Requires glibc 2.34 or newer (Ubuntu 22.04+, Debian 12+, Fedora 35+, RHEL 9+).

AppImages need FUSE 2. Ubuntu 24.04 and later do not install it by default:

    sudo apt install libfuse2t64

Or skip FUSE entirely:

    ./loot-x86_64.AppImage --appimage-extract-and-run

### From source
    (existing apt/pacman instructions, unchanged)
```

Plus a short "Building the AppImage" note near the Tests section documenting
`make appimage` and the podman requirement.

## Verification

| Claim | How it gets checked |
|---|---|
| Builds at all | `make appimage` exits 0, `dist/` contains the file. |
| Runs without a dev environment | `--version` under `xvfb-run` in a container holding only `vlc` and `xvfb`. |
| Qt platform plugin loads | Covered by the above. A missing xcb lib fails at Qt init, before `--version` can print. |
| Missing VLC is handled | Run the smoke container without installing `vlc`. Expect exit 1 and the diagnostic on stderr, not a traceback. |
| Actually plays media | Manual, on the dev machine. Launch the AppImage, add a library, play a file. Not automatable here. |
| Icon resolves when installed | Manual. The window icon is present in the AppImage, which is the case `parent.parent` broke. |
| Existing tests still pass | `make test`. The asset move and the `--version` flag are the only things that could disturb them. |

## Known limits

- **x86_64 only.**
- **glibc 2.34 floor.** Set by the PyQt6 wheel tags, not by us.
- **VLC must be installed.** By design.
- **FUSE 2 needed to run**, absent by default on Ubuntu 24.04+. Documented, with
  the `--appimage-extract-and-run` escape hatch.
- **Size is unmeasured.** No estimate is quoted anywhere in this spec on purpose.
  The build script prints the real number.
- **`data_dir()` is unaffected.** The AppImage reads and writes the same
  `~/.local/share/loot-player/library.db` as a source checkout, including the
  `vlc-library` → `vlc-ranger` → `loot-player` rename chain. Switching between
  the two keeps one library.

## Files touched

| File | Change |
|---|---|
| `pyproject.toml` | new |
| `packaging/build-appimage.sh` | new |
| `packaging/AppRun` | new |
| `packaging/loot-appimage.desktop` | new |
| `packaging/appimage-excludelist` | new, vendored |
| `.github/workflows/appimage.yml` | new |
| `loot_player/version.py` | new |
| `loot_player/__main__.py` | new |
| `loot_player/assets/loot.svg` | moved from `assets/loot.svg` |
| `loot_player/app.py` | `_LOGO_PATH` via `importlib.resources`; `--version` flag |
| `packaging/loot.desktop.in` | `Icon=` path |
| `packaging/install-desktop.sh` | icon path in trailing `echo` |
| `Makefile` | `appimage`, `appimage-clean` targets |
| `.gitignore` | `dist/`, `build/` |
| `README.md` | install section, build note, architecture tree |
