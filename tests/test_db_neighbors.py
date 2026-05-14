import os
import sqlite3
import tempfile

import pytest

from vlc_ranger.db import LibraryDB


@pytest.fixture
def db_with_files(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib_id = db.add_library("Test", "generic")
    db.add_library_folder(lib_id, "/m")
    # Insert three files in /m alphabetical: a.mkv, b.mkv, c.mkv
    conn = sqlite3.connect(str(db.db_path))
    for name in ("a.mkv", "b.mkv", "c.mkv"):
        conn.execute(
            """INSERT INTO files(library_id, path, parent_dir, filename, ext,
                                 size, mtime, last_seen)
               VALUES (?, ?, ?, ?, ?, 0, 0, 0)""",
            (lib_id, f"/m/{name}", "/m", name, ".mkv"),
        )
    conn.commit()
    conn.close()
    return db, lib_id


def test_next_in_middle(db_with_files):
    db, lib_id = db_with_files
    row = db.next_file_in_folder(lib_id, "/m", "b.mkv")
    assert row is not None
    assert row.filename == "c.mkv"


def test_next_at_end_returns_none(db_with_files):
    db, lib_id = db_with_files
    assert db.next_file_in_folder(lib_id, "/m", "c.mkv") is None


def test_prev_in_middle(db_with_files):
    db, lib_id = db_with_files
    row = db.prev_file_in_folder(lib_id, "/m", "b.mkv")
    assert row is not None
    assert row.filename == "a.mkv"


def test_prev_at_start_returns_none(db_with_files):
    db, lib_id = db_with_files
    assert db.prev_file_in_folder(lib_id, "/m", "a.mkv") is None


def test_next_scoped_to_library(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    lib_a = db.add_library("A", "generic")
    lib_b = db.add_library("B", "generic")
    conn = sqlite3.connect(str(db.db_path))
    for lib, name in [(lib_a, "a.mkv"), (lib_a, "b.mkv"), (lib_b, "z.mkv")]:
        conn.execute(
            """INSERT INTO files(library_id, path, parent_dir, filename, ext,
                                 size, mtime, last_seen)
               VALUES (?, ?, ?, ?, ?, 0, 0, 0)""",
            (lib, f"/{lib}/{name}", f"/{lib}", name, ".mkv"),
        )
    conn.commit()
    conn.close()
    # next after b.mkv in lib_a (parent /1) is None; the z.mkv in lib_b is not visible.
    assert db.next_file_in_folder(lib_a, f"/{lib_a}", "b.mkv") is None
