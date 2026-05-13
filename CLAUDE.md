# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running

```bash
python main.py
# On KDE Wayland, libVLC's set_xwindow needs XCB:
QT_QPA_PLATFORM=xcb python main.py
```

Dependencies: system `vlc`, plus `python-vlc` and `PyQt6` (see README for distro-specific install).

There is no test suite, linter config, or build step. Don't invent one unless asked.

## Where state lives

- Library DB: `$XDG_DATA_HOME/vlc-library/library.db` (defaults to `~/.local/share/vlc-library/library.db`).
- Everything else (queue, scanned roots, watch state) is in that DB. Delete the file to fully reset.

## Architecture (single file: `main.py`)

The whole app is one module, split by `# ---` banner comments into five layers. They depend top-down:

1. **`LibraryDB`** — owns the SQLite connection, schema, and *all* SQL in the app. Schema string `SCHEMA` is at the top; FTS5 mirror table `files_fts` is kept in sync by `AFTER INSERT/UPDATE/DELETE` triggers, so adding columns to `files` is safe but adding searchable fields means editing both the virtual table and all three triggers.
2. **`Scanner(QThread)`** — opens its **own** sqlite3 connection because sqlite objects can't cross threads. Walks via `os.scandir` (faster than `os.walk`), batches inserts at `batch_size=500`, uses `ON CONFLICT(path) DO UPDATE` so rescans are idempotent. After the walk, it deletes rows whose `last_seen < scan_started` under the same root — that's the purge for files that disappeared. One scan at a time is enforced in `MainWindow._start_scan`; keep it that way (SQLite single-writer).
3. **`VlcWidget(QFrame)`** — owns the libVLC `Instance` and `MediaPlayer`. libVLC renders directly into this widget's native window via `set_xwindow(winId())` on Linux. **`attach()` must be called after the widget is shown** — `winId()` is invalid before then. `main()` calls `w.show()` then `w.video.attach()`; `_play()` calls `attach()` again defensively before each playback.
4. **`QueueModel(QStandardItemModel)`** — pure in-memory list of `FileRow` mirrored to a `QStandardItemModel`. `_rebuild()` is the lazy approach used for any non-append change; it's fine until queues exceed ~10k items.
5. **`MainWindow`** — wires everything up. A 500ms `QTimer` (`_on_tick`) drives the transport slider and detects track-end for auto-advance.

## Invariants worth preserving

- **Persist the queue on every mutation.** All queue-mutating methods in `MainWindow` call `_persist_queue()`; if you add a new one, do the same — the in-memory model and the `queue` table must stay aligned across restarts.
- **Schema changes need a migration.** Bump `PRAGMA user_version` and run an `ALTER` against existing DBs; don't rely on `CREATE TABLE IF NOT EXISTS` to evolve schemas of users who already ran the app.
- **`MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS`** is what the scanner filters on. Anything not in this set is invisible to the library — add extensions there, not at the call site.
- **FTS5 query syntax can be invalid** (e.g. user typing a stray operator). `LibraryDB.search` catches `sqlite3.OperationalError` and falls back to `LIKE`. Preserve that fallback when modifying search.

## Roadmap

The README's "Roadmap" section lists concrete next steps (resume position, watched markers, ffprobe duration enrichment, drag-reorder, thumbnails, MPRIS2, etc.) and the README's "Key code paths to learn before extending" section names the right hook points for each. Read those before implementing new features rather than re-discovering the structure.
