# loot

A local-first media library and player for Linux/KDE. Pyplays files via
embedded libVLC inside a Qt window — no subprocess, no "launch VLC"
shell-out. Organize your stuff into named, typed libraries (Movies, TV,
Music, Generic), browse it through a hierarchical tree with smart-search,
and queue / shuffle / cinema-mode your way through it.

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
./loot-*-x86_64.AppImage --appimage-extract-and-run
```

Requires glibc 2.34 or newer: Ubuntu 22.04+, Debian 12+, Fedora 35+,
RHEL 9+, current Arch. x86_64 only.

`--appimage-extract-and-run` is there because AppImages normally need
FUSE 2, and Ubuntu 24.04 and later don't install it by default. If FUSE
2 is present on your system (`sudo apt install libfuse2t64` adds it on
newer Ubuntu), you can drop the flag and run the AppImage directly:

```bash
./loot-*-x86_64.AppImage
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

## Run

```bash
python3 main.py
# On KDE Wayland, libVLC's set_xwindow needs XCB:
QT_QPA_PLATFORM=xcb python3 main.py
```

First launch: click **+ New Library…** on the left, name it, pick a type
(Movies / TV / Music / Generic), point it at one or more folders. The
scan runs in the background; the tree fills in as it goes.

## Features

- **Typed libraries.** Movies / TV / Music / Generic. Filename parsing at
  scan time extracts year, series + season + episode, artist + album +
  track — surfaced where it's useful, ignored where it isn't.
- **Library tree.** Libraries → folders → subfolders → files. Single-chain
  folders collapse into compound nodes (`Action/2024`). Single-folder
  libraries hoist their contents under the library node directly. The
  currently-playing file is bold.
- **Smart search** (Ctrl+K). Search box at the top of the tree filters
  every node by text; matching branches auto-expand.
- **Queue.** Right-click a file or folder → `Play now` / `Play next`.
  Adding to an idle queue auto-starts playback. Queue panel auto-shows on
  the right whenever it has items.
- **Transport.** Slim VLC-style bar at the bottom: prev / play-pause /
  stop / next / shuffle / loading spinner / time / volume / cinema /
  fullscreen. Click anywhere on the seek slider to jump.
- **Shuffle**, three states cycled on click:
  - Off — folder-neighbor next.
  - Within library — random within the current library.
  - Across libraries — random anywhere indexed.
  Disabled while the queue has items (queue plays FIFO).
- **Cinema mode** (Ctrl+M). Hides the left tree and right queue; transport
  bar stays. **Fullscreen** (F or double-click the video) hides everything.
- **Persists.** Queue, shuffle mode, splitter sizes, currently-selected
  library — all in `ui_state`.

## Hotkeys

| Key | Action |
|---|---|
| Space | Play/pause |
| F | Fullscreen |
| Esc | Exit fullscreen or cinema mode |
| Ctrl+K | Focus search |
| Ctrl+M | Toggle cinema mode |

## Where state lives

`$XDG_DATA_HOME/loot-player/library.db` (defaults to
`~/.local/share/loot-player/library.db`). The schema is versioned
(`PRAGMA user_version`) and migrates forward from earlier names
(`vlc-ranger`, `vlc-library`) automatically — first launch will atomically
rename the directory.

Delete the file to fully reset.

## Architecture (one-line tour)

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
tests/                  # pytest: matching parsers + DB neighbor/random helpers
```

## Building the AppImage

```bash
make appimage        # -> dist/loot-<version>-x86_64.AppImage
```

Needs podman or docker. The build runs inside `ubuntu:22.04` rather than
on your machine: PyQt6 publishes exactly one x86_64 Linux wheel tag,
`manylinux_2_34`, so glibc 2.34 is the floor, and building against a
newer glibc produces a binary that runs almost nowhere.

libVLC is not bundled. The AppImage links against the host's VLC, which
keeps 382 VLC plugins and their codec dependencies out of the bundle.
`packaging/AppRun` checks for it at startup and explains what to install
if it is absent.

`make appimage-sweep` runs `packaging/vlc-plugin-sweep.py`, which dlopens
every one of the host's 382 VLC plugins through the AppImage's bundled
interpreter and fails if any hits an unresolved symbol; run it yourself
after `make appimage`, especially after touching the excludelist or
anything else that changes what gets bundled, and CI runs it again on
every tagged build. It exists because that link cuts both ways: any
library bundled for Qt's sake can shadow the host's copy for one of
VLC's plugins and break it. That happened during development: a bundled
glib broke `libavcodec` and `libavformat`, so nothing would have decoded
H.264 or AAC, and every other check still passed because `--version`
never touches Qt or VLC.

Set `CONTAINER_ENGINE=docker` to override the default of podman.
`make appimage-clean` removes `build/` and `dist/`.

## Tests

```bash
python3 -m pytest tests/ -v
```
