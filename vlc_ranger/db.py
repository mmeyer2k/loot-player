from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

from vlc_ranger.models import FileRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS libraries (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    type    TEXT NOT NULL CHECK (type IN ('movies','tv','music','generic')),
    added   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS library_folders (
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    path        TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_library_folders_lib ON library_folders(library_id);

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
    path        TEXT UNIQUE NOT NULL,
    parent_dir  TEXT NOT NULL,
    filename    TEXT NOT NULL,
    ext         TEXT NOT NULL,
    size        INTEGER,
    mtime       INTEGER,
    duration    REAL,
    last_seen   INTEGER NOT NULL,
    title       TEXT,
    year        INTEGER,
    series      TEXT,
    season      INTEGER,
    episode     INTEGER,
    artist      TEXT,
    album       TEXT,
    track       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_files_library ON files(library_id);
CREATE INDEX IF NOT EXISTS idx_files_parent  ON files(parent_dir);
CREATE INDEX IF NOT EXISTS idx_files_ext     ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_mtime   ON files(mtime);
CREATE INDEX IF NOT EXISTS idx_files_series  ON files(library_id, series, season, episode);
CREATE INDEX IF NOT EXISTS idx_files_album   ON files(library_id, artist, album, track);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename, parent_dir, title, series, artist, album,
    content='files', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, filename, parent_dir, title, series, artist, album)
    VALUES (new.id, new.filename, new.parent_dir, new.title, new.series, new.artist, new.album);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, parent_dir, title, series, artist, album)
    VALUES('delete', old.id, old.filename, old.parent_dir, old.title, old.series, old.artist, old.album);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, parent_dir, title, series, artist, album)
    VALUES('delete', old.id, old.filename, old.parent_dir, old.title, old.series, old.artist, old.album);
    INSERT INTO files_fts(rowid, filename, parent_dir, title, series, artist, album)
    VALUES (new.id, new.filename, new.parent_dir, new.title, new.series, new.artist, new.album);
END;

CREATE TABLE IF NOT EXISTS watch_state (
    file_id      INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    position     REAL DEFAULT 0,
    watched      INTEGER DEFAULT 0,
    last_played  INTEGER
);

