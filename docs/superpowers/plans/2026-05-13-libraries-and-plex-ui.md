# Libraries & Plex-style UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat "roots" model with multi-folder, typed libraries (Movies / TV / Music / Generic), per-type browse views in a Plex-style three-column UI, and a `vlc_ranger/` package structure — while preserving the embedded VLC player, queue, scanner mechanics, and SQLite schema continuity.

**Architecture:** Split `main.py` into a `vlc_ranger/` package with `db`, `scanner`, `matching`, `player`, `models`, `app`, and `ui/` modules. Add `libraries` and `library_folders` tables; add `library_id` and parsed-structure columns to `files`. Pure-function filename parsers in `matching.py` run inside the scanner and are unit-tested with `pytest`. A `QStackedWidget`-based browse router swaps in per-type views.

**Tech Stack:** Python 3.14, PyQt6, libVLC via `python3-vlc`, SQLite + FTS5, pytest (newly introduced for `matching.py`).

**Phases & ordering:**
1. **Refactor** (Tasks 1–7) — package split, no behavior change. App keeps working end-to-end after each task.
2. **Schema + matching** (Tasks 8–11) — DB v1, migration, pure parsers, scanner uses them.
3. **UI** (Tasks 12–22) — sidebar, library editor, browse router, four per-type views, queue panel, hotkeys, persistence, global search.

Spec: [`docs/superpowers/specs/2026-05-13-libraries-and-plex-ui-design.md`](../specs/2026-05-13-libraries-and-plex-ui-design.md).

---

## File map

```
vlc-ranger/
├── main.py                        # 5-line entrypoint
├── vlc_ranger/
│   ├── __init__.py
│   ├── app.py                     # MainWindow, toolbar, hotkeys, splitters, wiring
│   ├── db.py                      # LibraryDB: SCHEMA, _migrate, all SQL
│   ├── scanner.py                 # Scanner QThread; per-library, calls matching
│   ├── matching.py                # parse_movie / parse_tv / parse_music / parse_generic
│   ├── player.py                  # VlcWidget + transport
│   ├── models.py                  # FileRow, Library dataclasses
│   └── ui/
│       ├── __init__.py
│       ├── sidebar.py             # library list + right-click menu + "+ New"
│       ├── browse.py              # QStackedWidget router + global search box
│       ├── queue_panel.py         # toggleable right-rail queue
│       ├── library_editor.py      # New/Edit library dialog
│       └── views/
│           ├── __init__.py
│           ├── generic.py         # flat sortable QTableView (port of current results)
│           ├── movies.py          # QListView icon-grid of title-cards
│           ├── tv.py              # internal stacked widget: shows -> seasons -> episodes
│           └── music.py           # artists -> albums -> tracks
├── tests/
│   ├── __init__.py
│   └── test_matching.py
└── docs/superpowers/...
```

A note on existing code: the current `main.py` is the only Python file. Each refactor task moves a coherent chunk into its new home and updates the entrypoint. After Task 7 the app should run and behave identically to today; Phase 2 starts adding features.

---

## Phase 1 — Refactor (no behavior change)

### Task 1: Initialize git repo + scaffold package directories

The repo is currently not a git repo. The plan relies on commits between tasks, so this is step 0.

**Files:**
- Create: `.gitignore`
- Create: `vlc_ranger/__init__.py` (empty)
- Create: `vlc_ranger/ui/__init__.py` (empty)
- Create: `vlc_ranger/ui/views/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Init the git repo**

```bash
cd /home/mike/Code/vlc-ranger
git init
git config user.email "m.meyer2k@gmail.com"
git config user.name "Mike"
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
```

- [ ] **Step 3: Create empty package dirs**

```bash
mkdir -p vlc_ranger/ui/views tests
touch vlc_ranger/__init__.py vlc_ranger/ui/__init__.py vlc_ranger/ui/views/__init__.py tests/__init__.py
```

- [ ] **Step 4: Commit the starting state plus scaffold**

```bash
git add .gitignore main.py README.md CLAUDE.md docs/ vlc_ranger/ tests/
git commit -m "chore: initial commit + package scaffold"
```

---

### Task 2: Move `VlcWidget` to `vlc_ranger/player.py`

**Files:**
- Create: `vlc_ranger/player.py`
- Modify: `main.py` (remove `VlcWidget` class, add `from vlc_ranger.player import VlcWidget`)

- [ ] **Step 1: Create `vlc_ranger/player.py`**

```python
from __future__ import annotations
import sys

import vlc
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QFrame


class VlcWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), Qt.GlobalColor.black)
        self.setPalette(pal)
        self.setMinimumSize(QSize(480, 270))

        self.instance = vlc.Instance(["--no-video-title-show", "--quiet"])
        self.player = self.instance.media_player_new()

    def attach(self):
        wid = int(self.winId())
        if sys.platform.startswith("linux"):
            self.player.set_xwindow(wid)
        elif sys.platform == "win32":
            self.player.set_hwnd(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)

    def play_path(self, path: str):
        media = self.instance.media_new(path)
        self.player.set_media(media)
        self.player.play()

    def toggle_pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()

    def set_position(self, frac: float):
        self.player.set_position(max(0.0, min(1.0, frac)))

    def position(self) -> float:
        return float(self.player.get_position() or 0.0)

    def is_ended(self) -> bool:
        return self.player.get_state() == vlc.State.Ended
```

- [ ] **Step 2: Strip `VlcWidget` out of `main.py` and add the import**

In `main.py`: delete the `class VlcWidget(QFrame): …` block and its preceding banner comment. Near the other imports add:

```python
from vlc_ranger.player import VlcWidget
```

Also delete the now-unused `import vlc` line at the top of `main.py` (VLC is used only inside `VlcWidget` now).

- [ ] **Step 3: Run the app and confirm playback works**

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

Expected: window opens, "Scan Folder…" still works, double-clicking a media file plays it. Close the window (no automated assertion possible for UI).

- [ ] **Step 4: Commit**

```bash
git add main.py vlc_ranger/player.py
git commit -m "refactor: move VlcWidget into vlc_ranger.player"
```

---

### Task 3: Move `FileRow` + `QueueModel` to `vlc_ranger/models.py`

**Files:**
- Create: `vlc_ranger/models.py`
- Modify: `main.py`

- [ ] **Step 1: Create `vlc_ranger/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtGui import QStandardItem, QStandardItemModel


@dataclass
class FileRow:
    id: int
    path: str
    parent_dir: str
    filename: str
    ext: str
    size: int
    mtime: int
    duration: Optional[float]


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

    def _append_row(self, n: int, f: FileRow):
        self.appendRow([QStandardItem(str(n)), QStandardItem(f.filename)])

    def _rebuild(self):
        self.setRowCount(0)
        for i, f in enumerate(self._files, 1):
            self._append_row(i, f)
```

- [ ] **Step 2: Strip `FileRow` and `QueueModel` from `main.py`, add imports**

In `main.py`:
- Delete `@dataclass class FileRow:` and `class QueueModel(QStandardItemModel):` blocks and their banner comments.
- Add `from vlc_ranger.models import FileRow, QueueModel` near the other imports.
- Delete the now-unused `from dataclasses import dataclass` line (and `Optional` from `typing` if it's not referenced elsewhere — leave it if it is).

- [ ] **Step 3: Run the app to verify nothing regressed**

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

Expected: same as before.

- [ ] **Step 4: Commit**

```bash
git add main.py vlc_ranger/models.py
git commit -m "refactor: move FileRow and QueueModel into vlc_ranger.models"
```

---

### Task 4: Move `LibraryDB` + `SCHEMA` to `vlc_ranger/db.py`

Keep the v0 schema exactly as today. Schema v1 work happens in Phase 2.

**Files:**
- Create: `vlc_ranger/db.py`
- Modify: `main.py`

- [ ] **Step 1: Create `vlc_ranger/db.py` by copying the current SCHEMA + LibraryDB unchanged**

Copy:
- The whole `SCHEMA = """ … """` constant block.
- The whole `class LibraryDB:` block.

Imports at the top of `vlc_ranger/db.py`:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

from vlc_ranger.models import FileRow
```

- [ ] **Step 2: Strip `SCHEMA` and `LibraryDB` from `main.py`, add import**

```python
from vlc_ranger.db import LibraryDB
```

Delete `import sqlite3` from `main.py` if no other code references it.

- [ ] **Step 3: Run the app to verify**

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

- [ ] **Step 4: Commit**

```bash
git add main.py vlc_ranger/db.py
git commit -m "refactor: move LibraryDB and SCHEMA into vlc_ranger.db"
```

---

### Task 5: Move `Scanner` to `vlc_ranger/scanner.py`

Move it unchanged. Schema-aware changes come in Task 11.

**Files:**
- Create: `vlc_ranger/scanner.py`
- Modify: `main.py`

- [ ] **Step 1: Create `vlc_ranger/scanner.py`**

