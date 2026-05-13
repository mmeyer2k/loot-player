# Libraries & Plex-style UI — Design

**Status:** approved, pending implementation plan
**Date:** 2026-05-13

## Problem

The current app exposes media as a flat list of "roots" — each scanned top-level folder is its own thing in the sidebar, and all files are presented through a single folder-tree + search-results + queue layout. This works for a single home directory of media but doesn't reflect how people actually organize: multiple drives, multiple categories (movies, TV, anime, music, lectures), each potentially spanning several folders.

We want a "Library" concept: a user-named bag of folders with a type that drives smarter parsing and a per-type browse view — roughly the way Plex organizes content, but staying fully local (no internet metadata, no poster art).

## Scope

In:
- Multi-folder, user-named libraries with a fixed type (`movies`, `tv`, `music`, `generic`).
- Per-type filename parsing (year for movies; `SxxEyy` for TV; path-based artist/album/track for music; none for generic).
- Per-type browse views: title-card grid for movies; shows → seasons → episodes drill-down for TV; artists → albums → tracks for music; flat sortable list for generic.
- Library editor dialog (create, edit name/type, add/remove folders).
- Global search across libraries.
- Queue preserved, moved into a toggleable right-side panel.
- Schema migration from v0 → v1, including rolling existing `roots` into a single `"Default"` generic library.
- Data dir rename `vlc-library` → `vlc-ranger` with an atomic `os.rename`.
- Package restructure from single-file `main.py` into a `vlc_ranger/` package.

Out (explicit non-goals for this change):
- Internet metadata enrichment (TMDB/TVDB, posters, summaries). Stays a future phase.
- ID3 tag reading via `mutagen` for music.
- `ffprobe`-driven duration enrichment (already in the roadmap, not this change).
- Drag-to-reorder queue.
- Watched markers / resume position (still roadmapped).
- User-pluggable library types or custom matching regex.

## Package layout

```
vlc-ranger/
├── main.py                # tiny entrypoint: argparse, QApplication, MainWindow
├── vlc_ranger/
│   ├── __init__.py
│   ├── app.py             # MainWindow wiring, toolbar, hotkeys, splitters
│   ├── db.py              # LibraryDB: schema, migrations, all SQL
│   ├── scanner.py         # Scanner QThread, dispatches into matching
│   ├── matching.py        # pure-function filename parsers per type
│   ├── player.py          # VlcWidget + transport
│   ├── models.py          # dataclasses: FileRow, Library, etc.
│   └── ui/
│       ├── __init__.py
│       ├── sidebar.py     # left rail: library list
│       ├── browse.py      # router: picks view per library type
│       ├── queue_panel.py # right rail: queue (toggleable)
│       ├── views/
│       │   ├── movies.py
│       │   ├── tv.py
│       │   ├── music.py
│       │   └── generic.py
│       └── library_editor.py
└── docs/superpowers/specs/...
```

Rationale: each UI view is small and replaceable; `matching.py` is pure functions and gets the only test suite worth writing now; `db.py` stays the sole owner of SQL.

The repo directory stays `vlc-ranger`; the import package is `vlc_ranger` (PEP 8 convention — same string with `-`→`_`). `APP_NAME` constant moves from `"vlc-library"` to `"vlc-ranger"`; the data dir is migrated by atomic rename at startup.

## Database schema (v1)

New / changed tables:

