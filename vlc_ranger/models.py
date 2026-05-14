from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

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

    def take_random(self) -> Optional[FileRow]:
        """Pop and return a random file from the queue, or None if empty."""
        import random
        if not self._files:
            return None
        idx = random.randrange(len(self._files))
        f = self._files.pop(idx)
        self._rebuild()
        return f

    def _append_row(self, n: int, f: FileRow):
        self.appendRow([QStandardItem(str(n)), QStandardItem(f.filename)])

    def _rebuild(self):
        self.setRowCount(0)
        for i, f in enumerate(self._files, 1):
            self._append_row(i, f)