Copy the `Scanner(QThread)` class verbatim from `main.py`. Also copy the `VIDEO_EXTS`, `AUDIO_EXTS`, and `MEDIA_EXTS` constants — they belong with the scanner.

Imports:

```python
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
```

- [ ] **Step 2: Strip Scanner and the EXTS constants from `main.py`, add import**

```python
from vlc_ranger.scanner import Scanner
```

- [ ] **Step 3: Run the app and trigger a scan to verify**

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

Click Scan Folder… on a small directory; confirm files appear.

- [ ] **Step 4: Commit**

```bash
git add main.py vlc_ranger/scanner.py
git commit -m "refactor: move Scanner into vlc_ranger.scanner"
```

---

### Task 6: Move `MainWindow` + `data_dir` + `APP_NAME` to `vlc_ranger/app.py`, slim `main.py`

**Files:**
- Create: `vlc_ranger/app.py`
- Modify: `main.py` → becomes a 10-line entrypoint

- [ ] **Step 1: Create `vlc_ranger/app.py` with all the moved pieces**

Copy into it:
- `APP_NAME = "vlc-library"` (rename comes in Task 7)
- `data_dir()` function
- The whole `class MainWindow(QMainWindow):` block
- The `def main(): …` function from current `main.py`

Imports for `vlc_ranger/app.py`:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QAction, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTreeView, QTableView, QFrame,
    QFileDialog, QToolBar, QStatusBar, QSlider, QMessageBox, QAbstractItemView,
    QHeaderView, QStyle, QMenu,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow, QueueModel
from vlc_ranger.player import VlcWidget
from vlc_ranger.scanner import Scanner
```

- [ ] **Step 2: Replace `main.py` with the 10-line entrypoint**

```python
"""vlc-ranger entrypoint. See vlc_ranger.app.main for the real code."""

from vlc_ranger.app import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify the app still launches and behaves identically**

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

- [ ] **Step 4: Commit**

```bash
git add main.py vlc_ranger/app.py
git commit -m "refactor: move MainWindow + entrypoint into vlc_ranger.app"
```

---

### Task 7: Rename `APP_NAME` to `vlc-ranger` with data-dir migration

After this task the app reads/writes `~/.local/share/vlc-ranger/library.db`. Existing users have their old `~/.local/share/vlc-library/` folder atomically renamed.

**Files:**
- Modify: `vlc_ranger/app.py`

- [ ] **Step 1: Update `APP_NAME` and add `data_dir()` migration logic**

In `vlc_ranger/app.py`:

```python
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
```

- [ ] **Step 2: Verify migration**

Move your existing `~/.local/share/vlc-library` aside (if present), then run the app:

```bash
ls -ld ~/.local/share/vlc-library ~/.local/share/vlc-ranger 2>&1
QT_QPA_PLATFORM=xcb python3 main.py
ls -ld ~/.local/share/vlc-library ~/.local/share/vlc-ranger 2>&1
```

Expected: after launching, `~/.local/share/vlc-ranger/` exists; `~/.local/share/vlc-library/` is gone (renamed). If neither existed before, a fresh `vlc-ranger/` is created.

- [ ] **Step 3: Commit**

```bash
git add vlc_ranger/app.py
git commit -m "refactor: rename data dir to vlc-ranger with atomic migration"
```

---

## Phase 2 — Schema v1 + matching

### Task 8: Add `matching.py` with TDD + pytest setup

This is where TDD matters — pure functions, lots of edge cases. Install pytest first.

**Files:**
- Create: `tests/test_matching.py`
- Create: `vlc_ranger/matching.py`

- [ ] **Step 1: Install pytest**

```bash
sudo apt install -y python3-pytest
```

- [ ] **Step 2: Write failing tests for `parse_generic`**

`tests/test_matching.py`:

```python
from vlc_ranger.matching import parse_generic


def test_generic_strips_extension():
    assert parse_generic("Hello World.mkv") == {"title": "Hello World"}


def test_generic_handles_multi_dot_filename():
    assert parse_generic("foo.bar.baz.mp4") == {"title": "foo.bar.baz"}


def test_generic_handles_no_extension():
    assert parse_generic("README") == {"title": "README"}
```

