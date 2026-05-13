from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QListView, QMenu, QVBoxLayout, QWidget

from vlc_ranger.models import FileRow


class MoviesView(QWidget):
    play_requested = pyqtSignal(object)
    queue_end_requested = pyqtSignal(list)
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.list = QListView()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setGridSize(QSize(180, 110))
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.doubleClicked.connect(self._double)
        self.model = QStandardItemModel()
        self.list.setModel(self.model)

        self._rows: list[FileRow] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.list)

    def set_rows(self, rows: list[FileRow]):
        self._rows = sorted(rows, key=lambda f: ((f.title or f.filename).lower(), f.year or 0))
        self.model.clear()
        for f in self._rows:
            label = f.title or f.filename
            if f.year:
                label += f"\n({f.year})"
            item = QStandardItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setEditable(False)
            self.model.appendRow(item)

    def _double(self, idx):
        if 0 <= idx.row() < len(self._rows):
            self.play_requested.emit(self._rows[idx.row()])

    def _selected(self) -> list[FileRow]:
        rows = sorted({i.row() for i in self.list.selectionModel().selectedRows()})
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
        m.exec(self.list.viewport().mapToGlobal(point))
