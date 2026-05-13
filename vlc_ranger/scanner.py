from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".vob", ".ogv", ".3gp",
}
AUDIO_EXTS = {".mp3", ".flac", ".opus", ".ogg", ".m4a", ".wav", ".aac", ".wma"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


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
