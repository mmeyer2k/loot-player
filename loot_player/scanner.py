from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from loot_player.matching import parse


VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".vob", ".ogv", ".3gp",
}
AUDIO_EXTS = {".mp3", ".flac", ".opus", ".ogg", ".m4a", ".wav", ".aac", ".wma"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


class Scanner(QThread):
    progress = pyqtSignal(int, str)
    finished_scan = pyqtSignal(int)

    def __init__(self, db_path: Path, library_id: int, library_type: str,
                 folders: list[str], batch_size: int = 500):
        super().__init__()
        self.db_path = db_path
        self.library_id = library_id
        self.library_type = library_type
        self.folders = folders
        self.batch_size = batch_size
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
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
                """INSERT INTO files(library_id, path, parent_dir, filename, ext, size,
                                     mtime, last_seen, title, year, series, season,
                                     episode, artist, album, track)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                       library_id=excluded.library_id,
                       size=excluded.size, mtime=excluded.mtime, last_seen=excluded.last_seen,
                       title=excluded.title, year=excluded.year,
                       series=excluded.series, season=excluded.season, episode=excluded.episode,
                       artist=excluded.artist, album=excluded.album, track=excluded.track""",
                batch,
            )
            conn.commit()
            batch = []

        for folder in self.folders:
            if self._cancel:
                break
            stack = [folder]
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
                                        parsed = parse(self.library_type, entry.name, current)
                                        batch.append((
                                            self.library_id, entry.path, current,
                                            entry.name, ext, st.st_size,
                                            int(st.st_mtime), scan_started,
                                            parsed.get("title"), parsed.get("year"),
                                            parsed.get("series"), parsed.get("season"),
                                            parsed.get("episode"),
                                            parsed.get("artist"), parsed.get("album"),
                                            parsed.get("track"),
                                        ))
                                        total += 1
                                        if len(batch) >= self.batch_size:
                                            flush()
                            except OSError:
                                continue
                except (PermissionError, FileNotFoundError):
                    continue

        flush()

        # purge: delete files under this library's folders that weren't seen this scan
        for folder in self.folders:
            like = folder.rstrip("/") + "/%"
            conn.execute(
                "DELETE FROM files WHERE library_id=? AND last_seen<? AND path LIKE ?",
                (self.library_id, scan_started, like),
            )
        conn.commit()
        conn.close()
        self.finished_scan.emit(total)
