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
| 3. Prune Qt | Delete `Qt6/qml`, `Qt6/lib/libQt6Quick*`, `Qt6/lib/libQt6Qml*`, `Qt6/plugins/qmltooling`, `Qt6/translations`, `Qt6/plugins/platformthemes`, `Qt6/plugins/imageformats/libqtiff.so`. The app imports only QtCore, QtGui, QtWidgets. |
| 4. Deploy xcb libs | `ldd` on `PyQt6/Qt6/plugins/platforms/libqxcb.so`, copy resolved libraries to `AppDir/usr/lib`, filtered through the vendored AppImage excludelist plus our own denylist. Anything `ldd` resolves to a path already inside the AppDir is skipped. |
| 4b. Guard | Fail the build if any `libvlc*`, `libvlccore*`, `*/vlc/plugins/*` or glib-family library ended up in the AppDir. |
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
are reproducible and work offline. That file stays a verbatim upstream copy;
local additions go in `packaging/appimage-extra-excludes` and both are
concatenated into one normalized list. Normalizing matters: upstream puts
trailing `#` comments on three entries, including `libxcb-dri3.so.0` and
`libxcb-dri2.so.0`, so a literal whole-line match would silently miss the
two entries that exist to stop us breaking the target's GPU driver.

What survives the filter is a short list dominated by `libxcb-cursor.so.0`,
the library Ubuntu does not install by default and the direct cause of the
"could not load the Qt platform plugin xcb" error.

### Step 4 detail: why glib may never be bundled

This is a hard constraint that follows directly from not bundling libVLC, and
future work must not undo it.

The upstream excludelist assumes a self-contained application. This AppImage
is deliberately not one: it dlopens the host's libVLC, which dlopens roughly
400 host plugins into the same process. Those plugins resolve their own
dependencies against whatever the process has already loaded. The bundled
`python3` carries `DT_RPATH` (not `RUNPATH`) of `$ORIGIN/../lib`, and RPATH is
inherited by every `dlopen` in the process and outranks `LD_LIBRARY_PATH`, so
anything in `AppDir/usr/lib` wins for the host's plugins too.

`libqxcb.so` needs `libglib-2.0` and `libgthread-2.0` but not
`libgobject`/`libgio`/`libgmodule`, so an unguarded `ldd` walk bundles a
partial, older glib. Measured with a 22.04 build on a 26.04 target: 8 of 382
host VLC plugins failed to load with `undefined symbol: g_dir_unref`, among
them `libavcodec_plugin.so` and `libavformat_plugin.so`. H.264, HEVC, AAC and
MP3 would not decode, which defeats the entire point of linking against the
host's VLC.

Bundling the *complete* glib family is not the fix; it fails in the mirror
direction, with the host's newer plugins calling into an older ABI. The fix is
that no glib-family library enters the AppDir at all. Every desktop that has
VLC has glib, so depending on the host's is safe.

The acceptance test is a `dlopen` sweep of every host VLC plugin under
AppRun's environment, which must report zero failures. A passing `--version`
proves nothing here; this bug survived a full round of verification because
`--version` never touches a codec.

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
      QT_QPA_PLATFORMTHEME
LD_LIBRARY_PATH="$APPDIR/usr/lib:$LD_LIBRARY_PATH"
PYTHONSAFEPATH=1, PYTHONNOUSERSITE=1, unset PYTHONPATH PYTHONHOME
preflight: "$APPDIR/usr/bin/python3" -c "import vlc; vlc.libvlc_get_version()"
   exit 0  -> exec python3 -m loot_player "$@"
   nonzero -> print to stderr, show Qt dialog, exit 1
