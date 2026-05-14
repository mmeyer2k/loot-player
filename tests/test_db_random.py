import sqlite3

import pytest

from vlc_ranger.db import LibraryDB


def _insert_files(db: LibraryDB, library_id: int, names: list[str], parent_dir: str = "/m"):
    """Insert files directly, returning a list of inserted file ids in order."""
    conn = sqlite3.connect(str(db.db_path))
    ids: list[int] = []
    for name in names:
        cur = conn.execute(
            """INSERT INTO files(library_id, path, parent_dir, filename, ext,
                                 size, mtime, last_seen)
               VALUES (?, ?, ?, ?, ?, 0, 0, 0)""",
            (library_id, f"{parent_dir}/{name}", parent_dir, name, ".mkv"),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def test_random_in_library_returns_a_row_from_that_library(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib_a = db.add_library("A", "generic")
    lib_b = db.add_library("B", "generic")
    a_ids = _insert_files(db, lib_a, ["a1.mkv", "a2.mkv"], parent_dir="/a")
    b_ids = _insert_files(db, lib_b, ["b1.mkv", "b2.mkv"], parent_dir="/b")
    for _ in range(20):
        row = db.random_file_in_library(lib_a)
        assert row is not None
        assert row.library_id == lib_a
        assert row.id in a_ids
        assert row.id not in b_ids


def test_random_in_library_excludes_id(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib = db.add_library("A", "generic")
    ids = _insert_files(db, lib, ["a.mkv", "b.mkv"])
    for _ in range(20):
        row = db.random_file_in_library(lib, exclude_id=ids[0])
        assert row is not None
        assert row.id == ids[1]


def test_random_in_library_returns_none_when_only_excluded_exists(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib = db.add_library("A", "generic")
    ids = _insert_files(db, lib, ["only.mkv"])
    assert db.random_file_in_library(lib, exclude_id=ids[0]) is None


def test_random_anywhere_can_return_from_any_library(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib_a = db.add_library("A", "generic")
    lib_b = db.add_library("B", "generic")
    _insert_files(db, lib_a, ["a1.mkv"], parent_dir="/a")
    _insert_files(db, lib_b, ["b1.mkv"], parent_dir="/b")
    seen = set()
    for _ in range(100):
        row = db.random_file_anywhere()
        assert row is not None
        seen.add(row.library_id)
    assert seen == {lib_a, lib_b}


def test_random_anywhere_excludes_id(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib = db.add_library("A", "generic")
    ids = _insert_files(db, lib, ["a.mkv", "b.mkv"])
    for _ in range(20):
        row = db.random_file_anywhere(exclude_id=ids[0])
        assert row is not None
        assert row.id == ids[1]


def test_random_anywhere_skips_orphan_files(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib = db.add_library("A", "generic")
    _insert_files(db, lib, ["good.mkv"])
    conn = sqlite3.connect(str(db.db_path))
    conn.execute(
        """INSERT INTO files(library_id, path, parent_dir, filename, ext,
                             size, mtime, last_seen)
           VALUES (NULL, '/orphan/x.mkv', '/orphan', 'x.mkv', '.mkv', 0, 0, 0)""",
    )
    conn.commit()
    conn.close()
    for _ in range(20):
        row = db.random_file_anywhere()
        assert row is not None
        assert row.library_id == lib
        assert row.filename == "good.mkv"
