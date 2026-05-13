from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QAction, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTreeView, QTableView,
    QFileDialog, QToolBar, QStatusBar, QSlider, QMessageBox, QAbstractItemView,
    QHeaderView, QStyle, QMenu,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow, QueueModel
from vlc_ranger.player import VlcWidget
from vlc_ranger.scanner import Scanner

APP_NAME = "vlc-ranger"
OLD_APP_NAME = "vlc-library"


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    new = base / APP_NAME
    old = base / OLD_APP_NAME
    if new.exists():
        return new
    if old.exists():
        os.rename(old, new)        # atomic on the same filesystem
        return new
    new.mkdir(parents=True, exist_ok=True)
    return new


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
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
        # Library-aware sidebar arrives in Task 14; folder tree stays empty for now.
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
    # NOTE: These three methods are TEMPORARY stubs. The real library-aware
    # scan UI ships in Task 14 alongside the new sidebar/editor dialog.
    def _scan_folder(self):
        QMessageBox.information(
            self, "Library editor needed",
            "Scan-by-library lands when the new sidebar UI ships (Tasks 12-14).",
        )

    def _rescan_all(self):
        QMessageBox.information(
            self, "Library editor needed",
            "Scan-by-library lands when the new sidebar UI ships (Tasks 12-14).",
        )

    def _start_scan(self, root: str):
        QMessageBox.information(
            self, "Library editor needed",
            "Scan-by-library lands when the new sidebar UI ships (Tasks 12-14).",
        )

    # Selection helpers -------------------------------------------------
    def _selected_result_rows(self) -> list[FileRow]:
        ids = []
        for idx in self.results.selectionModel().selectedRows():
            ids.append(self.results_model.item(idx.row(), 0).data(Qt.ItemDataRole.UserRole))
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql = f"""SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                         title, year, series, season, episode, artist, album, track
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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    # winId() is valid now — bind libVLC's output to the video widget.
    w.video.attach()
    sys.exit(app.exec())