```

### Why the Python path variables are scrubbed

A bundle must run its own code. `PYTHONSAFEPATH` keeps the working directory
off `sys.path`, so launching from a source checkout runs the AppImage rather
than the checkout. It covers nothing else, so `PYTHONNOUSERSITE` is also set:
`~/.local/lib/python3.13/site-packages` otherwise sorts ahead of the bundle's
own site-packages, and a user with their own PyQt6 there would shadow the
bundled one with a mismatched ABI. `PYTHONPATH` and `PYTHONHOME` are unset for
the same reason.

### Why `QT_QPA_PLATFORM=xcb`

Same reason the Makefile's `run` target sets it: libVLC's `set_xwindow` needs an
X11 window handle, which does not exist under a native Wayland Qt session. It is
a no-op on X11. Defaulted rather than forced, so a user can override it.

### Why unset the Qt path variables

A KDE session exports `QT_PLUGIN_PATH` pointing at the host's Qt 6. If the
bundled Qt picks those up it loads host plugins against bundled libraries and
crashes. PyQt6 resolves its own plugins relative to the package, so clearing
these is both safe and necessary.

`QT_QPA_PLATFORMTHEME` is cleared for a related reason: a GNOME target sets it
to `gtk3`, and Qt would load a gtk3 theme plugin against the host's GTK stack.
Qt degrades to its own dialogs rather than crashing, so this is styling loss
and stderr noise, but it is avoidable. `libqgtk3.so` is deleted from the AppDir
too, so the variable is belt and braces.

Only that one plugin is deleted. `libqxdgdesktopportal.so` stays: it needs
`libQt6Gui`, `libQt6DBus`, `libQt6Core`, `libGL`, `libxkbcommon` and
`libstdc++` and nothing from GTK or glib, and it supplies xdg-portal file
dialogs plus the `org.freedesktop.appearance color-scheme` hint. Removing the
whole `platformthemes` directory leaves Qt on `QGenericUnixTheme` and its
default light palette, which makes the app render light on a dark desktop.

### Why the VLC preflight

`loot_player.app` imports `player`, which imports `vlc`, so a missing VLC
breaks before any window exists. Launched from a desktop menu that is a silent
no-op with nothing to diagnose.

Detecting it takes more than `import vlc`, **which succeeds on a machine with
no VLC installed at all.** On Linux `vlc.py` calls
`ctypes.CDLL(find_library("vlc"))`; with VLC absent `find_library` returns
None, so the call is `ctypes.CDLL(None)`, which is `dlopen(NULL)` and hands
back the running program's own symbol table instead of raising. The
`libvlc.so.5` fallback at `vlc.py:191` that would raise
`NotImplementedError("Cannot find libvlc lib")` is therefore never reached.
The failure surfaces later, at the first real libvlc symbol lookup. So both
AppRun and `loot_player.vlc_check.libvlc_available` probe by calling
`vlc.libvlc_get_version()` rather than by importing.

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
| Host VLC plugins still load | `dlopen` sweep of every plugin under `/usr/lib/x86_64-linux-gnu/vlc/plugins` using the bundled `python3` with AppRun's environment. Must report zero failures. This is the acceptance test for the no-glib rule and the only automatable proxy for "media actually decodes". |
| Actually plays media | Manual, on the dev machine. Launch the AppImage, add a library, play a file. Not automatable here. |
| Icon resolves when installed | Manual. The window icon is present in the AppImage, which is the case `parent.parent` broke. |
| Existing tests still pass | `make test`. The asset move and the `--version` flag are the only things that could disturb them. |

## Known limits

- **x86_64 only.**
- **glibc 2.34 floor.** Set by the PyQt6 wheel tags, not by us.
- **VLC must be installed.** By design.
- **No glib-family library may ever be bundled**, because the host's VLC
  plugins would resolve against it. See "why glib may never be bundled" above.
  The build fails if one appears. This constrains any future addition to the
  AppDir, not just the current `ldd` walk.
- **The glib rule is a patch on one instance, not a fix for the class.** The
  underlying mechanism is untouched: the bundled `python3` still carries
  `DT_RPATH` (not `RUNPATH`) `$ORIGIN/../lib`, so every `dlopen` the host's
  libVLC performs still prefers `AppDir/usr/lib` over the system copy. Only
  glib is denied.

  Seven sonames still in `usr/lib` are direct `NEEDED` entries of host VLC
  plugins on the machine this was measured on: `libdbus-1.so.3` (3 plugins),
  `libgcrypt.so.20` (6), `libpng16.so.16` (1), `libsystemd.so.0` (1),
  `libxcb-keysyms.so.1` (2), `libxcb-randr.so.0` (1), `libxcb-shm.so.0` (3).
  Several export strictly fewer symbols than the host's: bundled
  `libsystemd.so.0` exports 861 against the host's 1149, and bundled
  `libdbus-1.so.3` exports 659 against 694. That is the same shape as the glib
  bug. It does not fire only because the plugins that need those libraries do
  not happen to call the newer symbols.

  The `dlopen` sweep is currently the only thing that detects this class, and
  it is run by hand. Automating it is routed into the CI task, which turns the
  residual from a latent risk into a monitored one.

  A structural fix would mean keeping `AppDir/usr/lib` off any process-wide
  search path: `RUNPATH` rather than `RPATH` on the bundled objects, since
  `RUNPATH` is not inherited by `dlopen`, plus dropping `LD_LIBRARY_PATH` from
  AppRun. That was considered and deliberately not attempted here. It is a
  design change to how the bundle resolves its own libraries and it would risk
  a working build.
- **Only rootless podman is exercised.** Rootful docker leaves `build/` and
  `dist/` owned by root and `make appimage-clean` then needs sudo. Documented
  in the Makefile.
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
| `packaging/appimage-excludelist` | new, vendored verbatim from upstream |
| `packaging/appimage-extra-excludes` | new, our own additions to the above |
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
