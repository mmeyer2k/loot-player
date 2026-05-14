from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QSortFilterProxyModel, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QLineEdit, QMenu, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow


_TYPE_PREFIX = {"movies": "[M] ", "tv": "[T] ", "music": "[♪] ", "generic": "[G] "}


class LibraryTree(QWidget):
    play_requested = pyqtSignal(object)        # FileRow
    queue_end_requested = pyqtSignal(list)     # list[FileRow]
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)
    new_library_requested = pyqtSignal()
    edit_library_requested = pyqtSignal(int)
    rescan_library_requested = pyqtSignal(int)
    delete_library_requested = pyqtSignal(int)

    def __init__(self, db: LibraryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self._files_by_id: dict[int, FileRow] = {}

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self._on_search)

        self.model = QStandardItemModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.doubleClicked.connect(self._double)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)

        new_btn = QPushButton("+ New Library…")
        new_btn.clicked.connect(self.new_library_requested.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addWidget(new_btn)

        self.reload()

    # building -----------------------------------------------------------
    def reload(self):
        """Rebuild the entire tree from the DB."""
        self.model.clear()
        self._files_by_id.clear()
        for lib_id, name, type_ in self.db.list_libraries():
            self._build_library(lib_id, name, type_)

    def _build_library(self, lib_id: int, name: str, type_: str):
        prefix = _TYPE_PREFIX.get(type_, "")
        lib_item = QStandardItem(f"{prefix}{name}")
        lib_item.setData(("library", lib_id), Qt.ItemDataRole.UserRole)
        lib_item.setEditable(False)
        self.model.appendRow(lib_item)
        # ... build folder/file structure first, then collapse single chains.
        self._build_library_tree(lib_id, lib_item)
        self._collapse_chains(lib_item)

    def _build_library_tree(self, lib_id: int, lib_item: QStandardItem):

        folders = [p for (_, p) in self.db.library_folders(lib_id)]
        files = self.db.files_in_library(lib_id)
        for f in files:
            self._files_by_id[f.id] = f

        # Top folder nodes (the library_folders themselves) — basename label, full path data.
        folder_items: dict[str, QStandardItem] = {}
        for folder in folders:
            label = os.path.basename(folder.rstrip("/")) or folder
            item = QStandardItem(label)
            item.setData(("dir", lib_id, folder), Qt.ItemDataRole.UserRole)
            item.setToolTip(folder)
            item.setEditable(False)
            lib_item.appendRow(item)
            folder_items[folder] = item

        def get_or_create_subdir(parent_dir: str) -> QStandardItem | None:
            """Return the QStandardItem for a parent_dir, creating missing
            intermediate folder nodes as needed."""
            if parent_dir in folder_items:
                return folder_items[parent_dir]
            # Find the deepest library_folder that contains this parent_dir.
            best = None
            for folder in folders:
                if parent_dir == folder or parent_dir.startswith(folder + "/"):
                    if best is None or len(folder) > len(best):
                        best = folder
            if best is None:
                return None
            rel = parent_dir[len(best):].lstrip("/")
            parts = rel.split("/") if rel else []
            cur_item = folder_items[best]
            cur_path = best
            for part in parts:
                cur_path = cur_path + "/" + part
                if cur_path in folder_items:
                    cur_item = folder_items[cur_path]
                    continue
                new = QStandardItem(part)
                new.setData(("dir", lib_id, cur_path), Qt.ItemDataRole.UserRole)
                new.setToolTip(cur_path)
                new.setEditable(False)
                cur_item.appendRow(new)
                folder_items[cur_path] = new
                cur_item = new
            return cur_item

        # First pass: ensure every parent_dir has a folder node, so folders
        # appear before files within each level.
        for parent in sorted({f.parent_dir for f in files}):
            get_or_create_subdir(parent)

        # Second pass: attach files.
        for f in sorted(files, key=lambda r: r.filename.lower()):
            parent_item = get_or_create_subdir(f.parent_dir)
            if parent_item is None:
                continue
            file_item = QStandardItem(f.filename)
            file_item.setData(("file", f.id), Qt.ItemDataRole.UserRole)
            file_item.setEditable(False)
            parent_item.appendRow(file_item)

    def _collapse_chains(self, node: QStandardItem):
        """Post-order: merge any 'dir' node whose only child is another 'dir'
        into a single compound node ('parent/child'). Library nodes and any
        folder that has files or multiple children are left alone."""
        for r in range(node.rowCount()):
            self._collapse_chains(node.child(r))

        data = node.data(Qt.ItemDataRole.UserRole)
        if not data or data[0] != "dir":
            return

        while node.rowCount() == 1:
            child = node.child(0)
            child_data = child.data(Qt.ItemDataRole.UserRole)
            if not child_data or child_data[0] != "dir":
                break
            # Take the child's grandchildren before destroying child.
            grandchildren = []
            while child.rowCount() > 0:
                grandchildren.append(child.takeRow(0))
            node.setText(f"{node.text()}/{child.text()}")
            node.setData(child_data, Qt.ItemDataRole.UserRole)
            node.setToolTip(child.toolTip())
            node.removeRow(0)
            for row in grandchildren:
                node.appendRow(row)

    # search -------------------------------------------------------------
    def _on_search(self, text: str):
        self.proxy.setFilterFixedString(text.strip())
        if text.strip():
            self.tree.expandAll()

    # interaction --------------------------------------------------------
    def _resolve(self, proxy_idx) -> tuple:
        src = self.proxy.mapToSource(proxy_idx)
        item = self.model.itemFromIndex(src)
        return item, item.data(Qt.ItemDataRole.UserRole) if item else (None, None)

    def _files_under_item(self, item: QStandardItem) -> list[FileRow]:
        """Walk the subtree under `item` collecting all file rows in tree order."""
        out: list[FileRow] = []
        stack = [item]
        # Reverse so we pop in insertion order
        result: list[FileRow] = []

        def walk(node: QStandardItem):
            data = node.data(Qt.ItemDataRole.UserRole)
            if data and data[0] == "file":
                file_row = self._files_by_id.get(data[1])
                if file_row is not None:
                    result.append(file_row)
            for r in range(node.rowCount()):
                walk(node.child(r))

        walk(item)
        return result

    def _double(self, proxy_idx):
        item, data = self._resolve(proxy_idx)
        if not data:
            return
        kind = data[0]
        if kind == "file":
            file_row = self._files_by_id.get(data[1])
            if file_row is not None:
                self.play_requested.emit(file_row)

    def _menu(self, point):
        proxy_idx = self.tree.indexAt(point)
        if not proxy_idx.isValid():
            return
        item, data = self._resolve(proxy_idx)
        if not data:
            return
        kind = data[0]
        m = QMenu(self)
        if kind == "file":
            file_row = self._files_by_id.get(data[1])
            if file_row is None:
                return
            files = [file_row]
            m.addAction("▶ Play now",     lambda: self.play_requested.emit(file_row))
            m.addAction("Queue (end)",    lambda: self.queue_end_requested.emit(files))
            m.addAction("Queue (front)",  lambda: self.queue_front_requested.emit(files))
            m.addAction("Play next",      lambda: self.play_next_requested.emit(files))
        elif kind == "dir":
            files = self._files_under_item(item)
            if not files:
                return
            m.addAction(f"▶ Play all ({len(files)})",
                        lambda: (self.queue_front_requested.emit(files[1:]),
                                 self.play_requested.emit(files[0])))
            m.addAction("Queue all (end)",
                        lambda: self.queue_end_requested.emit(files))
            m.addAction("Queue all (front)",
                        lambda: self.queue_front_requested.emit(files))
        elif kind == "library":
            lib_id = data[1]
            m.addAction("Edit…",   lambda: self.edit_library_requested.emit(lib_id))
            m.addAction("Rescan",  lambda: self.rescan_library_requested.emit(lib_id))
            m.addSeparator()
            m.addAction("Delete",  lambda: self.delete_library_requested.emit(lib_id))
        else:
            return
        m.exec(self.tree.viewport().mapToGlobal(point))
