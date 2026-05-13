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

    def _migrate(self) -> None:
        v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if v < 1:
            self._migrate_v0_to_v1()
            self.conn.execute("PRAGMA user_version = 1")
            self.conn.commit()

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
                self.conn.execute(
                    "INSERT OR IGNORE INTO library_folders(library_id, path) VALUES (?, ?)",
                    (lib_id, r),
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

    # roots ----------------------------------------------------------------
    # NOTE: These methods bridge the legacy "roots" concept to the v1
    # libraries/library_folders schema. A real library-aware API arrives in
    # Task 11; for now we keep a single implicit "Default" generic library
    # so the existing UI continues to work on a fresh v1 DB.
    def _default_library_id(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM libraries WHERE name=?", ("Default",)
        ).fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO libraries(name, type, added) VALUES (?, ?, ?)",
            ("Default", "generic", int(time.time())),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_root(self, path: str) -> int:
        lib_id = self._default_library_id()
        self.conn.execute(
            "INSERT OR IGNORE INTO library_folders(library_id, path) VALUES (?, ?)",
            (lib_id, path),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM library_folders WHERE path=?", (path,)
        ).fetchone()
        return row[0]

    def list_roots(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT path FROM library_folders ORDER BY path"
        )]

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