Run: `pytest tests/test_matching.py -v`. Expected: ImportError / collection failure (module doesn't exist yet).

- [ ] **Step 3: Implement `parse_generic`**

`vlc_ranger/matching.py`:

```python
"""Pure-function filename parsers per library type. Called from Scanner.
Each function returns a dict of whatever fields it could extract."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any


def parse_generic(filename: str) -> dict[str, Any]:
    title, _ = os.path.splitext(filename)
    return {"title": title}
```

Run: `pytest tests/test_matching.py -v`. Expected: 3 passed.

- [ ] **Step 4: Write failing tests for `parse_movie`**

Append to `tests/test_matching.py`:

```python
from vlc_ranger.matching import parse_movie


def test_movie_paren_year():
    out = parse_movie("The Matrix (1999).mkv")
    assert out["title"] == "The Matrix"
    assert out["year"] == 1999


def test_movie_dot_year_scene_release():
    out = parse_movie("The.Matrix.1999.1080p.BluRay.x264.mkv")
    assert out["title"] == "The Matrix"
    assert out["year"] == 1999


def test_movie_bracket_year():
    out = parse_movie("Inception [2010].mp4")
    assert out["title"] == "Inception"
    assert out["year"] == 2010


def test_movie_year_in_title_does_not_confuse():
    # "2001 A Space Odyssey" — the real movie year is 1968.
    out = parse_movie("2001 A Space Odyssey (1968).mkv")
    assert out["year"] == 1968
    assert "2001" in out["title"]


def test_movie_no_year_fallback():
    out = parse_movie("Some Random Movie.mkv")
    assert out["title"] == "Some Random Movie"
    assert out["year"] is None


def test_movie_implausible_year_ignored():
    # 1850 is before 1900 — shouldn't be treated as a year.
    out = parse_movie("Old Footage 1850.mkv")
    assert out["year"] is None
```

Run: `pytest tests/test_matching.py -v`. Expected: 6 new failures.

- [ ] **Step 5: Implement `parse_movie`**

Append to `vlc_ranger/matching.py`:

```python
_YEAR_PATTERNS = [
    re.compile(r"\((\d{4})\)"),         # (1999)
    re.compile(r"\[(\d{4})\]"),         # [1999]
    re.compile(r"[.\s](\d{4})[.\s]"),   # .1999. or  1999
]


def _plausible_year(y: int) -> bool:
    return 1900 <= y <= datetime.now().year + 2


def _normalize_title(s: str) -> str:
    s = s.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_movie(filename: str) -> dict[str, Any]:
    base, _ = os.path.splitext(filename)
    # Find the LAST plausible-year match, since titles can contain year-like numbers.
    best_pos = -1
    best_year: int | None = None
    for pat in _YEAR_PATTERNS:
        for m in pat.finditer(base):
            y = int(m.group(1))
            if _plausible_year(y) and m.start() > best_pos:
                best_pos = m.start()
                best_year = y
    if best_year is None:
        return {"title": _normalize_title(base), "year": None}
    return {"title": _normalize_title(base[:best_pos]), "year": best_year}
```

Run: `pytest tests/test_matching.py -v`. Expected: 9 passed total.

- [ ] **Step 6: Write failing tests for `parse_tv`**

Append:

```python
from vlc_ranger.matching import parse_tv


def test_tv_sxxeyy_pattern():
    out = parse_tv("Breaking Bad - S01E03 - Pilot.mkv", parent_dir="/tv")
    assert out["series"] == "Breaking Bad"
    assert out["season"] == 1
    assert out["episode"] == 3


def test_tv_dot_separated_lower():
    out = parse_tv("breaking.bad.s05e14.felina.mkv", parent_dir="/tv")
    assert out["season"] == 5
    assert out["episode"] == 14


def test_tv_one_x_pattern():
    out = parse_tv("Severance 1x07.mp4", parent_dir="/tv")
    assert out["series"] == "Severance"
    assert out["season"] == 1
    assert out["episode"] == 7


def test_tv_folder_season_episode_in_filename():
    out = parse_tv("01 - Pilot.mkv", parent_dir="/tv/Breaking Bad/Season 1")
    assert out["series"] == "Breaking Bad"
    assert out["season"] == 1
    assert out["episode"] == 1


def test_tv_folder_season_s0n():
    out = parse_tv("03 - The Cat in the Bag.mkv",
                   parent_dir="/tv/Breaking Bad/S02")
    assert out["season"] == 2
    assert out["episode"] == 3


def test_tv_unsorted_fallback():
    out = parse_tv("random episode title.mkv",
                   parent_dir="/tv/Some Show")
    assert out["series"] == "Some Show"
    assert out["season"] is None
    assert out["episode"] is None
```

Run: expected 6 new failures.

- [ ] **Step 7: Implement `parse_tv`**

Append:

```python
_SXXEYY = re.compile(r"[sS](\d{1,2})[eE](\d{1,3})")
_ONE_X = re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)")
_SEASON_FOLDER = re.compile(r"(?i)^(?:season\s*|s0?)(\d{1,2})$")
_LEADING_NUM = re.compile(r"^\s*(\d{1,3})\b")


def parse_tv(filename: str, parent_dir: str) -> dict[str, Any]:
    base, _ = os.path.splitext(filename)

    m = _SXXEYY.search(base) or _ONE_X.search(base)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        series = _normalize_title(base[:m.start()])
        if series:
            return {"series": series, "season": season, "episode": episode}

    folder_name = os.path.basename(parent_dir.rstrip("/"))
    season_match = _SEASON_FOLDER.match(folder_name)
    if season_match:
        season = int(season_match.group(1))
        series_dir = os.path.dirname(parent_dir.rstrip("/"))
        series = os.path.basename(series_dir) or parent_dir
        ep_match = _LEADING_NUM.search(base)
        episode = int(ep_match.group(1)) if ep_match else None
        return {"series": series, "season": season, "episode": episode}

    return {"series": folder_name, "season": None, "episode": None}
```

Run: `pytest tests/test_matching.py -v`. Expected: 15 passed.

- [ ] **Step 8: Write failing tests for `parse_music`**

Append:

```python
from vlc_ranger.matching import parse_music


def test_music_three_level_layout():
    out = parse_music(
        filename="01 - Black Dog.mp3",
        parent_dir="/music/Led Zeppelin/IV",
    )
    assert out["artist"] == "Led Zeppelin"
    assert out["album"] == "IV"
    assert out["track"] == 1
    assert out["title"] == "Black Dog"


def test_music_two_level_no_artist():
    out = parse_music(
        filename="03 - Track.mp3",
        parent_dir="/music/Greatest Hits",
    )
    assert out["artist"] is None
    assert out["album"] == "Greatest Hits"
    assert out["track"] == 3


def test_music_flat_no_artist_no_album():
    out = parse_music(filename="random.mp3", parent_dir="/music")
    assert out["artist"] is None
    assert out["album"] is None
    assert out["title"] == "random"
```

Run: expected 3 new failures.

- [ ] **Step 9: Implement `parse_music`**

Append:

```python
_TRACK_PREFIX = re.compile(r"^\s*(\d{1,3})\s*[-.\s]+(.*)$")


def parse_music(filename: str, parent_dir: str) -> dict[str, Any]:
    base, _ = os.path.splitext(filename)
    track = None
    title = base
    m = _TRACK_PREFIX.match(base)
    if m:
        track = int(m.group(1))
        title = m.group(2).strip()
    title = _normalize_title(title)

    parts = [p for p in parent_dir.strip("/").split("/") if p]
    album = parts[-1] if len(parts) >= 1 else None
    artist = parts[-2] if len(parts) >= 2 else None

    # Heuristic for "flat" layout: if parent_dir is the library root itself
    # (caller decides; here we just expose what we found). For a single-part
    # parent_dir, prefer album=None too — there's no real album context.
    if len(parts) <= 1:
        album = None
        artist = None
    return {"artist": artist, "album": album, "track": track, "title": title}
```

Run: `pytest tests/test_matching.py -v`. Expected: 18 passed.

- [ ] **Step 10: Add a top-level `parse` dispatcher**

Append:

```python
def parse(library_type: str, filename: str, parent_dir: str) -> dict[str, Any]:
    if library_type == "movies":
        return parse_movie(filename)
    if library_type == "tv":
        return parse_tv(filename, parent_dir)
    if library_type == "music":
        return parse_music(filename, parent_dir)
    return parse_generic(filename)
```

Add a couple of dispatcher tests:

```python
from vlc_ranger.matching import parse


def test_dispatch_movies():
    out = parse("movies", "Arrival (2016).mkv", "/movies")
    assert out["year"] == 2016


def test_dispatch_unknown_type_falls_to_generic():
    out = parse("nonsense", "x.mp4", "/foo")
    assert out == {"title": "x"}
```

Run: `pytest tests/test_matching.py -v`. Expected: 20 passed.

- [ ] **Step 11: Commit**

```bash
git add vlc_ranger/matching.py tests/test_matching.py
git commit -m "feat: add per-type filename parsers with pytest coverage"
```

---

### Task 9: Schema v1 — add `libraries`, `library_folders`, `ui_state`; add columns to `files`; update FTS5

This task only changes the SQL strings — migration logic comes in Task 10.

**Files:**
- Modify: `vlc_ranger/db.py`

- [ ] **Step 1: Rewrite the `SCHEMA` constant to v1 final shape**

In `vlc_ranger/db.py`, replace the existing `SCHEMA = """ … """` with:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS libraries (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    type    TEXT NOT NULL CHECK (type IN ('movies','tv','music','generic')),
    added   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS library_folders (
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    path        TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_library_folders_lib ON library_folders(library_id);

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
    path        TEXT UNIQUE NOT NULL,
    parent_dir  TEXT NOT NULL,
    filename    TEXT NOT NULL,
    ext         TEXT NOT NULL,
    size        INTEGER,
    mtime       INTEGER,
    duration    REAL,
    last_seen   INTEGER NOT NULL,
    title       TEXT,
    year        INTEGER,
    series      TEXT,
    season      INTEGER,
    episode     INTEGER,
    artist      TEXT,
    album       TEXT,
    track       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_files_library ON files(library_id);
CREATE INDEX IF NOT EXISTS idx_files_parent  ON files(parent_dir);
CREATE INDEX IF NOT EXISTS idx_files_ext     ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_mtime   ON files(mtime);
CREATE INDEX IF NOT EXISTS idx_files_series  ON files(library_id, series, season, episode);
CREATE INDEX IF NOT EXISTS idx_files_album   ON files(library_id, artist, album, track);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename, parent_dir, title, series, artist, album,
    content='files', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, filename, parent_dir, title, series, artist, album)
    VALUES (new.id, new.filename, new.parent_dir, new.title, new.series, new.artist, new.album);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, parent_dir, title, series, artist, album)
    VALUES('delete', old.id, old.filename, old.parent_dir, old.title, old.series, old.artist, old.album);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, parent_dir, title, series, artist, album)
    VALUES('delete', old.id, old.filename, old.parent_dir, old.title, old.series, old.artist, old.album);
    INSERT INTO files_fts(rowid, filename, parent_dir, title, series, artist, album)
    VALUES (new.id, new.filename, new.parent_dir, new.title, new.series, new.artist, new.album);
END;

CREATE TABLE IF NOT EXISTS watch_state (
    file_id      INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    position     REAL DEFAULT 0,
    watched      INTEGER DEFAULT 0,
    last_played  INTEGER
);

CREATE TABLE IF NOT EXISTS queue (
    pos      INTEGER PRIMARY KEY,
    file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ui_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""
```

- [ ] **Step 2: Update `FileRow` dataclass to include the new columns**

In `vlc_ranger/models.py`, change `FileRow`:

```python
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
```

- [ ] **Step 3: Update existing `LibraryDB` queries that build `FileRow`**

`search`, `files_under`, and `load_queue` currently do `SELECT id, path, parent_dir, filename, ext, size, mtime, duration`. Change each to select all FileRow fields in order:

```sql
SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
       title, year, series, season, episode, artist, album, track
FROM …
```

There are three call sites in `db.py`: `search`, `files_under`, `load_queue`. Update each. Also one inside `MainWindow._selected_result_rows` in `vlc_ranger/app.py` — fix it too.

- [ ] **Step 4: Verify the schema applies cleanly on a fresh DB**

```bash
rm -rf ~/.local/share/vlc-ranger    # destructive; back it up first if it matters
QT_QPA_PLATFORM=xcb python3 main.py
```

App should open without errors. Sidebar/folder tree will be empty (no libraries yet — that's expected; the UI still shows the v0 layout, which queries `roots` and gets nothing). Close it.

- [ ] **Step 5: Inspect schema with sqlite3 CLI**

```bash
sqlite3 ~/.local/share/vlc-ranger/library.db ".schema"
```

Expected: `libraries`, `library_folders`, `files` (with new columns), `files_fts` with 6 columns, `ui_state` all present.

- [ ] **Step 6: Commit**

```bash
git add vlc_ranger/db.py vlc_ranger/models.py vlc_ranger/app.py
git commit -m "feat: schema v1 — libraries, library_folders, parsed columns, ui_state"
```

---

### Task 10: Migration from v0 → v1 via `PRAGMA user_version`

**Files:**
- Modify: `vlc_ranger/db.py`

- [ ] **Step 1: Add `_migrate` and call it from `LibraryDB.__init__`**

In `vlc_ranger/db.py`, in `LibraryDB.__init__`, after `self.conn.executescript(SCHEMA)` and before `self.conn.commit()`, insert:

```python
self._migrate()
```

Add this method to `LibraryDB`:

```python
def _migrate(self) -> None:
    v = self.conn.execute("PRAGMA user_version").fetchone()[0]
    if v < 1:
        self._migrate_v0_to_v1()
        self.conn.execute("PRAGMA user_version = 1")
        self.conn.commit()

def _migrate_v0_to_v1(self) -> None:
    """Move existing `roots` rows into a Default library and backfill files.library_id."""
    # Does old `roots` table exist? Fresh installs won't have it.
    has_roots = self.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='roots'"
    ).fetchone() is not None
    if not has_roots:
        return

    roots = [r[0] for r in self.conn.execute("SELECT path FROM roots")]
    if roots:
        self.conn.execute(
            "INSERT OR IGNORE INTO libraries(name, type, added) VALUES (?, ?, ?)",
            ("Default", "generic", int(time.time())),
        )
        lib_id = self.conn.execute(
            "SELECT id FROM libraries WHERE name='Default'"
        ).fetchone()[0]
        for r in roots:
            self.conn.execute(
                "INSERT OR IGNORE INTO library_folders(library_id, path) VALUES (?, ?)",
                (lib_id, r),
            )
        # Backfill: each existing file gets library_id of the deepest matching folder.
        self.conn.execute("""
            UPDATE files SET library_id = (
                SELECT lf.library_id FROM library_folders lf
                WHERE files.path LIKE lf.path || '/%'
                ORDER BY length(lf.path) DESC LIMIT 1
            ) WHERE library_id IS NULL
        """)
    self.conn.execute("DROP TABLE roots")
