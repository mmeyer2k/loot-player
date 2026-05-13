from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QListView, QMenu, QPushButton, QVBoxLayout, QWidget


_TYPE_PREFIX = {"movies": "[M]", "tv": "[T]", "music": "[♪]", "generic": "[G]"}


class Sidebar(QWidget):
    library_selected = pyqtSignal(int)               # library_id
    new_library_requested = pyqtSignal()
    edit_library_requested = pyqtSignal(int)
    rescan_library_requested = pyqtSignal(int)
    delete_library_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.list = QListView()
        self.model = QStandardItemModel()
        self.list.setModel(self.model)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.clicked.connect(self._clicked)

        self.new_btn = QPushButton("+ New Library…")
        self.new_btn.clicked.connect(self.new_library_requested.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.new_btn)

    def reload(self, libraries: list[tuple[int, str, str]]):
        self.model.clear()
        for lib_id, name, type_ in libraries:
            item = QStandardItem(f"{_TYPE_PREFIX.get(type_, '[?]')} {name}")
            item.setData(lib_id, Qt.ItemDataRole.UserRole)
            self.model.appendRow(item)

    def _clicked(self, idx):
        lib_id = self.model.itemFromIndex(idx).data(Qt.ItemDataRole.UserRole)
        self.library_selected.emit(lib_id)

    def _menu(self, point):
        idx = self.list.indexAt(point)
        if not idx.isValid():
            return
        lib_id = self.model.itemFromIndex(idx).data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Edit…",      lambda: self.edit_library_requested.emit(lib_id))
        m.addAction("Rescan",     lambda: self.rescan_library_requested.emit(lib_id))
        m.addSeparator()
        m.addAction("Delete",     lambda: self.delete_library_requested.emit(lib_id))
        m.exec(self.list.viewport().mapToGlobal(point))
