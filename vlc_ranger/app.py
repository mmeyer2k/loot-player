from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QStatusBar, QSlider, QMessageBox,
    QStyle, QMenu, QToolBar,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow, QueueModel
from vlc_ranger.player import VlcWidget
from vlc_ranger.scanner import Scanner

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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 850)
        self.db = LibraryDB(data_dir() / "library.db")
        self.scanner: Optional[Scanner] = None
        self.current_file: Optional[FileRow] = None

        self._build_ui()
        self._build_toolbar()
        self._restore_state()

        # Tick for transport slider + auto-advance
        self.tick = QTimer(self)
        self.tick.setInterval(500)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()

    # UI -------------------------------------------------------------------
    def _build_ui(self):
        from vlc_ranger.ui.sidebar import Sidebar
        from vlc_ranger.ui.browse import BrowseRouter

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

        self.queue_model = QueueModel()

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

        from vlc_ranger.ui.queue_panel import QueuePanel
        self.queue_panel = QueuePanel(self.queue_model)
        self.queue_panel.play_next_requested.connect(self._play_next_from_queue)
        self.queue_panel.clear_requested.connect(self._clear_queue)
        self.queue_panel.remove_requested.connect(self.queue_model.remove_indices)
        self.queue_panel.remove_requested.connect(lambda *_: self._persist_queue())
        self.queue_panel.setVisible(False)         # toggled by Ctrl+Q / toolbar button in later tasks

        root_split = QSplitter(Qt.Orientation.Horizontal)
        root_split.addWidget(self.sidebar)
        root_split.addWidget(center_split)
        root_split.addWidget(self.queue_panel)
        root_split.setSizes([260, 880, 260])
        self.root_split = root_split
        self.setCentralWidget(root_split)
        self.setStatusBar(QStatusBar())

        self.sidebar.reload(self.db.list_libraries())

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

    # First-load --------------------------------------------------------
    def _restore_state(self):
        self.queue_model.append(self.db.load_queue())

    # Library handlers --------------------------------------------------
    def _new_library(self):
        from vlc_ranger.ui.library_editor import LibraryEditor
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
        from vlc_ranger.ui.library_editor import LibraryEditor
        libs = {i: (n, t) for (i, n, t) in self.db.list_libraries()}
        name, type_ = libs.get(lib_id, ("", "generic"))
        folders = [p for (_, p) in self.db.library_folders(lib_id)]
        dlg = LibraryEditor(self, initial_name=name, initial_type=type_,
                            initial_folders=folders)
        if dlg.exec() and dlg.result_data:
            new_name, new_type, new_folders = dlg.result_data
            old_set = set(folders)
            new_set = set(new_folders)
            added = [f for f in new_folders if f not in old_set]
            removed = [f for f in folders if f not in new_set]
            self.db.update_library(lib_id, new_name, new_type)
            for f in removed:
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

    # Queue ops --------------------------------------------------------
    def _add_to_queue_end(self, files: list[FileRow]):
        self.queue_model.append(files)
        self._persist_queue()

    def _add_to_queue_front(self, files: list[FileRow]):
        self.queue_model.prepend(files)
        self._persist_queue()

    def _play_next(self, files: list[FileRow]):
        # insert right after the currently-playing index (top of queue is 0)
        self.queue_model.insert_after_current(files, -1)  # -1 => insert at position 0
        self._persist_queue()

    def _persist_queue(self):
        self.db.save_queue([f.id for f in self.queue_model.files()])

    def _clear_queue(self):
        self.queue_model.clear_queue()
        self._persist_queue()

    def _play_next_from_queue(self):
        f = self.queue_model.take_next()
        self._persist_queue()
        if f:
            self._play(f)

    # Playback ---------------------------------------------------------
    def _play(self, f: FileRow):
        # ensure VLC is bound to the now-shown video widget
        self.video.attach()
        self.video.play_path(f.path)
        self.current_file = f
        self.now_playing.setText(f"▶ {f.filename}  —  {f.parent_dir}")

    def _toggle_pause(self):
        self.video.toggle_pause()

    def _on_tick(self):
        # update transport slider
        pos = self.video.position()
        if not self.transport.isSliderDown():
            self.transport.setValue(int(pos * 1000))
        # auto-advance when current ends
        if self.current_file and self.video.is_ended():
            self.current_file = None
            self._play_next_from_queue()

    # cleanup ----------------------------------------------------------
    def closeEvent(self, ev):
        self.video.stop()
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(2000)
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    # winId() is valid now — bind libVLC's output to the video widget.
    w.video.attach()
    sys.exit(app.exec())