```sql
CREATE TABLE libraries (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    type    TEXT NOT NULL CHECK (type IN ('movies','tv','music','generic')),
    added   INTEGER NOT NULL
);

CREATE TABLE library_folders (
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    path        TEXT NOT NULL UNIQUE   -- folder belongs to exactly one library
);

-- files gains library_id + parsed structure
ALTER TABLE files ADD COLUMN library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE;
ALTER TABLE files ADD COLUMN title    TEXT;
ALTER TABLE files ADD COLUMN year     INTEGER;
ALTER TABLE files ADD COLUMN series   TEXT;
ALTER TABLE files ADD COLUMN season   INTEGER;
ALTER TABLE files ADD COLUMN episode  INTEGER;
ALTER TABLE files ADD COLUMN artist   TEXT;
ALTER TABLE files ADD COLUMN album    TEXT;
ALTER TABLE files ADD COLUMN track    INTEGER;

CREATE INDEX idx_files_library ON files(library_id);
CREATE INDEX idx_files_series  ON files(library_id, series, season, episode);
CREATE INDEX idx_files_album   ON files(library_id, artist, album, track);

CREATE TABLE ui_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

**Dropped:** `roots` table (after migration moves its data into `libraries` + `library_folders`).

**FTS5:** `files_fts` virtual table gains `series`, `title`, `artist`, `album` columns alongside the existing `filename`, `parent_dir`. All three triggers (`files_ai`, `files_ad`, `files_au`) updated to keep the mirror in sync. The `LIKE`-fallback path in `LibraryDB.search` is preserved.

**`watch_state` and `queue`:** unchanged (still keyed by `file_id`).

**No `shows` / `albums` tables.** Show and album lists are computed via `SELECT DISTINCT … WHERE library_id=?` queries, made cheap by the composite indexes above. This eliminates a whole class of staleness bugs when files are renamed or moved.

## Filename matching

All matching is pure functions in `matching.py`, called from the scanner before each batched insert. Return shape: `dict[str, Any]` with whichever of `title`, `year`, `series`, `season`, `episode`, `artist`, `album`, `track` the parser was able to extract.

**Movies (`parse_movie`)**
- Find first occurrence of `(YYYY)`, `.YYYY.`, `[YYYY]`, or ` YYYY ` where `1900 ≤ YYYY ≤ current_year + 2`. That's the year.
- Title = filename portion before the year, with `.`/`_` → space, whitespace collapsed, stripped.
- No year? `title = filename without ext`, `year = NULL`. Sorts under "Unknown year".

**TV (`parse_tv`)**
- Primary: regex on filename for `S\d{1,2}E\d{1,2}` (case-insensitive), `\d{1,2}x\d{1,2}`, or trailing `- E?\d{1,3}` patterns. Capture season + episode.
- Series = filename before the marker, normalized as in movies.
- Fallback: parse parent folder for `Season \d+` / `S0\d`; grandparent folder is the series; episode = leading digits or `- NN -` pattern in filename.
- Final fallback: `series = immediate parent folder`, `season = NULL`, `episode = NULL`. File still appears under that show in an "Unsorted" bucket.

**Music (`parse_music`)**
- Conventional layout: `…/<Artist>/<Album>/<NN - Title>.ext` → artist=grandparent, album=parent, track=leading digits, title=remainder.
- Two-level: `…/<Album>/<Title>.ext` → artist=NULL, album=parent.
- Flat: artist=NULL, album=NULL, title=filename-without-ext.
- ID3 tags via `mutagen` are out of scope; future enrichment pass analogous to `ffprobe`-for-duration.

**Generic (`parse_generic`)**
- `title = filename without ext`. Everything else NULL.

**Re-parsing.** Triggered by (a) library type change in the editor dialog, or (b) full rescan. Both batch `UPDATE files SET … WHERE id=?` — no disk reads.

## Scanner changes

The `Scanner` `QThread` keeps its current mechanics:
- Own sqlite connection (objects can't cross threads).
- `os.scandir` walk with explicit stack (no `os.walk`).
- Batched inserts at `batch_size=500` with `ON CONFLICT(path) DO UPDATE`.
- `last_seen`-based purge of files that disappeared between scans.
- Cancellable; one scan at a time enforced in `app.py`.

What changes:
- Takes a `library_id` and an iterable of folder paths (not a single root).
- Calls `matching.parse(library_type, path, parent_dir, filename)` before each batched insert; the parsed fields go into the same INSERT.
- `last_seen`-based purge runs per library (scoped by `library_folders.path LIKE` clauses).

## UI

Layout (replaces today's three-pane-left + video-right):

```
┌─ Toolbar: [+ New Library] [⟳ Rescan] [Queue (3) ▾] [⛶] ─────────────────┐
├──────────────┬──────────────────────────────────────┬──────────────────┤
│  Sidebar     │  Browse area   [global search ⌕]     │  Queue panel     │
│              │                                      │  (toggleable,    │
│  Libraries   │  (per-type view via QStackedWidget)  │   default off)   │
│  ──────────  │                                      │                  │
│ ▶ [M] Movies │                                      │                  │
│   [T] TV     │                                      │                  │
│   [T] Anime  │                                      │                  │
│   [♪] Music  │                                      │                  │
│   [G] Lect.  │                                      │                  │
│  ──────────  │                                      │                  │
│  [+ New…]    ├──────────────────────────────────────┤                  │
│              │  Video pane  (resizable splitter)    │                  │
│              │  Now playing · [▶][⏹][⏭] ━━●━━━━     │                  │
└──────────────┴──────────────────────────────────────┴──────────────────┘
```

Three columns. The middle column has a vertical splitter — browse on top, video below — default 70/30. Splitter position persists in `ui_state`.

**Sidebar (`ui/sidebar.py`)**
- One row per library; type-letter prefix in brackets.
- Right-click → Edit, Rescan, Delete.
- `+ New Library…` at the bottom opens the editor dialog.
- Selected library highlights and drives `browse.py`.

**Browse router (`ui/browse.py`)**
- `QStackedWidget` of per-type view widgets. Selecting a library swaps in its type's widget and feeds it `library_id`.
- Global search box at the top; results show across all libraries with a library-label column.

**Per-type views (`ui/views/*.py`)**
- **Movies (`movies.py`)** — `QListView` in icon-grid mode, cards show title + year. Sort: title / year / date added.
- **TV (`tv.py`)** — internal `QStackedWidget` of three pages: shows grid → seasons list → episodes table. Breadcrumb at top (`TV / Breaking Bad / Season 1`); Backspace or breadcrumb click navigates up. Parse-failed episodes appear under a synthetic "Unsorted" show.
- **Music (`music.py`)** — same shape as TV: artists → albums → tracks.
- **Generic (`generic.py`)** — sortable `QTableView`: Filename, Folder, Size, Modified. ≈ today's results table.

**Library editor dialog (`ui/library_editor.py`)**
- Fields: name (`QLineEdit`), type (`QComboBox`), folders list (`QListWidget` + `[+ Add Folder…] [− Remove]`).
- OK/Cancel.
- On save: insert library + library_folders rows, kick off background scan of any newly-added folders.
- On type change for an existing library: re-parse files in place (no disk re-walk).

**Right-click actions (consistent everywhere):**
- On a card / row / show / album: `▶ Play now`, `Add to queue (end)`, `Add to queue (front)`, `Play next`.
- On a show / season / album / library: same four, recursive over their files.

**Hotkeys:**
- `Space` — play/pause
- `F` — fullscreen video pane
- `Esc` — exit fullscreen
- `Ctrl+K` — focus search
- `Ctrl+Q` — toggle queue panel
- `Ctrl+B` — toggle sidebar
- `Backspace` — up one drill level

**Persisted UI state (`ui_state` table, string-keyed):**
- `selected_library_id`
- `tv.current.<library_id>` → `"show=<name>&season=<n>"` (drill position per library)
- `music.current.<library_id>` similarly
- `queue_panel_visible`, `sidebar_visible`
- `splitter.main`, `splitter.center` (geometry strings)

## Migration

Two migrations run on first launch of the new version. Both idempotent.

**A. Data dir rename, in `app.py` before `LibraryDB`:**
1. `new = $XDG_DATA_HOME/vlc-ranger`, `old = $XDG_DATA_HOME/vlc-library`.
2. If `new` exists → use it, done.
3. Else if `old` exists → `os.rename(old, new)`.
4. Else → fresh install, create `new`.

`os.rename` is atomic on the same filesystem (the XDG common case). No copy needed.

**B. Schema v0 → v1, in `db.py`, dispatched by `PRAGMA user_version`:**

```python
def _migrate(conn):
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    if v < 1:
        with conn:                       # one transaction
            conn.executescript(SCHEMA_V1_ADDITIONS)
            _seed_default_library(conn)
            _backfill_library_id(conn)
            conn.execute("DROP TABLE roots")
            conn.execute("PRAGMA user_version = 1")
```

- `_seed_default_library(conn)` — if any `roots` rows exist, create `library("Default", "generic")` and insert each old `roots.path` as a `library_folders` row under it.
- `_backfill_library_id(conn)` — set `files.library_id` to the library whose `library_folders.path` is the longest prefix of the file's `path`:
  ```sql
  UPDATE files SET library_id = (
      SELECT lf.library_id FROM library_folders lf
      WHERE files.path LIKE lf.path || '/%'
      ORDER BY length(lf.path) DESC LIMIT 1
  );
  ```
- Files that match no folder: `library_id` stays NULL. UI filters them out; next rescan cleans up.
- The migration does **not** re-parse filenames. Existing files appear with only `filename`/`parent_dir` populated (i.e. behaving as Generic) until the user clicks Rescan or "Re-parse library" on the library editor. Keeps the migration fast even on 100k-file libraries.

**`SCHEMA` constant** is rewritten to the v1 final shape so fresh installs go straight there; `_migrate` runs only for users coming from v0.

**Rollback:** none. The migration drops `roots` in the same transaction. Users worried about it can copy `library.db` before upgrading. Acceptable for a personal-use app.

## What stays the same

- `VlcWidget` and its `set_xwindow(winId())` lifecycle.
- Queue model semantics: add end / front / play-next / clear / jump-to / persist-on-every-mutation.
- Scanner internals (own connection, `os.scandir`, batched inserts, `ON CONFLICT` upsert, `last_seen` purge).
- FTS5 → LIKE fallback on invalid query syntax.
- Single-writer SQLite invariant (one scan at a time, enforced in `app.py`).

## Testing

`matching.py` is pure functions and gets the only test suite worth writing for this change. A `tests/test_matching.py` (`pytest` is fine; no test infra exists yet, this introduces it) covers:
- Movie patterns: `(YYYY)`, `.YYYY.`, scene release, no-year fallback, year-in-title edge case (`2001 A Space Odyssey (1968)`).
- TV patterns: `SxxEyy`, `s01e01`, `1x01`, `- 01 -`, folder-based season, "Unsorted" fallback.
- Music patterns: 3-level, 2-level, flat-fallback.
- Generic: title strip.

Everything else (scanner, UI, migration) is manually verified by running the app and clicking through.

## Open questions / risks

- **TV anime filenames** (release-group brackets, hash suffixes) are messier than typical TV releases. The TV parser is best-effort; anime-heavy users will see more episodes land in "Unsorted." A future enrichment pass (regex per library, mutagen-equivalent for video filenames) could improve this without changing the schema.
- **Library deletion** cascades: `ON DELETE CASCADE` on `library_folders.library_id` and `files.library_id` means deleting a library removes its files, which in turn removes their `watch_state` and `queue` entries via existing cascades. This is the intended behavior but worth flagging — there's no soft-delete or undo.
- **Two libraries pointing at overlapping folders.** The `library_folders.path UNIQUE` constraint prevents *exact* duplicates only; it does not prevent nested overlap (e.g. library A registers `/media/movies` and library B registers `/media/movies/2024`). A nested-overlap check runs at editor-save time and warns the user but does not block. Treating cross-library overlap as a known sharp edge rather than a hard constraint.
