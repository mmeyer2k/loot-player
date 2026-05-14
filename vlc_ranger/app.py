from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QByteArray, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QStatusBar, QSlider, QMessageBox,
    QStyle,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow, QueueModel
from vlc_ranger.player import VlcWidget
from vlc_ranger.scanner import Scanner
from vlc_ranger.ui.library_editor import LibraryEditor
from vlc_ranger.ui.library_tree import LibraryTree
from vlc_ranger.ui.queue_panel import QueuePanel

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
        self.queue_model = QueueModel()
        self._cinema = False
        self._fullscreen = False

        self._build_ui()

        QShortcut(QKeySequence("Space"),    self, activated=self._toggle_pause)
        QShortcut(QKeySequence("F"),        self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence("Esc"),      self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+K"),   self, activated=lambda: self.tree.search.setFocus())
        QShortcut(QKeySequence("Ctrl+M"),   self, activated=self._toggle_cinema_mode)

        self._restore_state()
        self._update_queue_visibility()

        self.tick = QTimer(self)
        self.tick.setInterval(500)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()

    # UI -------------------------------------------------------------------
    def _build_ui(self):
        # Column 1: search + library tree
        self.tree = LibraryTree(self.db)
        self.tree.play_requested.connect(self._play)
        self.tree.queue_end_requested.connect(self._add_to_queue_end)
        self.tree.queue_front_requested.connect(self._add_to_queue_front)
        self.tree.play_next_requested.connect(self._queue_play_next)
        self.tree.new_library_requested.connect(self._new_library)
        self.tree.edit_library_requested.connect(self._edit_library)
        self.tree.rescan_library_requested.connect(self._rescan_library)
        self.tree.delete_library_requested.connect(self._delete_library)

        # Column 2: video + transport
        self.video = VlcWidget()
        self.video.double_clicked.connect(self._toggle_fullscreen)
        self.video.set_volume(80)

        self.controls_wrap = self._build_transport_bar()

        video_wrap = QWidget()
        vw = QVBoxLayout(video_wrap)
        vw.setContentsMargins(0, 0, 0, 0)
        vw.addWidget(self.video, 1)
        vw.addWidget(self.controls_wrap)

        # Column 3: queue (auto-hidden when empty)
        self.queue_panel = QueuePanel(self.queue_model)
        self.queue_panel.play_next_requested.connect(self._play_next)
        self.queue_panel.clear_requested.connect(self._clear_queue)
        self.queue_panel.remove_requested.connect(self.queue_model.remove_indices)
        self.queue_panel.remove_requested.connect(lambda *_: self._persist_queue())
        self.queue_panel.setVisible(False)

        # Auto-show/hide queue column based on queue contents.
        self.queue_model.rowsInserted.connect(lambda *_: self._update_queue_visibility())
        self.queue_model.rowsRemoved.connect(lambda *_: self._update_queue_visibility())
        self.queue_model.modelReset.connect(self._update_queue_visibility)

        root_split = QSplitter(Qt.Orientation.Horizontal)
        root_split.addWidget(self.tree)
        root_split.addWidget(video_wrap)
        root_split.addWidget(self.queue_panel)
        root_split.setSizes([300, 800, 300])
        root_split.setStretchFactor(0, 0)
        root_split.setStretchFactor(1, 1)
        root_split.setStretchFactor(2, 0)
        self.root_split = root_split
        self.setCentralWidget(root_split)

        # Status bar auto-hides whenever it has no message.
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.messageChanged.connect(self._update_status_visibility)
        self._update_status_visibility(sb.currentMessage())

    def _build_transport_bar(self) -> QWidget:
        """Slim VLC-style bottom transport: seek slider on top row;
        play/stop/next + time + volume + fullscreen on the bottom row."""
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        # Top row: seek slider.
        self.transport = QSlider(Qt.Orientation.Horizontal)
        self.transport.setRange(0, 1000)
        self.transport.setMaximumHeight(16)
        self.transport.sliderMoved.connect(lambda v: self.video.set_position(v / 1000.0))
        col.addWidget(self.transport)

        # Bottom row: transport buttons | time | spacer | volume | fullscreen.
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        def slim_button(icon_pix=None, text=None, slot=None) -> QPushButton:
            b = QPushButton()
            if icon_pix is not None:
                b.setIcon(self.style().standardIcon(icon_pix))
            if text is not None:
                b.setText(text)
            b.setFlat(True)
            b.setFixedHeight(24)
            if slot is not None:
                b.clicked.connect(slot)
            return b

        self.prev_btn = slim_button(QStyle.StandardPixmap.SP_MediaSkipBackward, slot=self._play_prev)
        self.play_pause_btn = slim_button(QStyle.StandardPixmap.SP_MediaPlay, slot=self._toggle_pause)
        self.stop_btn = slim_button(QStyle.StandardPixmap.SP_MediaStop, slot=self._stop)
        self.next_btn = slim_button(QStyle.StandardPixmap.SP_MediaSkipForward, slot=self._play_next)
        for b in (self.prev_btn, self.play_pause_btn, self.stop_btn, self.next_btn):
            b.setFixedWidth(28)
            row.addWidget(b)

        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setStyleSheet("color: palette(mid); font-family: monospace;")
        row.addWidget(self.time_label)

        row.addStretch(1)

        self.mute_btn = slim_button(QStyle.StandardPixmap.SP_MediaVolume, slot=self._toggle_mute)
        self.mute_btn.setFixedWidth(28)
        row.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setMaximumHeight(16)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.volume_slider)

        fs_btn = slim_button(text="⛶", slot=self._toggle_fullscreen)
        fs_btn.setFixedWidth(28)
        row.addWidget(fs_btn)

        col.addLayout(row)
        return wrap

    @staticmethod
    def _format_time(ms: int) -> str:
        if ms is None or ms < 0:
            return "--:--"
        s = ms // 1000
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_volume_changed(self, v: int):
        self.video.set_volume(v)
        if v > 0 and self.video.get_mute():
            self.video.set_mute(False)
        self._update_mute_icon()

    def _toggle_mute(self):
        self.video.set_mute(not self.video.get_mute())
        self._update_mute_icon()

    def _update_mute_icon(self):
        muted = self.video.get_mute() or self.video.get_volume() == 0
        pix = (QStyle.StandardPixmap.SP_MediaVolumeMuted if muted
               else QStyle.StandardPixmap.SP_MediaVolume)
        self.mute_btn.setIcon(self.style().standardIcon(pix))

    def _update_play_pause_icon(self):
        pix = (QStyle.StandardPixmap.SP_MediaPause if self.video.is_playing()
               else QStyle.StandardPixmap.SP_MediaPlay)
        self.play_pause_btn.setIcon(self.style().standardIcon(pix))

    def _stop(self):
        self.video.stop()
        self.current_file = None
        self.setWindowTitle(APP_NAME)
        self.video.setToolTip("")

    def _apply_chrome_visibility(self):
        """Apply current cinema/fullscreen state to all chrome widgets.

        Cinema mode hides the left and right side panels only, so the video
        gets the full window width with the transport bar still visible.
        Fullscreen additionally hides the transport bar and status bar."""
        hide_sides = self._cinema or self._fullscreen
        hide_bottom = self._fullscreen
        self.tree.setVisible(not hide_sides)
        self.controls_wrap.setVisible(not hide_bottom)
        if hide_sides:
            self.queue_panel.setVisible(False)
        else:
            self._update_queue_visibility()
        if hide_bottom:
            self.statusBar().setVisible(False)
        else:
            self._update_status_visibility(self.statusBar().currentMessage())

    def _update_status_visibility(self, message: str):
        if self._fullscreen:
            return
        self.statusBar().setVisible(bool(message))

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self._apply_chrome_visibility()
        if self._fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()

    def _toggle_cinema_mode(self):
        self._cinema = not self._cinema
        self._apply_chrome_visibility()

    def _on_escape(self):
        if self._fullscreen:
            self._toggle_fullscreen()
        elif self._cinema:
            self._toggle_cinema_mode()

    def _update_queue_visibility(self):
        self.queue_panel.setVisible(self.queue_model.rowCount() > 0)

    # First-load --------------------------------------------------------
    def _restore_state(self):
        self.queue_model.append(self.db.load_queue())

        raw = self.db.ui_get("splitter.root")
        if raw is not None:
            try:
                self.root_split.restoreState(QByteArray.fromHex(raw.encode()))
            except Exception:
                pass

    # Library handlers --------------------------------------------------
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
            self.tree.reload()
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
            self.tree.reload()
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
            self.tree.reload()

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
                           self.tree.reload())
        )
        self.scanner.start()

    # Queue ops --------------------------------------------------------
    def _add_to_queue_end(self, files: list[FileRow]):
        self.queue_model.append(files)
        self._persist_queue()

    def _add_to_queue_front(self, files: list[FileRow]):
        self.queue_model.prepend(files)
        self._persist_queue()

    def _queue_play_next(self, files: list[FileRow]):
        self.queue_model.prepend(files)
        self._persist_queue()

    def _persist_queue(self):
        self.db.save_queue([f.id for f in self.queue_model.files()])

    def _clear_queue(self):
        self.queue_model.clear_queue()
        self._persist_queue()

    def _play_next(self):
        """Transport ⏭: queue first, else next folder neighbor."""
        f = self.queue_model.take_next()
        self._persist_queue()
        if f:
            self._play(f)
            return
        cur = self.current_file
        if cur is None or cur.library_id is None:
            return
        nxt = self.db.next_file_in_folder(cur.library_id, cur.parent_dir, cur.filename)
        if nxt:
            self._play(nxt)

    def _play_prev(self):
        """Transport ⏮: restart current if > 3s in, else previous folder neighbor."""
        cur = self.current_file
        if cur is None:
            return
        if self.video.get_time() > 3000:
            self.video.set_position(0.0)
            return
        if cur.library_id is None:
            return
        prv = self.db.prev_file_in_folder(cur.library_id, cur.parent_dir, cur.filename)
        if prv:
            self._play(prv)

    # Playback ---------------------------------------------------------
    def _play(self, f: FileRow):
        self.video.attach()
        self.video.play_path(f.path)
        self.current_file = f
        self.setWindowTitle(f"{APP_NAME} — {f.filename}")
        self.video.setToolTip(f"{f.filename}\n{f.parent_dir}")

    def _toggle_pause(self):
        self.video.toggle_pause()

    def _on_tick(self):
        pos = self.video.position()
        if not self.transport.isSliderDown():
            self.transport.setValue(int(pos * 1000))
        cur = self.video.get_time()
        total = self.video.get_length()
        self.time_label.setText(f"{self._format_time(cur)} / {self._format_time(total)}")
        self._update_play_pause_icon()
        if self.current_file and self.video.is_ended():
            self.current_file = None
            self._play_next()

    # cleanup ----------------------------------------------------------
    def closeEvent(self, ev):
        self.video.stop()
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(2000)
        self.db.ui_set("splitter.root", self.root_split.saveState().toHex().data().decode())
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    w.video.attach()
    sys.exit(app.exec())