```

- [ ] **Step 2: Verify migration on a v0 DB**

If you still have a v0 DB lying around use that; otherwise prep one:

```bash
# Build a v0 DB by checking out the prior commit, running the app, scanning a folder
git stash
git checkout HEAD~3 -- vlc_ranger/db.py    # pre-v1 schema
QT_QPA_PLATFORM=xcb python3 main.py        # add a root, scan, close
git checkout HEAD -- vlc_ranger/db.py
git stash pop
```

Then trigger the migration:

```bash
sqlite3 ~/.local/share/vlc-ranger/library.db "PRAGMA user_version"  # → 0
QT_QPA_PLATFORM=xcb python3 main.py &
sleep 2 && kill %1
sqlite3 ~/.local/share/vlc-ranger/library.db "PRAGMA user_version"  # → 1
sqlite3 ~/.local/share/vlc-ranger/library.db \
  "SELECT name, type FROM libraries; SELECT path FROM library_folders;"
sqlite3 ~/.local/share/vlc-ranger/library.db \
  "SELECT COUNT(*) AS total, COUNT(library_id) AS with_lib FROM files;"
```

Expected: a `Default` (generic) library; one `library_folders` row per old root; all (or nearly all) `files` rows have `library_id` set.

- [ ] **Step 3: Verify a fresh-install path is a no-op**

```bash
rm -rf ~/.local/share/vlc-ranger
QT_QPA_PLATFORM=xcb python3 main.py &
sleep 2 && kill %1
sqlite3 ~/.local/share/vlc-ranger/library.db "PRAGMA user_version"  # → 1
sqlite3 ~/.local/share/vlc-ranger/library.db "SELECT * FROM libraries"  # empty
```

- [ ] **Step 4: Commit**

```bash
git add vlc_ranger/db.py
git commit -m "feat: migrate v0 -> v1, roll old roots into Default library"
```

---

### Task 11: Scanner uses `library_id` + calls `matching.parse`

**Files:**
- Modify: `vlc_ranger/scanner.py`
- Modify: `vlc_ranger/db.py` (add `add_library`, `add_library_folder`, `list_libraries`, `library_folders` helpers)

- [ ] **Step 1: Add library CRUD helpers in `LibraryDB`**

In `vlc_ranger/db.py`, replace the `# roots` section with library helpers:

```python
# libraries -----------------------------------------------------------
def add_library(self, name: str, type_: str) -> int:
    cur = self.conn.execute(
        "INSERT INTO libraries(name, type, added) VALUES (?, ?, ?)",
        (name, type_, int(time.time())),
    )
    self.conn.commit()
    return cur.lastrowid

def update_library(self, lib_id: int, name: str, type_: str) -> None:
    self.conn.execute(
        "UPDATE libraries SET name=?, type=? WHERE id=?", (name, type_, lib_id)
    )
    self.conn.commit()

def delete_library(self, lib_id: int) -> None:
    self.conn.execute("DELETE FROM libraries WHERE id=?", (lib_id,))
    self.conn.commit()

def list_libraries(self) -> list[tuple[int, str, str]]:
    return list(self.conn.execute("SELECT id, name, type FROM libraries ORDER BY name"))

def add_library_folder(self, lib_id: int, path: str) -> None:
    self.conn.execute(
        "INSERT OR IGNORE INTO library_folders(library_id, path) VALUES (?, ?)",
        (lib_id, path),
    )
    self.conn.commit()

def remove_library_folder(self, folder_id: int) -> None:
    self.conn.execute("DELETE FROM library_folders WHERE id=?", (folder_id,))
    self.conn.commit()

def library_folders(self, lib_id: int) -> list[tuple[int, str]]:
    return list(self.conn.execute(
        "SELECT id, path FROM library_folders WHERE library_id=? ORDER BY path",
        (lib_id,),
    ))

def get_library_type(self, lib_id: int) -> str:
    row = self.conn.execute("SELECT type FROM libraries WHERE id=?", (lib_id,)).fetchone()
    return row[0] if row else "generic"
```

- [ ] **Step 2: Rewrite `Scanner` to take `library_id` + `library_type` + folder list**

Replace the entire `Scanner` class in `vlc_ranger/scanner.py`:

```python
from vlc_ranger.matching import parse


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
```

- [ ] **Step 3: Verify by running a temporary scan**

`app.py` is still using the old `Scanner(db_path, root)` signature, so we need to update one call site to keep the app launchable. Replace the `_start_scan` method body in `vlc_ranger/app.py` with a temporary stub:

```python
def _start_scan(self, root: str):
    QMessageBox.information(self, "Phase 3 needed",
                            "Library editor + scan-by-library lands in the UI phase.")
```

