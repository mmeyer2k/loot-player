from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QMenu, QTableView, QVBoxLayout, QWidget,
)

from vlc_ranger.models import FileRow


class GenericView(QWidget):
    play_requested = pyqtSignal(object)        # FileRow
    queue_end_requested = pyqtSignal(list)
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = QTableView()
        self.model = QStandardItemModel()
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.doubleClicked.connect(self._double)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self._rows: list[FileRow] = []
        self._mode_search = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        self._set_headers(False)

    def _set_headers(self, search_mode: bool):
        self._mode_search = search_mode
        if search_mode:
            self.model.setHorizontalHeaderLabels(["Filename", "Folder", "Library"])
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        else:
            self.model.setHorizontalHeaderLabels(["Filename", "Folder"])

    def set_rows(self, rows: list[FileRow]):
        self._set_headers(False)
        self._rows = rows
        self.model.setRowCount(0)
        for f in rows:
            self.model.appendRow([QStandardItem(f.filename), QStandardItem(f.parent_dir)])

    def set_search_rows(self, rows: list[tuple[FileRow, str]]):
        self._set_headers(True)
        self._rows = [r[0] for r in rows]
        self.model.setRowCount(0)
        for f, libname in rows:
            self.model.appendRow([
                QStandardItem(f.filename),
                QStandardItem(f.parent_dir),
                QStandardItem(libname),
            ])

    def _double(self, idx):
        if 0 <= idx.row() < len(self._rows):
            self.play_requested.emit(self._rows[idx.row()])

    def _selected(self) -> list[FileRow]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self._rows[r] for r in rows if 0 <= r < len(self._rows)]

    def _menu(self, point):
        sel = self._selected()
        if not sel:
            return
        m = QMenu(self)
        m.addAction("▶ Play now",        lambda: self.play_requested.emit(sel[0]))
        m.addAction("Queue (end)",       lambda: self.queue_end_requested.emit(sel))
        m.addAction("Queue (front)",     lambda: self.queue_front_requested.emit(sel))
        m.addAction("Play next",         lambda: self.play_next_requested.emit(sel))
        m.exec(self.table.viewport().mapToGlobal(point))
