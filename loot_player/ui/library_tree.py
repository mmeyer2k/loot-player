from __future__ import annotations

import os

import qtawesome as qta
from PyQt6.QtCore import Qt, QSortFilterProxyModel, QTimer, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QLineEdit, QMenu, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from loot_player.db import LibraryDB
from loot_player.models import FileRow




class LibraryTree(QWidget):
    play_requested = pyqtSignal(object)        # FileRow
    queue_front_requested = pyqtSignal(list)   # used internally for "Play all"
    play_next_requested = pyqtSignal(list)
    new_library_requested = pyqtSignal()
    edit_library_requested = pyqtSignal(int)
    rescan_library_requested = pyqtSignal(int)
    delete_library_requested = pyqtSignal(int)

    def __init__(self, db: LibraryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self._files_by_id: dict[int, FileRow] = {}
        self._items_by_id: dict[int, QStandardItem] = {}
        self._playing_id: int | None = None

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self._on_search)
        self._clear_action = self.search.addAction(
            qta.icon("mdi6.close"),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self._clear_action.setVisible(False)
        self._clear_action.triggered.connect(self.search.clear)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_search)

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
        saved_playing = self._playing_id
        self.model.clear()
        self._files_by_id.clear()
        self._items_by_id.clear()
        self._playing_id = None
        for lib_id, name, type_ in self.db.list_libraries():
            self._build_library(lib_id, name, type_)
        if saved_playing is not None:
            self.set_playing(saved_playing)

    def _build_library(self, lib_id: int, name: str, type_: str):
        lib_item = QStandardItem(name)
        lib_item.setData(("library", lib_id), Qt.ItemDataRole.UserRole)
        lib_item.setEditable(False)
        self.model.appendRow(lib_item)
        # ... build folder/file structure first, then collapse single chains.
        self._build_library_tree(lib_id, lib_item)
        self._collapse_chains(lib_item)
        # If the library has exactly one library_folder, that folder is
        # redundant noise — hoist its children directly under the library.
        if lib_item.rowCount() == 1:
            only = lib_item.child(0)
            only_data = only.data(Qt.ItemDataRole.UserRole)
            if only_data and only_data[0] == "dir":
                grandchildren = []
                while only.rowCount() > 0:
                    grandchildren.append(only.takeRow(0))
                lib_item.removeRow(0)
                for row in grandchildren:
                    lib_item.appendRow(row)

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
            self._items_by_id[f.id] = file_item
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

    # currently-playing highlight ---------------------------------------
    def set_playing(self, file_id: int | None):
        """Bold the tree row for the file currently being played; unbold
        whichever row was previously bolded. Pass None when nothing plays."""
        if self._playing_id is not None:
            prev = self._items_by_id.get(self._playing_id)
            if prev is not None:
                font = prev.font()
                font.setBold(False)
                prev.setFont(font)
        self._playing_id = file_id
        if file_id is None:
            return
        item = self._items_by_id.get(file_id)
        if item is not None:
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    # search -------------------------------------------------------------
    def _on_search(self, text: str):
        # Debounce: 1-char queries match too much to be useful and the
        # recursive filter pass is expensive on large libraries. Clearing
        # the field applies immediately so the tree restores without lag.
        self._clear_action.setVisible(bool(text))
        if not text.strip():
            self._search_timer.stop()
            self._apply_search()
            return
        self._search_timer.start()

    def _apply_search(self):
        text = self.search.text().strip()
        if len(text) == 1:
            return
        self.proxy.setFilterFixedString(text)
        if text:
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
            m.addAction("Play next",      lambda: self.play_next_requested.emit(files))
        elif kind == "dir":
            files = self._files_under_item(item)
            if not files:
                return
            m.addAction(f"▶ Play all ({len(files)})",
                        lambda: (self.queue_front_requested.emit(files[1:]),
                                 self.play_requested.emit(files[0])))
            m.addAction(f"Play next ({len(files)})",
                        lambda: self.play_next_requested.emit(files))
        elif kind == "library":
            lib_id = data[1]
            m.addAction("Edit…",   lambda: self.edit_library_requested.emit(lib_id))
            m.addAction("Rescan",  lambda: self.rescan_library_requested.emit(lib_id))
            m.addSeparator()
            m.addAction("Delete",  lambda: self.delete_library_requested.emit(lib_id))
        else:
            return
        m.exec(self.tree.viewport().mapToGlobal(point))
