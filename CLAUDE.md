# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running

```bash
python3 main.py
# On KDE Wayland, libVLC's set_xwindow needs XCB:
QT_QPA_PLATFORM=xcb python3 main.py
```

Dependencies (`apt`): `vlc`, `python3-pyqt6`, `python3-vlc`, `python3-qtawesome`, `python3-pytest`.

## Tests

```bash
python3 -m pytest tests/ -v
```

There's no linter or build step.

## State on disk

`$XDG_DATA_HOME/loot-player/library.db` (default: `~/.local/share/loot-player/library.db`). Schema versioned via `PRAGMA user_version`. `data_dir()` walks a rename chain (`vlc-library` → `vlc-ranger` → `loot-player`) and atomically renames the dir at launch.

## Package layout (`loot_player/`)

The app is a package, not a single file. Each module is small and focused.

- **`db.py`** — `LibraryDB`. Schema string + `_migrate` (v0→v1, see below). **All** SQL lives here. FTS5 mirror `files_fts` kept in sync via three triggers (`files_ai`/`files_ad`/`files_au`); if you add a searchable column to `files`, edit the virtual table and all three triggers.
- **`scanner.py`** — `Scanner(QThread)`. Opens its own sqlite3 connection (objects can't cross threads). `os.scandir` walk, batched inserts at 500, `ON CONFLICT(path) DO UPDATE` upsert, `last_seen`-based purge. Calls `matching.parse(library_type, …)` before each insert to populate the parsed columns. One scan at a time enforced in `MainWindow._start_scan_library`.
- **`matching.py`** — pure functions: `parse_movie`, `parse_tv`, `parse_music`, `parse_generic`, plus `parse(library_type, filename, parent_dir)` dispatcher. Unit-tested in `tests/test_matching.py`.
- **`models.py`** — `FileRow` dataclass (17 fields), `QueueModel` (in-memory list mirrored to `QStandardItemModel`). `_rebuild()` is the simple-but-fine approach for any non-append change.
- **`player.py`** — `VlcWidget(QFrame)`. Owns libVLC `Instance` + `MediaPlayer`. Calls `set_xwindow(winId())` in `attach()` — **must be called after the widget is shown**. Emits `loading_started` / `playback_started` from libVLC events (queued to the main thread).
- **`app.py`** — `MainWindow`, transport bar, the wiring hub. `APP_NAME = "loot-player"` (on-disk + repo name); `APP_BRAND = "loot"` (window title and visible label). 500ms `QTimer` (`_on_tick`) refreshes the seek slider, time label, play/pause icon, and handles auto-advance on track end.
- **`ui/library_tree.py`** — the tree on the left. Builds libraries → folders → files, then `_collapse_chains` merges single-child folder chains into compound nodes (`Action/2024`); single-folder libraries hoist their children up under the library node. Bold-on-current-playing via `set_playing(file_id)`.
- **`ui/library_editor.py`** — "+ New Library" / "Edit library" modal dialog.
- **`ui/queue_panel.py`** — toggleable right-rail panel. Auto-hidden when queue is empty.

## Database schema (v1)

`libraries(id, name UNIQUE, type CHECK ∈ {movies,tv,music,generic})` + `library_folders(id, library_id FK, path UNIQUE)` + `files(id, library_id FK, path UNIQUE, parent_dir, filename, ext, size, mtime, duration, last_seen, title, year, series, season, episode, artist, album, track)` + `files_fts` (6-col FTS5 mirror: filename, parent_dir, title, series, artist, album) + `watch_state(file_id PK)` + `queue(pos PK, file_id FK)` + `ui_state(key PK, value)`.

`_migrate_v0_to_v1` drops the legacy `roots` table, rolls its paths into a `"Default"` generic library, and backfills `files.library_id` by deepest-folder-prefix match. Wrapped in a single transaction; aware of the v0 files_fts shape mismatch (drops + recreates the FTS table before SCHEMA runs).

## Invariants worth preserving

- **Persist queue on every mutation.** All queue-mutating handlers in `MainWindow` call `_persist_queue()` after.
- **Schema changes need a migration step.** Add to `_migrate_v0_to_v1`-style helpers and bump `user_version`; don't rely on `CREATE TABLE IF NOT EXISTS` to evolve existing DBs.
- **`MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS`** in `scanner.py` is the source of truth for indexable file types.
- **FTS5 query syntax can be invalid.** `LibraryDB.search` / `search_with_library` catches `sqlite3.OperationalError` and falls back to `LIKE`. Preserve that.
- **libVLC events fire on a worker thread.** Use `Qt.ConnectionType.QueuedConnection` for any signal handler that touches widgets.
- **Single SQLite writer.** Scanner has its own connection but only one scan runs at a time (enforced in `_start_scan_library`). Keep it that way.

## Tone for commits

Lowercase scoped prefix (`feat(ui):`, `fix(db):`, `refactor:`, `docs:`). Body explains *why*. Don't use the word "land".
