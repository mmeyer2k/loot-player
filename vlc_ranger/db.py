from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

from vlc_ranger.models import FileRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS roots (
    id      INTEGER PRIMARY KEY,
    path    TEXT UNIQUE NOT NULL,
    added   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    parent_dir  TEXT NOT NULL,
    filename    TEXT NOT NULL,
    ext         TEXT NOT NULL,
    size        INTEGER,
    mtime       INTEGER,
    duration    REAL,
    last_seen   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_parent ON files(parent_dir);
CREATE INDEX IF NOT EXISTS idx_files_ext    ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_mtime  ON files(mtime);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename, parent_dir,
    content='files', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, filename, parent_dir)
    VALUES (new.id, new.filename, new.parent_dir);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, parent_dir)
    VALUES('delete', old.id, old.filename, old.parent_dir);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, parent_dir)
    VALUES('delete', old.id, old.filename, old.parent_dir);
    INSERT INTO files_fts(rowid, filename, parent_dir)
    VALUES (new.id, new.filename, new.parent_dir);
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
"""


class LibraryDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # roots ----------------------------------------------------------------
    def add_root(self, path: str) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO roots(path, added) VALUES (?, ?)",
            (path, int(time.time())),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM roots WHERE path=?", (path,)).fetchone()
        return row[0]

    def list_roots(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT path FROM roots ORDER BY path")]

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
            SELECT f.id, f.path, f.parent_dir, f.filename, f.ext, f.size, f.mtime, f.duration
            FROM files_fts JOIN files f ON f.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank LIMIT ?
        """
        try:
            return [FileRow(*r) for r in self.conn.execute(sql, (query, limit))]
        except sqlite3.OperationalError:
            # invalid FTS syntax — fall back to LIKE
            like = f"%{query}%"
            sql2 = """SELECT id, path, parent_dir, filename, ext, size, mtime, duration
                      FROM files
                      WHERE filename LIKE ? OR parent_dir LIKE ?
                      ORDER BY filename LIMIT ?"""
            return [FileRow(*r) for r in self.conn.execute(sql2, (like, like, limit))]

    def files_under(self, dir_path: str, recursive: bool = True) -> list[FileRow]:
        """Files inside a folder. recursive=True walks subdirectories."""
        if recursive:
            like = dir_path.rstrip("/") + "/%"
            sql = """SELECT id, path, parent_dir, filename, ext, size, mtime, duration
                     FROM files WHERE path LIKE ? ORDER BY path"""
            args = (like,)
        else:
            sql = """SELECT id, path, parent_dir, filename, ext, size, mtime, duration
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
        sql = """SELECT f.id, f.path, f.parent_dir, f.filename, f.ext, f.size, f.mtime, f.duration
                 FROM queue q JOIN files f ON f.id = q.file_id
                 ORDER BY q.pos"""
        return [FileRow(*r) for r in self.conn.execute(sql)]
