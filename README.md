# vlc-library

A library/queue-forward video player for Linux/KDE. Browses huge hierarchical
media libraries with full-text search and plays them inside an embedded VLC
render surface (libVLC), so playback feels native, not "launching VLC."

## What's in this skeleton

- **Embedded libVLC** rendering into a `QFrame` via `set_xwindow(winId())`. No
  subprocess, no reparenting hacks — VLC draws directly into the app window.
- **SQLite + FTS5** index for fast search across tens/hundreds of thousands of
  files. Schema includes `files`, `watch_state`, `queue`, `roots`, plus FTS5
  triggers kept in sync via `AFTER INSERT/UPDATE/DELETE`.
- **Background scanner thread** using `os.scandir()` (much faster than
  `os.walk`) with batched inserts inside a single transaction. Cancellable.
  Purges files that disappeared between scans.
- **Hierarchical folder tree** built lazily from the index (expands a node →
  query DISTINCT child dirs from DB, no extra disk reads).
- **Queue** with: add to end, add to front, play next, remove, clear, jump-to.
  Folder-level queueing too. Auto-advance on track end. Queue persists to DB
  across restarts.
- **Search box** powered by FTS5. Supports prefix (`break*`), AND, OR, NOT,
  phrase queries. Falls back to LIKE if syntax is invalid.

## Setup

### System deps (Arch/KDE)

```bash
sudo pacman -S vlc python python-pyqt6
```

On Debian/Ubuntu:

```bash
sudo apt install vlc python3-pyqt6 python3-pip
```

### Python deps

```bash
pip install --user python-vlc
# PyQt6 from pip also works if your distro package is too old:
# pip install --user PyQt6
```

### Wayland note

If you're on KDE Wayland (not X11/XWayland), `set_xwindow` may not work.
Quickest fix while developing:

```bash
QT_QPA_PLATFORM=xcb python main.py
```

A proper Wayland path uses `libvlc_media_player_set_xwindow` with an XWayland
fallback or a `vlc-vdpau`/EGL output module — out of scope for the skeleton.

## Run

```bash
python main.py
```

First launch: click **Scan Folder…** and pick a library root. The scan runs in
the background; the folder tree and search become populated as it progresses.
You can add multiple roots.

## Layout

```
┌─ Toolbar: Scan Folder · Rescan All ─────────────────────────────────┐
├─────────────────────┬───────────────────────────────────────────────┤
│  Library (folders)  │                                               │
│    /movies          │            embedded VLC render                │
│    /tv              │                                               │
│  ─────────────────  │                                               │
│  Search: ___        │                                               │
│  ┌ results ──────┐  │                                               │
│  │ file | folder │  │                                               │
│  └───────────────┘  ├───────────────────────────────────────────────┤
│  ─────────────────  │  Now playing: …                               │
│  Queue              │  [⏯] [⏹] [⏭]  ━━━━●━━━━━━━━━━━                │
│  ┌ # | file ─────┐  │                                               │
│  │   …           │  │                                               │
│  └───────────────┘  │                                               │
│  [▶ Play next] [Clear] [Remove]                                     │
└─────────────────────┴───────────────────────────────────────────────┘
```

Right-click anywhere (folder tree, results, queue) for context menus with the
queue actions.

## Key code paths to learn before extending

- `LibraryDB` — all SQL. Schema is at the top in `SCHEMA`. If you add columns,
  add them here and write a tiny migration (check `PRAGMA user_version`).
- `Scanner.run` — adjust `MEDIA_EXTS` to add/remove file types. The
  `ON CONFLICT(path) DO UPDATE` clause means rescans are cheap and idempotent.
- `VlcWidget` — the libVLC instance and media_player live here. To add audio
  track / subtitle selection, you'd add methods that call into
  `self.player.audio_set_track(n)` / `self.player.video_set_spu(n)`.
- `QueueModel` — pure in-memory list mirrored to the view. `_rebuild()` is the
  simple-but-fine approach; if queues get >10k items you'd switch to row-level
  insert/remove notifications.
