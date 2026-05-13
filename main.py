"""
vlc-library — a library/queue-forward video player with embedded VLC playback.

Skeleton intended to be extended (in Claude Code or elsewhere). Run with:
    python main.py

First launch: use the "Scan Folder…" button to pick a root directory.
Files are indexed into ~/.local/share/vlc-library/library.db (SQLite + FTS5).

Dependencies (system):
    sudo pacman -S vlc python-pyqt6      # Arch / KDE
    # or: sudo apt install vlc python3-pyqt6
Dependencies (pip):
    pip install python-vlc PyQt6

Architecture:
    - LibraryDB   : SQLite (with FTS5) wrapper. Files + watch_state + folder cache.
    - Scanner     : QThread that walks the filesystem with os.scandir, batches inserts.
    - VlcWidget   : QFrame whose winId() is given to libVLC for native rendering.
    - Queue       : in-memory list with model/view; persisted to DB on change.
    - MainWindow  : library tree (folders) + search results table + queue panel + player.
"""

from __future__ import annotations

import os
import sys
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QModelIndex, QSize, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTreeView, QTableView, QListView, QFrame,
    QFileDialog, QToolBar, QStatusBar, QSlider, QMessageBox, QAbstractItemView,
    QHeaderView, QStyle, QMenu,
)

from vlc_ranger.player import VlcWidget

# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------

