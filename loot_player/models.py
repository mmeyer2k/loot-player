from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QMimeData, QModelIndex, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel


@dataclass
class FileRow:
    id: int
    library_id: Optional[int]
    path: str
    parent_dir: str
    filename: str
    ext: str
    size: int
    mtime: int
    duration: Optional[float]
    title: Optional[str] = None
    year: Optional[int] = None
    series: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    track: Optional[int] = None


class QueueModel(QStandardItemModel):
    MIME_ROWS = "application/x-loot-queue-rows"

    queue_reordered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(["File"])
        self._files: list[FileRow] = []

    def files(self) -> list[FileRow]:
        return list(self._files)

    # Drag-and-drop reorder --------------------------------------------
    def flags(self, index):
        f = super().flags(index)
        if index.isValid():
            return (f | Qt.ItemFlag.ItemIsDragEnabled) & ~Qt.ItemFlag.ItemIsDropEnabled
        return f | Qt.ItemFlag.ItemIsDropEnabled

    def mimeTypes(self):
        return [self.MIME_ROWS]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes if i.isValid()})
        data = QMimeData()
        data.setData(self.MIME_ROWS, ",".join(str(r) for r in rows).encode())
        return data

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(self.MIME_ROWS)

    def dropMimeData(self, data, action, row, column, parent):
        if action == Qt.DropAction.IgnoreAction:
            return True
        if not data.hasFormat(self.MIME_ROWS):
            return False
        payload = bytes(data.data(self.MIME_ROWS)).decode()
        if not payload:
            return False
        src_rows = sorted({int(r) for r in payload.split(",")})

        if parent.isValid():
            dest = parent.row()
        elif row >= 0:
            dest = row
        else:
            dest = len(self._files)

        moving = [self._files[r] for r in src_rows if 0 <= r < len(self._files)]
        if not moving:
            return False
        # Adjust dest for each source row removed from before it.
        dest -= sum(1 for r in src_rows if r < dest)
        for r in reversed(src_rows):
            if 0 <= r < len(self._files):
                del self._files[r]
        for i, f in enumerate(moving):
            self._files.insert(dest + i, f)
        self._rebuild()
        self.queue_reordered.emit()
        # Return False so Qt's view framework doesn't also try to remove the
        # source rows — we already moved them in-place.
        return False

    def append(self, files: list[FileRow]):
        for f in files:
            self._files.append(f)
            self._append_row(f)

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

    def take_random(self) -> Optional[FileRow]:
        """Pop and return a random file from the queue, or None if empty."""
        import random
        if not self._files:
            return None
        idx = random.randrange(len(self._files))
        f = self._files.pop(idx)
        self._rebuild()
        return f

    def _append_row(self, f: FileRow):
        self.appendRow([QStandardItem(f.filename)])

    def _rebuild(self):
        self.setRowCount(0)
        for f in self._files:
            self._append_row(f)