- `MainWindow._on_tick` — the 500ms timer that updates the transport bar and
  auto-advances on track end. Reasonable place to also write watch position
  back to `watch_state` periodically.

## Roadmap (good next steps for Claude Code)

### Phase 1 — finish the basics
- [ ] **Resume position**: write `player.get_time()` to `watch_state` every
      ~5 seconds; on play, seek to it (with a "Start over?" prompt if >90%).
- [ ] **Watched markers**: mark file watched when position > 90% of duration.
      Show a ✓ column in results.
- [ ] **Duration enrichment**: spawn a low-priority worker that runs `ffprobe`
      on files where `duration IS NULL`, batches results into the DB.
- [ ] **Drag-and-drop queue reorder**: enable `setDragDropMode` on the queue
      view, implement `dropMimeData` in `QueueModel`.
- [ ] **Filter chips above results**: All / Video / Audio / Unwatched.

### Phase 2 — library quality of life
- [ ] **Live folder watching** with `watchdog` for incremental updates. Hook
      to `FileSystemEventHandler.on_created/on_deleted/on_moved`.
- [ ] **Saved smart playlists**: e.g. "Unwatched in /tv/Breaking Bad",
      "Added in the last 30 days". Persist as a `playlists` table where each
      row is a saved FTS query + filters.
- [ ] **Thumbnails**: extract via `ffmpeg -ss 00:01:00 -vframes 1`. Cache in
      `~/.cache/vlc-library/thumbs/<sha1(path)>.jpg`. Show in a switchable
      grid view.
- [ ] **TV episode grouping**: regex-match `SxxEyy` patterns in filenames,
      add `series`/`season`/`episode` columns to `files`, group display.
- [ ] **Multi-select drag from results into queue.**

### Phase 3 — polish
- [ ] **Settings dialog**: hardware decoding on/off, default subtitle track,
      audio output device (libVLC supports these via `--avcodec-hw`,
      `--sub-language`, `--aout`).
- [ ] **Global hotkeys** (Space, F, M, ←/→) when the video has focus.
- [ ] **MPRIS2 publishing** so KDE's media controls in the system tray drive
      this app. `dbus-next` or `pydbus`.
- [ ] **Subtitle track menu** + external subtitle file picker.
- [ ] **External player fallback**: a "Open in VLC" action that just runs
      `vlc <path>` for files libVLC's embedded mode chokes on.

### Phase 4 — bigger swings
- [ ] **Optional TMDB enrichment** for movies/TV (free API key). Stays
      optional; library still works fully offline.
- [ ] **Remote control**: small HTTP API so a phone can browse and queue.
- [ ] **Sync across machines**: rsync-style sync of the SQLite watch_state
      between desktops. Or store watch_state in a small SQLite file under
      the library root itself.

## File layout

```
vlc-library/
├── main.py        # entire app (single file for now)
└── README.md      # this file
```

When the file gets unwieldy (it will around phase 2), split into:

```
vlc-library/
├── app.py         # entry point, QApplication, MainWindow wiring
├── db.py          # LibraryDB, schema, migrations
├── scanner.py     # Scanner thread + ffprobe enrichment
├── player.py      # VlcWidget + transport
├── ui/
│   ├── library.py # folder tree + search results
│   └── queue.py   # QueueModel + view + reorder
└── README.md
```

## Known limitations of the skeleton

- No Wayland-native path (uses XWayland fallback).
- No duration column populated yet — needs `ffprobe` worker (Phase 1).
- Queue reorder is via "Remove + re-add"; no drag-reorder yet.
- One scan at a time (intentional — keeps SQLite writer single-threaded).
- No error reporting UI if libVLC fails to load a file; check stderr.

## Why this design over a Lua VLC extension

VLC's extension API is anemic for what you want: no real library model, no
hierarchical browser, the Lua sandbox can't easily run long-lived background
threads, and the UI is constrained to VLC's dialog system. Wrapping VLC the
other way around (your app owns the window, VLC is just the decoder) is the
same approach used by Kodi/Jellyfin Media Player/etc., and it gives you full
freedom over the UX while keeping VLC's playback quality.