APP_NAME = "vlc-library"
VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".vob", ".ogv", ".3gp",
}
AUDIO_EXTS = {".mp3", ".flac", ".opus", ".ogg", ".m4a", ".wav", ".aac", ".wma"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

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


@dataclass
class FileRow:
    id: int
    path: str
    parent_dir: str
    filename: str
    ext: str
    size: int
    mtime: int
    duration: Optional[float]


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


# ---------------------------------------------------------------------------
# Scanner (background thread)
# ---------------------------------------------------------------------------

class Scanner(QThread):
    progress = pyqtSignal(int, str)  # count, current_dir
    finished_scan = pyqtSignal(int)  # total files

    def __init__(self, db_path: Path, root: str, batch_size: int = 500):
        super().__init__()
        self.db_path = db_path
        self.root = root
        self.batch_size = batch_size
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        # New connection — sqlite objects can't cross threads.
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        scan_started = int(time.time())
        batch: list[tuple] = []
        total = 0

        def flush():
            nonlocal batch
            if not batch:
                return
            conn.executemany(
                """INSERT INTO files(path, parent_dir, filename, ext, size, mtime, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                       size=excluded.size, mtime=excluded.mtime, last_seen=excluded.last_seen""",
                batch,
            )
            conn.commit()
            batch = []

        stack = [self.root]
        while stack and not self._cancel:
            current = stack.pop()
            self.progress.emit(total, current)
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if self._cancel:
                            break
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                ext = os.path.splitext(entry.name)[1].lower()
                                if ext in MEDIA_EXTS:
                                    st = entry.stat()
                                    batch.append((
                                        entry.path, current, entry.name, ext,
                                        st.st_size, int(st.st_mtime), scan_started,
                                    ))
                                    total += 1
                                    if len(batch) >= self.batch_size:
                                        flush()
                        except OSError:
                            continue
            except (PermissionError, FileNotFoundError):
                continue

        flush()
        # purge files under this root that weren't seen this scan
        like = self.root.rstrip("/") + "/%"
        conn.execute("DELETE FROM files WHERE last_seen < ? AND path LIKE ?",
                     (scan_started, like))
        conn.commit()
        conn.close()
        self.finished_scan.emit(total)


# ---------------------------------------------------------------------------
# Queue model
# ---------------------------------------------------------------------------

class QueueModel(QStandardItemModel):
    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(["#", "File"])
        self._files: list[FileRow] = []

    def files(self) -> list[FileRow]:
        return list(self._files)

    def append(self, files: list[FileRow]):
        for f in files:
            self._files.append(f)
            self._append_row(len(self._files), f)

    def prepend(self, files: list[FileRow]):
        for i, f in enumerate(files):
            self._files.insert(i, f)
        self._rebuild()

    def insert_after_current(self, files: list[FileRow], current_index: int):
        for i, f in enumerate(files):
            self._files.insert(current_index + 1 + i, f)
        self._rebuild()

    def clear_queue(self):
        self._files.clear()
        self.setRowCount(0)

    def remove_indices(self, rows: list[int]):
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self._files):
                del self._files[r]
        self._rebuild()

    def take_next(self) -> Optional[FileRow]:
        if not self._files:
            return None
        f = self._files.pop(0)
        self._rebuild()
        return f

    def _append_row(self, n: int, f: FileRow):
        self.appendRow([QStandardItem(str(n)), QStandardItem(f.filename)])

    def _rebuild(self):
        self.setRowCount(0)
        for i, f in enumerate(self._files, 1):
            self._append_row(i, f)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("vlc-library")
        self.resize(1400, 850)
        self.db = LibraryDB(data_dir() / "library.db")
        self.scanner: Optional[Scanner] = None
        self.current_file: Optional[FileRow] = None

        self._build_ui()
        self._build_toolbar()
        self._restore_state()

        # Tick for transport slider + auto-advance
        self.tick = QTimer(self)
        self.tick.setInterval(500)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()

    # UI -------------------------------------------------------------------
    def _build_ui(self):
        # left: folder tree (top) + search results (middle) + queue (bottom)
        # right: video + transport
        self.folder_tree = QTreeView()
        self.folder_model = QStandardItemModel()
        self.folder_model.setHorizontalHeaderLabels(["Library"])
        self.folder_tree.setModel(self.folder_model)
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.expanded.connect(self._on_folder_expand)
        self.folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self._folder_menu)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search (FTS5: 'breaking bad', 'mkv*', etc.)")
        self.search_box.textChanged.connect(self._on_search)

        self.results = QTableView()
        self.results_model = QStandardItemModel()
        self.results_model.setHorizontalHeaderLabels(["Filename", "Folder"])
        self.results.setModel(self.results_model)
        self.results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.doubleClicked.connect(self._play_selected_result)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self._results_menu)

        self.queue_model = QueueModel()
        self.queue_view = QTableView()
        self.queue_view.setModel(self.queue_model)
        self.queue_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.queue_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue_view.doubleClicked.connect(self._jump_queue)
        self.queue_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_view.customContextMenuRequested.connect(self._queue_menu)

        queue_buttons = QHBoxLayout()
        for label, slot in [
            ("▶ Play next", self._play_next_from_queue),
            ("Clear", self._clear_queue),
            ("Remove", self._remove_selected_queue),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            queue_buttons.addWidget(b)

        queue_box = QWidget()
        ql = QVBoxLayout(queue_box)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(QLabel("Queue"))
        ql.addWidget(self.queue_view)
        ql.addLayout(queue_buttons)

        left_split = QSplitter(Qt.Orientation.Vertical)
        # results pane wraps search box + table
        results_wrap = QWidget()
        rl = QVBoxLayout(results_wrap)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.search_box)
        rl.addWidget(self.results)
        left_split.addWidget(self.folder_tree)
        left_split.addWidget(results_wrap)
        left_split.addWidget(queue_box)
        left_split.setSizes([250, 350, 250])

        # right: video + transport
        self.video = VlcWidget()
        self.transport = QSlider(Qt.Orientation.Horizontal)
        self.transport.setRange(0, 1000)
        self.transport.sliderMoved.connect(lambda v: self.video.set_position(v / 1000.0))
        self.now_playing = QLabel("Nothing playing")

        controls = QHBoxLayout()
        for icon, slot in [
            (QStyle.StandardPixmap.SP_MediaPlay, self._toggle_pause),
            (QStyle.StandardPixmap.SP_MediaStop, self.video.stop),
            (QStyle.StandardPixmap.SP_MediaSkipForward, self._play_next_from_queue),
        ]:
            b = QPushButton()
            b.setIcon(self.style().standardIcon(icon))
            b.clicked.connect(slot)
            controls.addWidget(b)
        controls.addWidget(self.transport, 1)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.addWidget(self.video, 1)
        rlay.addWidget(self.now_playing)
        rlay.addLayout(controls)

        root_split = QSplitter(Qt.Orientation.Horizontal)
        root_split.addWidget(left_split)
        root_split.addWidget(right)
        root_split.setSizes([450, 950])
        self.setCentralWidget(root_split)
        self.setStatusBar(QStatusBar())

    def _build_toolbar(self):
        tb = QToolBar()
        self.addToolBar(tb)
        act_scan = QAction("Scan Folder…", self)
        act_scan.triggered.connect(self._scan_folder)
        tb.addAction(act_scan)

        act_rescan = QAction("Rescan All", self)
        act_rescan.triggered.connect(self._rescan_all)
        tb.addAction(act_rescan)

    # First-load --------------------------------------------------------
    def _restore_state(self):
        # rebuild folder tree from indexed roots
        roots = self.db.list_roots()
        for r in roots:
            self._add_root_node(r)
        # restore persisted queue
        self.queue_model.append(self.db.load_queue())

    def _add_root_node(self, path: str):
        item = QStandardItem(path)
        item.setData(path, Qt.ItemDataRole.UserRole)
        # placeholder child so the expand arrow appears
        item.appendRow(QStandardItem("(loading)"))
        self.folder_model.appendRow(item)

    def _on_folder_expand(self, idx: QModelIndex):
        item = self.folder_model.itemFromIndex(idx)
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        # Replace children only if first child is placeholder.
        if item.rowCount() == 1 and item.child(0).text() == "(loading)":
            item.removeRows(0, 1)
            for child in self.db.child_dirs(path):
                ch = QStandardItem(os.path.basename(child) or child)
                ch.setData(child, Qt.ItemDataRole.UserRole)
                ch.appendRow(QStandardItem("(loading)"))
                item.appendRow(ch)
        # Also populate results pane with this folder's files (recursive).
        self._fill_results(self.db.files_under(path, recursive=True))

    def _fill_results(self, files: list[FileRow]):
        self.results_model.setRowCount(0)
        for f in files:
            row = [QStandardItem(f.filename), QStandardItem(f.parent_dir)]
            for it in row:
                it.setData(f.id, Qt.ItemDataRole.UserRole)
            self.results_model.appendRow(row)
        self.statusBar().showMessage(f"{len(files)} file(s)")

    def _on_search(self, text: str):
        if not text.strip():
            self.results_model.setRowCount(0)
            return
        self._fill_results(self.db.search(text))

    # Scanning ----------------------------------------------------------
    def _scan_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Pick a root to index")
        if not path:
            return
        self.db.add_root(path)
        if not any(self.folder_model.item(i).text() == path
                   for i in range(self.folder_model.rowCount())):
            self._add_root_node(path)
        self._start_scan(path)

    def _rescan_all(self):
        for root in self.db.list_roots():
            self._start_scan(root)

    def _start_scan(self, root: str):
        if self.scanner and self.scanner.isRunning():
            QMessageBox.information(self, "Busy", "A scan is already running.")
            return
        self.scanner = Scanner(self.db.db_path, root)
        self.scanner.progress.connect(
            lambda n, d: self.statusBar().showMessage(f"Scanning {n}: {d}")
        )
        self.scanner.finished_scan.connect(
            lambda total: self.statusBar().showMessage(f"Indexed {total} file(s) under {root}")
        )
        self.scanner.start()

    # Selection helpers -------------------------------------------------
    def _selected_result_rows(self) -> list[FileRow]:
        ids = []
        for idx in self.results.selectionModel().selectedRows():
            ids.append(self.results_model.item(idx.row(), 0).data(Qt.ItemDataRole.UserRole))
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql = f"""SELECT id, path, parent_dir, filename, ext, size, mtime, duration
                  FROM files WHERE id IN ({placeholders})"""
        return [FileRow(*r) for r in self.db.conn.execute(sql, ids)]

    # Queue ops --------------------------------------------------------
    def _add_to_queue_end(self, files: list[FileRow]):
        self.queue_model.append(files)
        self._persist_queue()

    def _add_to_queue_front(self, files: list[FileRow]):
        self.queue_model.prepend(files)
        self._persist_queue()

    def _play_next(self, files: list[FileRow]):
        # insert right after the currently-playing index (top of queue is 0)
        self.queue_model.insert_after_current(files, -1)  # -1 => insert at position 0
        self._persist_queue()

    def _persist_queue(self):
        self.db.save_queue([f.id for f in self.queue_model.files()])

    def _clear_queue(self):
        self.queue_model.clear_queue()
        self._persist_queue()

    def _remove_selected_queue(self):
        rows = [i.row() for i in self.queue_view.selectionModel().selectedRows()]
        self.queue_model.remove_indices(rows)
        self._persist_queue()

    def _play_next_from_queue(self):
        f = self.queue_model.take_next()
        self._persist_queue()
        if f:
            self._play(f)

    def _jump_queue(self, idx: QModelIndex):
        # play the double-clicked queue item, remove items above it
        row = idx.row()
        # drop all items 0..row inclusive, then prepend the chosen one back? simpler: pop until we reach it
        for _ in range(row):
            self.queue_model.take_next()
        f = self.queue_model.take_next()
        self._persist_queue()
        if f:
            self._play(f)

    # Context menus ----------------------------------------------------
    def _results_menu(self, point):
        files = self._selected_result_rows()
        if not files:
            return
        menu = QMenu(self)
        menu.addAction("▶ Play now", lambda: self._play(files[0]))
        menu.addAction("Add to end of queue",   lambda: self._add_to_queue_end(files))
        menu.addAction("Add to front of queue", lambda: self._add_to_queue_front(files))
        menu.addAction("Play next",             lambda: self._play_next(files))
        menu.exec(self.results.viewport().mapToGlobal(point))

    def _folder_menu(self, point):
        idx = self.folder_tree.indexAt(point)
        if not idx.isValid():
            return
        item = self.folder_model.itemFromIndex(idx)
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        files = self.db.files_under(path, recursive=True)
        if not files:
            return
        menu = QMenu(self)
        menu.addAction(f"Queue folder ({len(files)} files) — end",
                       lambda: self._add_to_queue_end(files))
        menu.addAction("Queue folder — front",
                       lambda: self._add_to_queue_front(files))
        menu.addAction("Play folder now (replaces queue)",
                       lambda: self._play_folder(files))
        menu.exec(self.folder_tree.viewport().mapToGlobal(point))

    def _queue_menu(self, point):
        menu = QMenu(self)
        menu.addAction("Remove", self._remove_selected_queue)
        menu.addAction("Clear queue", self._clear_queue)
        menu.exec(self.queue_view.viewport().mapToGlobal(point))

    def _play_folder(self, files: list[FileRow]):
        self.queue_model.clear_queue()
        self.queue_model.append(files)
        self._persist_queue()
        self._play_next_from_queue()

    def _play_selected_result(self, idx: QModelIndex):
        files = self._selected_result_rows()
        if files:
            self._play(files[0])

    # Playback ---------------------------------------------------------
    def _play(self, f: FileRow):
        # ensure VLC is bound to the now-shown video widget
        self.video.attach()
        self.video.play_path(f.path)
        self.current_file = f
        self.now_playing.setText(f"▶ {f.filename}  —  {f.parent_dir}")

    def _toggle_pause(self):
        self.video.toggle_pause()

    def _on_tick(self):
        # update transport slider
        pos = self.video.position()
        if not self.transport.isSliderDown():
            self.transport.setValue(int(pos * 1000))
        # auto-advance when current ends
        if self.current_file and self.video.is_ended():
            self.current_file = None
            self._play_next_from_queue()

    # cleanup ----------------------------------------------------------
    def closeEvent(self, ev):
        self.video.stop()
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(2000)
        super().closeEvent(ev)


# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    # winId() is valid now — bind libVLC's output to the video widget.
    w.video.attach()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