CREATE TABLE IF NOT EXISTS queue (
    pos      INTEGER PRIMARY KEY,
    file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ui_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class LibraryDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._pre_schema_migrate()
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _pre_schema_migrate(self) -> None:
        """Adjust legacy v0 tables so SCHEMA's CREATE-IF-NOT-EXISTS calls
        (which add new indexes/columns) succeed before the post-schema data
        migration runs."""
        has_files = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='files'"
        ).fetchone() is not None
        if has_files:
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(files)")}
            # v0 lacked library_id and the richer metadata columns; add anything missing.
            v1_extra_cols = [
                ("library_id", "INTEGER REFERENCES libraries(id) ON DELETE CASCADE"),
                ("title", "TEXT"),
                ("year", "INTEGER"),
                ("series", "TEXT"),
                ("season", "INTEGER"),
                ("episode", "INTEGER"),
                ("artist", "TEXT"),
                ("album", "TEXT"),
                ("track", "INTEGER"),
            ]
            for name, decl in v1_extra_cols:
                if name not in cols:
                    self.conn.execute(f"ALTER TABLE files ADD COLUMN {name} {decl}")

        # v0 had a 2-column files_fts (filename, parent_dir). v1 expands it to 6 columns.
        # CREATE VIRTUAL TABLE IF NOT EXISTS is a no-op, so reshape by drop+recreate.
        fts_exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='files_fts'"
        ).fetchone() is not None
        if fts_exists:
            fts_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(files_fts)")]
            if set(fts_cols) != {"filename", "parent_dir", "title", "series", "artist", "album"}:
                self.conn.execute("DROP TRIGGER IF EXISTS files_ai")
                self.conn.execute("DROP TRIGGER IF EXISTS files_ad")
                self.conn.execute("DROP TRIGGER IF EXISTS files_au")
                self.conn.execute("DROP TABLE files_fts")

    def _migrate(self) -> None:
        v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if v < 1:
            with self.conn:
                self._migrate_v0_to_v1()
                self.conn.execute("PRAGMA user_version = 1")

    def _migrate_v0_to_v1(self) -> None:
        """Move existing `roots` rows into a Default library and backfill files.library_id."""
        has_roots = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='roots'"
        ).fetchone() is not None
        if not has_roots:
            return

        old_roots = [r[0] for r in self.conn.execute("SELECT path FROM roots")]
        if old_roots:
            self.conn.execute(
                "INSERT OR IGNORE INTO libraries(name, type, added) VALUES (?, ?, ?)",
                ("Default", "generic", int(time.time())),
            )
            lib_id = self.conn.execute(
                "SELECT id FROM libraries WHERE name='Default'"
            ).fetchone()[0]
            for r in old_roots:
                normalized = r.rstrip("/") or r          # don't turn "/" into ""
                self.conn.execute(
                    "INSERT OR IGNORE INTO library_folders(library_id, path) VALUES (?, ?)",
                    (lib_id, normalized),
                )
            # Sync the FTS shadow table with existing pre-v1 file rows so the
            # post-UPDATE trigger has consistent state to delete-then-reinsert.
            self.conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            # Backfill: each existing file gets library_id of the deepest matching folder.
            self.conn.execute("""
                UPDATE files SET library_id = (
                    SELECT lf.library_id FROM library_folders lf
                    WHERE files.path LIKE lf.path || '/%'
                    ORDER BY length(lf.path) DESC LIMIT 1
                ) WHERE library_id IS NULL
            """)
        self.conn.execute("DROP TABLE roots")

    # libraries -----------------------------------------------------------
    def add_library(self, name: str, type_: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO libraries(name, type, added) VALUES (?, ?, ?)",
            (name, type_, int(time.time())),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_library(self, lib_id: int, name: str, type_: str) -> None:
        self.conn.execute(
            "UPDATE libraries SET name=?, type=? WHERE id=?", (name, type_, lib_id)
        )
        self.conn.commit()

    def delete_library(self, lib_id: int) -> None:
        self.conn.execute("DELETE FROM libraries WHERE id=?", (lib_id,))
        self.conn.commit()

    def list_libraries(self) -> list[tuple[int, str, str]]:
        return list(self.conn.execute("SELECT id, name, type FROM libraries ORDER BY name"))

    def add_library_folder(self, lib_id: int, path: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO library_folders(library_id, path) VALUES (?, ?)",
            (lib_id, path.rstrip("/") or path),
        )
        self.conn.commit()

    def remove_library_folder(self, folder_id: int) -> None:
        self.conn.execute("DELETE FROM library_folders WHERE id=?", (folder_id,))
        self.conn.commit()

    def library_folders(self, lib_id: int) -> list[tuple[int, str]]:
        return list(self.conn.execute(
            "SELECT id, path FROM library_folders WHERE library_id=? ORDER BY path",
            (lib_id,),
        ))

    def get_library_type(self, lib_id: int) -> str:
        row = self.conn.execute("SELECT type FROM libraries WHERE id=?", (lib_id,)).fetchone()
        return row[0] if row else "generic"

    # files ----------------------------------------------------------------
    def upsert_files(self, rows: Iterable[tuple]) -> None:
        """rows: (path, parent_dir, filename, ext, size, mtime, last_seen)"""
        self.conn.executemany(
            """INSERT INTO files(path, parent_dir, filename, ext, size, mtime, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   size=excluded.size, mtime=excluded.mtime, last_seen=excluded.last_seen""",
            rows,
        )

    def commit(self):
        self.conn.commit()

    def purge_stale(self, scan_started: int, root: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM files WHERE last_seen < ? AND path LIKE ?",
            (scan_started, root.rstrip("/") + "/%"),
        )
        self.conn.commit()
        return cur.rowcount

    # search / browse ------------------------------------------------------
    def search(self, query: str, limit: int = 500) -> list[FileRow]:
        # FTS5 query — escape simply by quoting tokens. For more complex
        # syntax (AND, OR, prefix*) pass query through unchanged.
        if not query.strip():
            return []
        sql = """
            SELECT f.id, f.library_id, f.path, f.parent_dir, f.filename, f.ext, f.size, f.mtime, f.duration,
                   f.title, f.year, f.series, f.season, f.episode, f.artist, f.album, f.track
            FROM files_fts JOIN files f ON f.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank LIMIT ?
        """
        try:
            return [FileRow(*r) for r in self.conn.execute(sql, (query, limit))]
        except sqlite3.OperationalError:
            # invalid FTS syntax — fall back to LIKE
            like = f"%{query}%"
            sql2 = """SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                             title, year, series, season, episode, artist, album, track
                      FROM files
                      WHERE filename LIKE ? OR parent_dir LIKE ?
                      ORDER BY filename LIMIT ?"""
            return [FileRow(*r) for r in self.conn.execute(sql2, (like, like, limit))]

    def files_in_library(self, library_id: int) -> list[FileRow]:
        sql = """SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                        title, year, series, season, episode, artist, album, track
                 FROM files WHERE library_id=? ORDER BY filename"""
        return [FileRow(*r) for r in self.conn.execute(sql, (library_id,))]

    def tv_shows(self, library_id: int) -> list[tuple[str, int]]:
        """Returns (series, episode_count). NULL series shows as '(Unsorted)'."""
        return list(self.conn.execute(
            """SELECT COALESCE(series, '(Unsorted)') AS s, COUNT(*) FROM files
               WHERE library_id=? GROUP BY s ORDER BY s""",
            (library_id,),
        ))

    def tv_seasons(self, library_id: int, series: str) -> list[tuple[int | None, int]]:
        return list(self.conn.execute(
            """SELECT season, COUNT(*) FROM files
               WHERE library_id=? AND COALESCE(series,'(Unsorted)')=?
               GROUP BY season ORDER BY season""",
            (library_id, series),
        ))

    def tv_episodes(self, library_id: int, series: str,
                    season: int | None) -> list[FileRow]:
        cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                  title, year, series, season, episode, artist, album, track"""
        if season is None:
            sql = f"""SELECT {cols} FROM files
                      WHERE library_id=? AND COALESCE(series,'(Unsorted)')=? AND season IS NULL
                      ORDER BY filename"""
            args = (library_id, series)
        else:
            sql = f"""SELECT {cols} FROM files
                      WHERE library_id=? AND COALESCE(series,'(Unsorted)')=? AND season=?
                      ORDER BY episode, filename"""
            args = (library_id, series, season)
        return [FileRow(*r) for r in self.conn.execute(sql, args)]

    def files_under(self, dir_path: str, recursive: bool = True) -> list[FileRow]:
        """Files inside a folder. recursive=True walks subdirectories."""
        if recursive:
            like = dir_path.rstrip("/") + "/%"
            sql = """SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                            title, year, series, season, episode, artist, album, track
                     FROM files WHERE path LIKE ? ORDER BY path"""
            args = (like,)
        else:
            sql = """SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                            title, year, series, season, episode, artist, album, track
                     FROM files WHERE parent_dir = ? ORDER BY filename"""
            args = (dir_path,)
        return [FileRow(*r) for r in self.conn.execute(sql, args)]

    def child_dirs(self, parent: str) -> list[str]:
        """Immediate child directories of `parent` that contain (directly or
        recursively) at least one indexed file."""
        prefix = parent.rstrip("/") + "/"
        rows = self.conn.execute(
            "SELECT DISTINCT parent_dir FROM files WHERE parent_dir LIKE ?",
            (prefix + "%",),
        ).fetchall()
        children = set()
        plen = len(prefix)
        for (pdir,) in rows:
            rest = pdir[plen:]
            if not rest:
                continue
            first = rest.split("/", 1)[0]
            children.add(prefix + first)
        return sorted(children)

    # queue persistence ----------------------------------------------------
    def save_queue(self, file_ids: list[int]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM queue")
            self.conn.executemany(
                "INSERT INTO queue(pos, file_id) VALUES (?, ?)",
                list(enumerate(file_ids)),
            )

    def load_queue(self) -> list[FileRow]:
        sql = """SELECT f.id, f.library_id, f.path, f.parent_dir, f.filename, f.ext, f.size, f.mtime, f.duration,
                        f.title, f.year, f.series, f.season, f.episode, f.artist, f.album, f.track
                 FROM queue q JOIN files f ON f.id = q.file_id
                 ORDER BY q.pos"""
        return [FileRow(*r) for r in self.conn.execute(sql)]