(The old `_scan_folder` and `_rescan_all` still call this; that's fine — they just pop a message until the new sidebar replaces them in Task 12.)

Verify the app still launches without crashing:

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

- [ ] **Step 4: Commit**

```bash
git add vlc_ranger/scanner.py vlc_ranger/db.py vlc_ranger/app.py
git commit -m "feat: scanner is library-aware and runs matching during scan"
```

---

## Phase 3 — UI

After Task 11 the app launches but has no working UI for the new model. Phase 3 rebuilds the main window around `Sidebar` + `Browse` + `QueuePanel`. We do the skeleton + Generic view first (Task 12–15) so we have a working end-to-end loop, then add the richer per-type views.

### Task 12: Sidebar widget (library list + context menu + "+ New")

**Files:**
- Create: `vlc_ranger/ui/sidebar.py`

- [ ] **Step 1: Implement `Sidebar`**

```python
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
```

- [ ] **Step 2: Commit (no integration yet)**

```bash
git add vlc_ranger/ui/sidebar.py
git commit -m "feat: Sidebar widget for the library list"
```

---

### Task 13: Library editor dialog

**Files:**
- Create: `vlc_ranger/ui/library_editor.py`

- [ ] **Step 1: Implement `LibraryEditor`**

```python
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)


TYPE_CHOICES = [
    ("movies",  "Movies"),
    ("tv",      "TV"),
    ("music",   "Music"),
    ("generic", "Generic"),
]


class LibraryEditor(QDialog):
    """Modal dialog. Returns (name, type, folders: list[str]) via .result_data."""

    def __init__(self, parent=None, *, initial_name: str = "",
                 initial_type: str = "movies",
                 initial_folders: Optional[list[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Library")
        self.setMinimumWidth(440)
        self.result_data: Optional[tuple[str, str, list[str]]] = None

        self.name = QLineEdit(initial_name)
        self.type = QComboBox()
        for code, label in TYPE_CHOICES:
            self.type.addItem(label, code)
        self.type.setCurrentIndex(
            next(i for i, (c, _) in enumerate(TYPE_CHOICES) if c == initial_type)
        )

        self.folders = QListWidget()
        for f in initial_folders or []:
            self.folders.addItem(QListWidgetItem(f))

        add_btn = QPushButton("+ Add Folder…")
        rm_btn = QPushButton("− Remove")
        add_btn.clicked.connect(self._add_folder)
        rm_btn.clicked.connect(self._remove_folder)
        folder_buttons = QHBoxLayout()
        folder_buttons.addWidget(add_btn)
        folder_buttons.addWidget(rm_btn)
        folder_buttons.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Name"))
        lay.addWidget(self.name)
        lay.addWidget(QLabel("Type"))
        lay.addWidget(self.type)
        lay.addWidget(QLabel("Folders"))
        lay.addWidget(self.folders, 1)
        lay.addLayout(folder_buttons)
        lay.addWidget(buttons)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Add folder")
        if path:
            self.folders.addItem(QListWidgetItem(path))

    def _remove_folder(self):
        for item in self.folders.selectedItems():
            self.folders.takeItem(self.folders.row(item))

    def _accept(self):
        name = self.name.text().strip()
        if not name:
            return
        folders = [self.folders.item(i).text() for i in range(self.folders.count())]
        self.result_data = (name, self.type.currentData(), folders)
        self.accept()
```

- [ ] **Step 2: Commit**

```bash
git add vlc_ranger/ui/library_editor.py
git commit -m "feat: LibraryEditor dialog"
```

---

### Task 14: Generic view (port of current results table) + browse router skeleton

This is the smallest possible end-to-end browse loop. Subsequent tasks add the richer per-type views.

**Files:**
- Create: `vlc_ranger/ui/views/generic.py`
- Create: `vlc_ranger/ui/browse.py`
- Modify: `vlc_ranger/db.py` (add `files_in_library`)

- [ ] **Step 1: Add `files_in_library` helper to `LibraryDB`**

In `vlc_ranger/db.py`:

```python
def files_in_library(self, library_id: int) -> list[FileRow]:
    sql = """SELECT id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
                    title, year, series, season, episode, artist, album, track
             FROM files WHERE library_id=? ORDER BY filename"""
    return [FileRow(*r) for r in self.conn.execute(sql, (library_id,))]
```

- [ ] **Step 2: Implement `GenericView`**

`vlc_ranger/ui/views/generic.py`:

```python
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QMenu, QTableView, QVBoxLayout, QWidget,
)

from vlc_ranger.models import FileRow


class GenericView(QWidget):
    play_requested = pyqtSignal(object)        # FileRow
    queue_end_requested = pyqtSignal(list)     # list[FileRow]
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = QTableView()
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Filename", "Folder"])
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.doubleClicked.connect(self._double)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)

        self._rows: list[FileRow] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)

    def set_rows(self, rows: list[FileRow]):
        self._rows = rows
        self.model.setRowCount(0)
        for f in rows:
            self.model.appendRow([
                QStandardItem(f.filename),
                QStandardItem(f.parent_dir),
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
```

- [ ] **Step 3: Implement `BrowseRouter`**

`vlc_ranger/ui/browse.py`:

```python
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow
from vlc_ranger.ui.views.generic import GenericView


class BrowseRouter(QWidget):
    """Owns the per-type view stack. Re-renders when a library is selected."""

    play_requested = pyqtSignal(object)
    queue_end_requested = pyqtSignal(list)
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)

    def __init__(self, db: LibraryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self.current_library_id: int | None = None

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search across all libraries…")
        self.search.textChanged.connect(self._on_search)

        self.stack = QStackedWidget()
        self.generic = GenericView()
        self.stack.addWidget(self.generic)

        # Re-emit child signals upward.
        for v in (self.generic,):
            v.play_requested.connect(self.play_requested.emit)
            v.queue_end_requested.connect(self.queue_end_requested.emit)
            v.queue_front_requested.connect(self.queue_front_requested.emit)
            v.play_next_requested.connect(self.play_next_requested.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.search)
        lay.addWidget(self.stack, 1)

    def show_library(self, library_id: int):
        self.current_library_id = library_id
        type_ = self.db.get_library_type(library_id)
        rows = self.db.files_in_library(library_id)
        # For now every type renders through Generic until Tasks 15–17 add the rest.
        self.generic.set_rows(rows)
        self.stack.setCurrentWidget(self.generic)

    def _on_search(self, text: str):
        rows = self.db.search(text) if text.strip() else []
        self.generic.set_rows(rows)
        self.stack.setCurrentWidget(self.generic)
```

- [ ] **Step 4: Rewrite `MainWindow._build_ui` to use Sidebar + BrowseRouter (no Queue panel yet)**

This is the biggest single edit in the plan. Replace `MainWindow._build_ui` in `vlc_ranger/app.py` with:

```python
def _build_ui(self):
    from vlc_ranger.ui.sidebar import Sidebar
    from vlc_ranger.ui.browse import BrowseRouter
    from vlc_ranger.ui.library_editor import LibraryEditor

    self.sidebar = Sidebar()
    self.browse = BrowseRouter(self.db)

    self.sidebar.library_selected.connect(self.browse.show_library)
    self.sidebar.new_library_requested.connect(self._new_library)
    self.sidebar.edit_library_requested.connect(self._edit_library)
    self.sidebar.rescan_library_requested.connect(self._rescan_library)
    self.sidebar.delete_library_requested.connect(self._delete_library)

    self.browse.play_requested.connect(self._play)
    self.browse.queue_end_requested.connect(self._add_to_queue_end)
    self.browse.queue_front_requested.connect(self._add_to_queue_front)
    self.browse.play_next_requested.connect(self._play_next)

    self.video = VlcWidget()
    self.transport = QSlider(Qt.Orientation.Horizontal)
    self.transport.setRange(0, 1000)
    self.transport.sliderMoved.connect(lambda v: self.video.set_position(v / 1000.0))
    self.now_playing = QLabel("Nothing playing")

    controls = QHBoxLayout()
    for icon, slot in [
        (QStyle.StandardPixmap.SP_MediaPlay,         self._toggle_pause),
        (QStyle.StandardPixmap.SP_MediaStop,         self.video.stop),
        (QStyle.StandardPixmap.SP_MediaSkipForward,  self._play_next_from_queue),
    ]:
        b = QPushButton()
        b.setIcon(self.style().standardIcon(icon))
        b.clicked.connect(slot)
        controls.addWidget(b)
    controls.addWidget(self.transport, 1)

    video_wrap = QWidget()
    vw = QVBoxLayout(video_wrap)
    vw.setContentsMargins(0, 0, 0, 0)
    vw.addWidget(self.video, 1)
    vw.addWidget(self.now_playing)
    vw.addLayout(controls)

    center_split = QSplitter(Qt.Orientation.Vertical)
    center_split.addWidget(self.browse)
    center_split.addWidget(video_wrap)
    center_split.setSizes([600, 250])
    self.center_split = center_split

    root_split = QSplitter(Qt.Orientation.Horizontal)
    root_split.addWidget(self.sidebar)
    root_split.addWidget(center_split)
    root_split.setSizes([260, 1140])
    self.root_split = root_split
    self.setCentralWidget(root_split)
    self.setStatusBar(QStatusBar())

    self.sidebar.reload(self.db.list_libraries())
```

Replace `_restore_state` with the simplified version (folder tree is gone):

```python
def _restore_state(self):
    self.queue_model.append(self.db.load_queue())
```

Add the new sidebar handlers in `MainWindow`:

```python
def _new_library(self):
    dlg = LibraryEditor(self)
    if dlg.exec() and dlg.result_data:
        name, type_, folders = dlg.result_data
        try:
            lib_id = self.db.add_library(name, type_)
        except Exception as e:
            QMessageBox.warning(self, "Couldn't create library", str(e))
            return
        for f in folders:
            self.db.add_library_folder(lib_id, f)
        self.sidebar.reload(self.db.list_libraries())
        if folders:
            self._start_scan_library(lib_id)

def _edit_library(self, lib_id: int):
    libs = {i: (n, t) for (i, n, t) in self.db.list_libraries()}
    name, type_ = libs.get(lib_id, ("", "generic"))
    folders = [p for (_, p) in self.db.library_folders(lib_id)]
    dlg = LibraryEditor(self, initial_name=name, initial_type=type_,
                        initial_folders=folders)
    if dlg.exec() and dlg.result_data:
        new_name, new_type, new_folders = dlg.result_data
        old_folders = set(folders)
        added = [f for f in new_folders if f not in old_folders]
        removed = [f for f in folders if f not in set(new_folders)]
        self.db.update_library(lib_id, new_name, new_type)
        for f in removed:
            # Find the folder id and delete it
            for fid, p in self.db.library_folders(lib_id):
                if p == f:
                    self.db.remove_library_folder(fid)
                    break
        for f in added:
            self.db.add_library_folder(lib_id, f)
        self.sidebar.reload(self.db.list_libraries())
        if added or new_type != type_:
            self._start_scan_library(lib_id)

def _rescan_library(self, lib_id: int):
    self._start_scan_library(lib_id)

def _delete_library(self, lib_id: int):
    if QMessageBox.question(
        self, "Delete library?",
        "This removes the library and all its indexed files (and their queue/watch state). Continue?",
    ) == QMessageBox.StandardButton.Yes:
        self.db.delete_library(lib_id)
        self.sidebar.reload(self.db.list_libraries())

def _start_scan_library(self, lib_id: int):
    if self.scanner and self.scanner.isRunning():
        QMessageBox.information(self, "Busy", "A scan is already running.")
        return
    folders = [p for (_, p) in self.db.library_folders(lib_id)]
    if not folders:
        return
    type_ = self.db.get_library_type(lib_id)
    self.scanner = Scanner(self.db.db_path, lib_id, type_, folders)
    self.scanner.progress.connect(
        lambda n, d: self.statusBar().showMessage(f"Scanning {n}: {d}")
    )
    self.scanner.finished_scan.connect(
        lambda total: (self.statusBar().showMessage(f"Indexed {total} file(s)"),
                       self.browse.show_library(lib_id))
    )
    self.scanner.start()
```

Delete the now-dead methods from `MainWindow`: `_add_root_node`, `_on_folder_expand`, `_fill_results`, `_on_search`, `_scan_folder`, `_rescan_all`, `_start_scan` (the stub), `_results_menu`, `_folder_menu`, `_play_folder`, `_play_selected_result`, `_selected_result_rows`, `_jump_queue`. Also delete `_build_toolbar` and its reference in `__init__`; the new toolbar comes back in Task 19.

- [ ] **Step 5: Launch and exercise the basic loop**

```bash
QT_QPA_PLATFORM=xcb python3 main.py
```

Click `+ New Library…`, name it "Test", pick type Generic, add a folder, OK. Wait for scan. Click the library in the sidebar — files appear in the table. Double-click → plays.

- [ ] **Step 6: Commit**

```bash
git add vlc_ranger/db.py vlc_ranger/app.py vlc_ranger/ui/views/generic.py vlc_ranger/ui/browse.py
git commit -m "feat: sidebar + browse router + generic view; basic library loop"
```

---

### Task 15: Movies view (icon-grid of title-cards)

**Files:**
- Create: `vlc_ranger/ui/views/movies.py`
- Modify: `vlc_ranger/ui/browse.py` (register movies view)

- [ ] **Step 1: Implement `MoviesView`**

```python
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
```

- [ ] **Step 2: Register `MoviesView` in `BrowseRouter`**

In `vlc_ranger/ui/browse.py`, change `__init__` to add a movies page and rewrite `show_library` to dispatch by type:

```python
# in imports:
from vlc_ranger.ui.views.movies import MoviesView

# in __init__, after self.generic is constructed:
self.movies = MoviesView()
self.stack.addWidget(self.movies)
for v in (self.generic, self.movies):       # update existing for-loop
    v.play_requested.connect(self.play_requested.emit)
    v.queue_end_requested.connect(self.queue_end_requested.emit)
    v.queue_front_requested.connect(self.queue_front_requested.emit)
    v.play_next_requested.connect(self.play_next_requested.emit)

# replace show_library:
def show_library(self, library_id: int):
    self.current_library_id = library_id
    type_ = self.db.get_library_type(library_id)
    rows = self.db.files_in_library(library_id)
    if type_ == "movies":
        self.movies.set_rows(rows)
        self.stack.setCurrentWidget(self.movies)
    else:
        self.generic.set_rows(rows)
        self.stack.setCurrentWidget(self.generic)
```

- [ ] **Step 3: Verify**

Run the app, create a Movies-typed library, scan a folder with movies, click into the library — should see a grid of title-cards.

- [ ] **Step 4: Commit**

```bash
git add vlc_ranger/ui/views/movies.py vlc_ranger/ui/browse.py
git commit -m "feat: Movies view (title-card grid)"
```

---

### Task 16: TV view (shows → seasons → episodes)

**Files:**
- Create: `vlc_ranger/ui/views/tv.py`
- Modify: `vlc_ranger/db.py` (add `tv_shows`, `tv_seasons`, `tv_episodes` helpers)
- Modify: `vlc_ranger/ui/browse.py`

- [ ] **Step 1: Add TV query helpers**

In `vlc_ranger/db.py`:

```python
def tv_shows(self, library_id: int) -> list[tuple[str, int]]:
    """Returns (series, episode_count). 'Unsorted' is just NULL series → folder name."""
    rows = self.conn.execute(
        """SELECT COALESCE(series, '(Unsorted)') AS s, COUNT(*) FROM files
           WHERE library_id=? GROUP BY s ORDER BY s""",
        (library_id,),
    ).fetchall()
    return rows

def tv_seasons(self, library_id: int, series: str) -> list[tuple[int | None, int]]:
    sql = """SELECT season, COUNT(*) FROM files
             WHERE library_id=? AND COALESCE(series,'(Unsorted)')=?
             GROUP BY season ORDER BY season"""
    return list(self.conn.execute(sql, (library_id, series)))

def tv_episodes(self, library_id: int, series: str,
                season: int | None) -> list[FileRow]:
    cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
              title, year, series, season, episode, artist, album, track"""
    if season is None:
        sql = f"""SELECT {cols} FROM files
                  WHERE library_id=? AND COALESCE(series,'(Unsorted)')=? AND season IS NULL
                  ORDER BY filename"""
        args = (library_id, series)
    else:
        sql = f"""SELECT {cols} FROM files
                  WHERE library_id=? AND COALESCE(series,'(Unsorted)')=? AND season=?
                  ORDER BY episode, filename"""
        args = (library_id, series, season)
    return [FileRow(*r) for r in self.conn.execute(sql, args)]
```

- [ ] **Step 2: Implement `TVView`**

`vlc_ranger/ui/views/tv.py`:

```python
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QListView, QMenu, QPushButton,
    QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow


class TVView(QWidget):
    play_requested = pyqtSignal(object)
    queue_end_requested = pyqtSignal(list)
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)

    def __init__(self, db: LibraryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self.library_id: int | None = None
        self.current_show: str | None = None
        self.current_season: int | None = None

        self.breadcrumb = QLabel("")
        self.back = QPushButton("← Back")
        self.back.clicked.connect(self._go_up)

        top = QVBoxLayout()
        top.addWidget(self.back)
        top.addWidget(self.breadcrumb)

        self.stack = QStackedWidget()
        self.shows = QListView()
        self.shows_model = QStandardItemModel()
        self.shows.setModel(self.shows_model)
        self.shows.setViewMode(QListView.ViewMode.IconMode)
        self.shows.setResizeMode(QListView.ResizeMode.Adjust)
        self.shows.doubleClicked.connect(self._click_show)

        self.seasons = QListView()
        self.seasons_model = QStandardItemModel()
        self.seasons.setModel(self.seasons_model)
        self.seasons.doubleClicked.connect(self._click_season)

        self.episodes = QTableView()
        self.episodes_model = QStandardItemModel()
        self.episodes_model.setHorizontalHeaderLabels(["#", "Title", "File"])
        self.episodes.setModel(self.episodes_model)
        self.episodes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.episodes.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.episodes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.episodes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.episodes.doubleClicked.connect(self._click_episode)
        self.episodes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.episodes.customContextMenuRequested.connect(self._episode_menu)
        self._episode_rows: list[FileRow] = []

        self.stack.addWidget(self.shows)
        self.stack.addWidget(self.seasons)
        self.stack.addWidget(self.episodes)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.stack, 1)

    # public --------------------------------------------------------------
    def set_library(self, library_id: int):
        self.library_id = library_id
        self.current_show = None
        self.current_season = None
        self._render_shows()

    # rendering -----------------------------------------------------------
    def _render_shows(self):
        self.stack.setCurrentWidget(self.shows)
        self.breadcrumb.setText("TV")
        self.shows_model.clear()
        for series, count in self.db.tv_shows(self.library_id):
            item = QStandardItem(f"{series}\n({count})")
            item.setData(series, Qt.ItemDataRole.UserRole)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.shows_model.appendRow(item)

    def _render_seasons(self):
        self.stack.setCurrentWidget(self.seasons)
        self.breadcrumb.setText(f"TV / {self.current_show}")
        self.seasons_model.clear()
        for season, count in self.db.tv_seasons(self.library_id, self.current_show):
            label = "Unsorted" if season is None else f"Season {season}"
            item = QStandardItem(f"{label} ({count})")
            item.setData(season, Qt.ItemDataRole.UserRole)
            self.seasons_model.appendRow(item)

    def _render_episodes(self):
        self.stack.setCurrentWidget(self.episodes)
        season_label = "Unsorted" if self.current_season is None else f"Season {self.current_season}"
        self.breadcrumb.setText(f"TV / {self.current_show} / {season_label}")
        self._episode_rows = self.db.tv_episodes(self.library_id,
                                                 self.current_show,
                                                 self.current_season)
        self.episodes_model.setRowCount(0)
        for f in self._episode_rows:
            ep = "" if f.episode is None else str(f.episode)
            self.episodes_model.appendRow([
                QStandardItem(ep),
                QStandardItem(f.title or f.filename),
                QStandardItem(f.filename),
            ])

    # navigation ----------------------------------------------------------
    def _click_show(self, idx):
        series = self.shows_model.itemFromIndex(idx).data(Qt.ItemDataRole.UserRole)
        self.current_show = series
        self.current_season = None
        self._render_seasons()

    def _click_season(self, idx):
        season = self.seasons_model.itemFromIndex(idx).data(Qt.ItemDataRole.UserRole)
        self.current_season = season
        self._render_episodes()

    def _click_episode(self, idx):
        if 0 <= idx.row() < len(self._episode_rows):
            self.play_requested.emit(self._episode_rows[idx.row()])

    def _go_up(self):
        if self.stack.currentWidget() is self.episodes:
            self._render_seasons()
        elif self.stack.currentWidget() is self.seasons:
            self._render_shows()

    # context menus -------------------------------------------------------
    def _episode_menu(self, point):
        rows = sorted({i.row() for i in self.episodes.selectionModel().selectedRows()})
        sel = [self._episode_rows[r] for r in rows]
        if not sel:
            return
        m = QMenu(self)
        m.addAction("▶ Play now",        lambda: self.play_requested.emit(sel[0]))
        m.addAction("Queue (end)",       lambda: self.queue_end_requested.emit(sel))
        m.addAction("Queue (front)",     lambda: self.queue_front_requested.emit(sel))
        m.addAction("Play next",         lambda: self.play_next_requested.emit(sel))
        m.exec(self.episodes.viewport().mapToGlobal(point))
```

- [ ] **Step 3: Register in `BrowseRouter`**

In `vlc_ranger/ui/browse.py`, add `from vlc_ranger.ui.views.tv import TVView`, construct `self.tv = TVView(self.db)`, add to the stack and signal-relay loop, and extend `show_library`:

```python
if type_ == "tv":
    self.tv.set_library(library_id)
    self.stack.setCurrentWidget(self.tv)
elif type_ == "movies":
    self.movies.set_rows(rows)
    self.stack.setCurrentWidget(self.movies)
else:
    self.generic.set_rows(rows)
    self.stack.setCurrentWidget(self.generic)
```

- [ ] **Step 4: Verify**

Run the app, create a TV-typed library, scan a folder with `S01E01`-style files. Confirm drill-down works: shows → seasons → episodes; Back button traverses up.

- [ ] **Step 5: Commit**

```bash
git add vlc_ranger/db.py vlc_ranger/ui/views/tv.py vlc_ranger/ui/browse.py
git commit -m "feat: TV view (drill: shows -> seasons -> episodes)"
```

---

### Task 17: Music view (artists → albums → tracks)

Structurally identical to Task 16. Compress.

**Files:**
- Create: `vlc_ranger/ui/views/music.py`
- Modify: `vlc_ranger/db.py` (add `music_artists`, `music_albums`, `music_tracks`)
- Modify: `vlc_ranger/ui/browse.py`

- [ ] **Step 1: Add Music query helpers in `LibraryDB`**

```python
def music_artists(self, library_id: int) -> list[tuple[str, int]]:
    return list(self.conn.execute(
        """SELECT COALESCE(artist,'(Unknown artist)'), COUNT(*) FROM files
           WHERE library_id=? GROUP BY 1 ORDER BY 1""",
        (library_id,),
    ))

def music_albums(self, library_id: int, artist: str) -> list[tuple[str, int]]:
    return list(self.conn.execute(
        """SELECT COALESCE(album,'(Unknown album)'), COUNT(*) FROM files
           WHERE library_id=? AND COALESCE(artist,'(Unknown artist)')=?
           GROUP BY 1 ORDER BY 1""",
        (library_id, artist),
    ))

def music_tracks(self, library_id: int, artist: str, album: str) -> list[FileRow]:
    cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
              title, year, series, season, episode, artist, album, track"""
    return [FileRow(*r) for r in self.conn.execute(
        f"""SELECT {cols} FROM files
            WHERE library_id=? AND COALESCE(artist,'(Unknown artist)')=?
              AND COALESCE(album,'(Unknown album)')=?
            ORDER BY track, filename""",
        (library_id, artist, album),
    )]
```

- [ ] **Step 2: Implement `MusicView`**

Copy `tv.py` to `music.py`, rename class `TVView` → `MusicView`, rename methods `_render_shows/_seasons/_episodes` → `_render_artists/_albums/_tracks`, change breadcrumb prefix from `"TV"` to `"Music"`, change DB calls accordingly. Episode/season concepts become artist/album; track number replaces episode number; no "Unsorted" bucket — use `(Unknown artist)` / `(Unknown album)` from the SQL. Keep three-level `QStackedWidget` navigation identical.

- [ ] **Step 3: Register in `BrowseRouter`**

Add `elif type_ == "music": self.music.set_library(library_id); ...`.

- [ ] **Step 4: Verify**

Create a Music library, scan a small artist folder, confirm drill-down.

- [ ] **Step 5: Commit**

```bash
git add vlc_ranger/db.py vlc_ranger/ui/views/music.py vlc_ranger/ui/browse.py
git commit -m "feat: Music view (drill: artists -> albums -> tracks)"
```

---

### Task 18: Queue panel as toggleable right rail

**Files:**
- Create: `vlc_ranger/ui/queue_panel.py`
- Modify: `vlc_ranger/app.py`

- [ ] **Step 1: Implement `QueuePanel`**

```python
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)


class QueuePanel(QWidget):
    play_next_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    remove_requested = pyqtSignal(list)        # list[int] of row indices

    def __init__(self, queue_model, parent=None):
        super().__init__(parent)
        self.view = QTableView()
        self.view.setModel(queue_model)
        self.view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        next_btn = QPushButton("▶ Next")
        clear_btn = QPushButton("Clear")
        remove_btn = QPushButton("Remove")
        next_btn.clicked.connect(self.play_next_requested.emit)
        clear_btn.clicked.connect(self.clear_requested.emit)
        remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(
                [i.row() for i in self.view.selectionModel().selectedRows()]
            )
        )

        buttons = QHBoxLayout()
        buttons.addWidget(next_btn)
        buttons.addWidget(clear_btn)
        buttons.addWidget(remove_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Queue"))
        lay.addWidget(self.view, 1)
        lay.addLayout(buttons)
```

- [ ] **Step 2: Wire `QueuePanel` into `MainWindow`**

In `vlc_ranger/app.py`:

```python
# In _build_ui, after sidebar/browse are constructed:
from vlc_ranger.ui.queue_panel import QueuePanel
self.queue_panel = QueuePanel(self.queue_model)
self.queue_panel.play_next_requested.connect(self._play_next_from_queue)
self.queue_panel.clear_requested.connect(self._clear_queue)
self.queue_panel.remove_requested.connect(self.queue_model.remove_indices)
self.queue_panel.remove_requested.connect(lambda *_: self._persist_queue())
self.queue_panel.setVisible(False)         # toggled by Ctrl+Q / toolbar button

# Change root_split to add queue_panel as a third pane:
root_split = QSplitter(Qt.Orientation.Horizontal)
root_split.addWidget(self.sidebar)
root_split.addWidget(center_split)
root_split.addWidget(self.queue_panel)
root_split.setSizes([260, 880, 260])
```

Add a toggle method:

```python
def _toggle_queue_panel(self):
    self.queue_panel.setVisible(not self.queue_panel.isVisible())
```

- [ ] **Step 3: Verify**

Run the app. Queue panel hidden by default. We'll wire the keyboard toggle in Task 20.

- [ ] **Step 4: Commit**

```bash
git add vlc_ranger/ui/queue_panel.py vlc_ranger/app.py
git commit -m "feat: queue panel as toggleable third pane"
```

---

### Task 19: Toolbar with `+ New Library`, `Rescan`, `Toggle Queue`, `Fullscreen`

**Files:**
- Modify: `vlc_ranger/app.py`

- [ ] **Step 1: Add `_build_toolbar` and call it from `__init__`**

In `vlc_ranger/app.py`, in `MainWindow.__init__`, after `self._build_ui()`:

```python
self._build_toolbar()
```

Add the method:

```python
def _build_toolbar(self):
    tb = QToolBar()
    self.addToolBar(tb)
    new_lib = QAction("+ New Library", self)
    new_lib.triggered.connect(self._new_library)
    tb.addAction(new_lib)

    rescan = QAction("⟳ Rescan current", self)
    rescan.triggered.connect(self._rescan_current_library)
    tb.addAction(rescan)

    self.queue_action = QAction("Queue", self)
    self.queue_action.setCheckable(True)
    self.queue_action.toggled.connect(self.queue_panel.setVisible)
    tb.addAction(self.queue_action)

    fullscreen = QAction("⛶ Fullscreen", self)
    fullscreen.triggered.connect(self._toggle_fullscreen)
    tb.addAction(fullscreen)

def _rescan_current_library(self):
    lib_id = self.browse.current_library_id
    if lib_id is not None:
        self._start_scan_library(lib_id)

def _toggle_fullscreen(self):
    if self.isFullScreen():
        self.showNormal()
    else:
        self.showFullScreen()
```

- [ ] **Step 2: Verify**

Toolbar appears at the top; buttons trigger the right actions.

- [ ] **Step 3: Commit**

```bash
git add vlc_ranger/app.py
git commit -m "feat: toolbar (new library, rescan, queue toggle, fullscreen)"
```

---

### Task 20: Hotkeys

**Files:**
- Modify: `vlc_ranger/app.py`

- [ ] **Step 1: Register `QShortcut`s in `MainWindow.__init__`**

After `self._build_toolbar()`:

```python
from PyQt6.QtGui import QShortcut, QKeySequence
QShortcut(QKeySequence("Space"),  self, activated=self._toggle_pause)
QShortcut(QKeySequence("F"),      self, activated=self._toggle_fullscreen)
QShortcut(QKeySequence("Esc"),    self, activated=lambda: self.isFullScreen() and self.showNormal())
QShortcut(QKeySequence("Ctrl+K"), self, activated=lambda: self.browse.search.setFocus())
QShortcut(QKeySequence("Ctrl+Q"), self, activated=lambda: self.queue_action.toggle())
QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.sidebar.setVisible(not self.sidebar.isVisible()))
QShortcut(QKeySequence("Backspace"), self, activated=self._backspace_up)
```

Add `_backspace_up`:

```python
def _backspace_up(self):
    """Forward Backspace to drill-down views that handle it."""
    current = self.browse.stack.currentWidget()
    if hasattr(current, "_go_up"):
        current._go_up()
```

- [ ] **Step 2: Verify**

Each hotkey behaves as labeled. Backspace inside TV drill moves up a level.

- [ ] **Step 3: Commit**

```bash
git add vlc_ranger/app.py
git commit -m "feat: hotkeys (Space/F/Esc/Ctrl+K/Ctrl+Q/Ctrl+B/Backspace)"
```

---

### Task 21: UI state persistence (`ui_state` table)

**Files:**
- Modify: `vlc_ranger/db.py`
- Modify: `vlc_ranger/app.py`

- [ ] **Step 1: Add `ui_state` getters/setters in `LibraryDB`**

```python
def ui_get(self, key: str) -> str | None:
    row = self.conn.execute("SELECT value FROM ui_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None

def ui_set(self, key: str, value: str) -> None:
    self.conn.execute(
        "INSERT INTO ui_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    self.conn.commit()
```

- [ ] **Step 2: Save on close, restore on open**

In `MainWindow.closeEvent`, add:

```python
self.db.ui_set("splitter.root", self.root_split.saveState().toHex().data().decode())
self.db.ui_set("splitter.center", self.center_split.saveState().toHex().data().decode())
self.db.ui_set("queue_panel_visible", "1" if self.queue_panel.isVisible() else "0")
self.db.ui_set("sidebar_visible", "1" if self.sidebar.isVisible() else "0")
if self.browse.current_library_id is not None:
    self.db.ui_set("selected_library_id", str(self.browse.current_library_id))
```

In `_restore_state` (at the end), add:

```python
def _restore(key, applier, decoder=str):
    raw = self.db.ui_get(key)
    if raw is not None:
        try:
            applier(decoder(raw))
        except Exception:
            pass

from PyQt6.QtCore import QByteArray
_restore("splitter.root", self.root_split.restoreState,
         lambda s: QByteArray.fromHex(s.encode()))
_restore("splitter.center", self.center_split.restoreState,
         lambda s: QByteArray.fromHex(s.encode()))
_restore("queue_panel_visible", lambda v: self.queue_action.setChecked(v == "1"))
_restore("sidebar_visible", lambda v: self.sidebar.setVisible(v == "1"))
_restore("selected_library_id",
         lambda v: self.browse.show_library(int(v)) if v else None)
```

- [ ] **Step 3: Verify**

Open the app, resize splitters, open the queue panel, select a library, close. Reopen — same state.

- [ ] **Step 4: Commit**

```bash
git add vlc_ranger/db.py vlc_ranger/app.py
git commit -m "feat: persist splitters, panel visibility, and selected library"
```

---

### Task 22: Global search across libraries with library-label column

**Files:**
- Modify: `vlc_ranger/db.py` (extend `search` to return library names)
- Modify: `vlc_ranger/ui/views/generic.py` (third column when used for search)
- Modify: `vlc_ranger/ui/browse.py`

- [ ] **Step 1: Add `search_with_library` to `LibraryDB`**

```python
def search_with_library(self, query: str, limit: int = 500) -> list[tuple[FileRow, str]]:
    """Like `search`, but each row is paired with the owning library's name."""
    if not query.strip():
        return []
    cols = """f.id, f.library_id, f.path, f.parent_dir, f.filename, f.ext, f.size,
              f.mtime, f.duration, f.title, f.year, f.series, f.season, f.episode,
              f.artist, f.album, f.track, COALESCE(l.name, '')"""
    sql = f"""
        SELECT {cols}
        FROM files_fts JOIN files f ON f.id = files_fts.rowid
        LEFT JOIN libraries l ON l.id = f.library_id
        WHERE files_fts MATCH ?
        ORDER BY rank LIMIT ?
    """
    try:
        out = []
        for r in self.conn.execute(sql, (query, limit)):
            out.append((FileRow(*r[:-1]), r[-1]))
        return out
    except sqlite3.OperationalError:
        # LIKE fallback
        like = f"%{query}%"
        sql2 = f"""SELECT {cols} FROM files f
                   LEFT JOIN libraries l ON l.id = f.library_id
                   WHERE f.filename LIKE ? OR f.parent_dir LIKE ?
                   ORDER BY f.filename LIMIT ?"""
        out = []
        for r in self.conn.execute(sql2, (like, like, limit)):
            out.append((FileRow(*r[:-1]), r[-1]))
        return out
```

- [ ] **Step 2: Teach `GenericView` to render an optional 3rd "Library" column**

Replace `set_rows` and the model setup in `vlc_ranger/ui/views/generic.py`:

```python
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
```

- [ ] **Step 3: Update `BrowseRouter._on_search`**

```python
def _on_search(self, text: str):
    if not text.strip():
        # restore the library's normal view if one was selected
        if self.current_library_id is not None:
            self.show_library(self.current_library_id)
        return
    rows = self.db.search_with_library(text)
    self.generic.set_search_rows(rows)
    self.stack.setCurrentWidget(self.generic)
```

- [ ] **Step 4: Verify**

Type into the search box — results from across all libraries show up with a Library column. Clear the box — view returns to the previously-selected library.

- [ ] **Step 5: Commit**

```bash
git add vlc_ranger/db.py vlc_ranger/ui/views/generic.py vlc_ranger/ui/browse.py
git commit -m "feat: global search across libraries with library-label column"
```

---

## Smoke-test checklist (after the final task)

Walk through these manually with `QT_QPA_PLATFORM=xcb python3 main.py`:

- [ ] Fresh DB: app launches, sidebar empty, "+ New Library…" works.
- [ ] Create Movies library, add a folder, scan completes, grid populates with title-cards.
- [ ] Create TV library on a folder with `SxxEyy` names: drill-down works; "Unsorted" appears for malformed names.
- [ ] Create Music library on `Artist/Album/Track` layout: drill-down works.
- [ ] Create Generic library: flat table.
- [ ] Right-click in any view: Play / Queue end / Queue front / Play next all work.
- [ ] Queue panel: Ctrl+Q toggles, items appear, Remove + Clear work, persists across restart.
- [ ] Hotkeys: Space, F, Esc, Ctrl+K, Ctrl+B, Backspace all behave.
- [ ] Splitter positions and selected library survive a restart.
- [ ] Global search: matches show with library column; clearing returns to previous library.
- [ ] Edit library — change name and type; verify reparse without rescan (existing files keep working).
- [ ] Delete library — files gone, queue and watch_state entries pointing at them are gone too (FK cascade).
- [ ] v0 → v1 migration: launch with a pre-existing `vlc-library` dir → renamed to `vlc-ranger`, `roots` rolled into "Default" library.

---

## Self-review notes

- **Spec coverage check.** Every section of the spec maps to at least one task:
  - Package layout → Tasks 1–6.
  - Data dir rename → Task 7.
  - Schema v1 + FTS5 → Task 9.
  - Filename matching → Task 8.
  - Scanner changes → Task 11.
  - UI: sidebar / browse router / editor / views / queue panel → Tasks 12–18.
  - Hotkeys → Task 20.
  - Persistence (`ui_state`) → Task 21.
  - Global search → Task 22.
  - Migration v0 → v1 → Task 10.
  - "What stays the same" → preserved throughout (VlcWidget moves but unchanged; scanner internals preserved in Task 11; queue semantics intact).
- **Nested-overlap warning** (spec open question): not in the plan because the spec marks it as a known sharp edge, not a requirement. Easy to revisit later if it bites.
- **`reparse_files` button** mentioned in the spec is intentionally minimal in the plan: editor's type change triggers a re-scan of the library's folders (which re-parses as a side effect via `Scanner` → `matching.parse`). A pure UPDATE-only re-parse without rewalking would be a small follow-up if rescanning huge libraries becomes annoying.
