from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QByteArray, QEvent, QSize, QTimer
from PyQt6.QtGui import QIcon, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QStatusBar, QSlider, QMessageBox,
    QStyle, QMenu,
)

import qtawesome as qta

from loot_player.cast import CastController
from loot_player.db import LibraryDB
from loot_player.models import FileRow, QueueModel
from loot_player.player import VlcWidget
from loot_player.scanner import Scanner
from loot_player.ui.library_editor import LibraryEditor
from loot_player.ui.library_tree import LibraryTree
from loot_player.ui.queue_panel import QueuePanel
from loot_player.version import __version__

APP_NAME = "loot-player"
APP_BRAND = "loot"
_PRIOR_APP_NAMES = ("vlc-ranger", "vlc-library")
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "loot.svg"


class ClickJumpSlider(QSlider):
    """QSlider where LMB anywhere on the trough jumps the value to that
    position (instead of the default page-step behavior). Drag continues
    to work — the slider stays held down until the button is released."""

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._update_from_pos(ev.position().x())
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_pos(ev.position().x())
            ev.accept()
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            ev.accept()
        else:
            super().mouseReleaseEvent(ev)

    def _update_from_pos(self, x: float):
        if self.width() <= 0:
            return
        val = QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(x), self.width()
        )
        self.setValue(val)
        self.sliderMoved.emit(val)


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    new = base / APP_NAME
    if new.exists():
        return new
    # Migration chain: pick up the most recent prior name we can find and
    # atomically rename the directory. Order matters — earliest entry wins.
    for prior in _PRIOR_APP_NAMES:
        old = base / prior
        if old.exists():
            os.rename(old, new)        # atomic on the same filesystem
            return new
    new.mkdir(parents=True, exist_ok=True)
    return new


class MainWindow(QMainWindow):
    _SHUFFLE_CYCLE = ["off", "within", "between"]
    _SHUFFLE_VISUALS = {
        # mode -> (icon color or None for default, tooltip)
        "off":     (None,      "Shuffle: off"),
        "within":  ("#FFC800", "Shuffle: within library"),
        "between": ("#0096FF", "Shuffle: across all libraries"),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_BRAND)
        self.resize(1400, 850)
        self.db = LibraryDB(data_dir() / "library.db")
        self.scanner: Optional[Scanner] = None
        self.current_file: Optional[FileRow] = None
        self.queue_model = QueueModel()
        self._cinema = False
        self._fullscreen = False
        self._shuffle_mode: str = "off"
        self._tree_pane_width = 300
        self._queue_pane_width = 300
        self._is_muted = False

        self._build_ui()

        QShortcut(QKeySequence("Space"),    self, activated=self._toggle_pause)
        QShortcut(QKeySequence("F"),        self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence("Esc"),      self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+K"),   self, activated=lambda: self.tree.search.setFocus())
        QShortcut(QKeySequence("Ctrl+M"),   self, activated=self._toggle_cinema_mode)

        self._restore_state()
        self._update_queue_visibility()
        self._ensure_tree_pane_width()

        self.tick = QTimer(self)
        self.tick.setInterval(500)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()

    # UI -------------------------------------------------------------------
    def _build_ui(self):
        # Column 1: search + library tree
        self.tree = LibraryTree(self.db)
        self.tree.play_requested.connect(self._play)
        self.tree.queue_front_requested.connect(self._add_to_queue_front)
        self.tree.play_next_requested.connect(self._queue_play_next)
        self.tree.new_library_requested.connect(self._new_library)
        self.tree.edit_library_requested.connect(self._edit_library)
        self.tree.rescan_library_requested.connect(self._rescan_library)
        self.tree.delete_library_requested.connect(self._delete_library)

        # Column 2: video + transport
        self.video = VlcWidget()
        self.video.double_clicked.connect(self._toggle_fullscreen)
        # libVLC events fire on a worker thread; force a queued connection so
        # the slot runs on the Qt main thread safely.
        self.video.loading_started.connect(
            lambda: self.buffering_indicator.setVisible(True),
            Qt.ConnectionType.QueuedConnection)
        self.video.playback_started.connect(
            lambda: self.buffering_indicator.setVisible(False),
            Qt.ConnectionType.QueuedConnection)
        # libVLC's audio output is created lazily on first play. Its initial
        # mute state can be inherited from the system audio backend (e.g. a
        # persisted PulseAudio sink-input mute), so once the output exists
        # we push the UI's state to libVLC to keep them in sync.
        self.video.playback_started.connect(
            self._sync_audio_state, Qt.ConnectionType.QueuedConnection)
        self.video.set_volume(80)
        self.video.set_mute(False)

        self.cast = CastController(self.video.instance, self)
        self.cast.start()
        self._active_cast = None
        self._active_cast_name: str = ""
        self._build_cast_overlay()

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
        self.queue_panel.play_at_requested.connect(self._play_queue_index)
        self.queue_model.queue_reordered.connect(self._persist_queue)
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
        root_split.splitterMoved.connect(self._on_root_split_moved)
        self.root_split = root_split
        self.setCentralWidget(root_split)

        # Status bar auto-hides whenever it has no message.
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.messageChanged.connect(self._update_status_visibility)
        self._update_status_visibility(sb.currentMessage())

    _BUTTON_SIZE = QSize(30, 26)
    _ICON_SIZE = QSize(18, 18)

    def _icon_button(self, mdi_name: str, slot=None, *, checkable: bool = False) -> QPushButton:
        """Make a uniform flat icon button using a Material Design Icon."""
        b = QPushButton()
        b.setIcon(qta.icon(mdi_name))
        b.setIconSize(self._ICON_SIZE)
        b.setFixedSize(self._BUTTON_SIZE)
        b.setFlat(True)
        if checkable:
            b.setCheckable(True)
        if slot is not None:
            b.clicked.connect(slot)
        return b

    def _build_transport_bar(self) -> QWidget:
        """Slim VLC-style bottom transport: seek slider on top row;
        prev/play/stop/next/shuffle | time | volume | fullscreen on the bottom row."""
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        # Top row: seek slider with click-to-jump.
        self.transport = ClickJumpSlider(Qt.Orientation.Horizontal)
        self.transport.setRange(0, 1000)
        self.transport.setMaximumHeight(16)
        self.transport.sliderMoved.connect(lambda v: self.video.set_position(v / 1000.0))
        col.addWidget(self.transport)

        # Bottom row.
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.prev_btn = self._icon_button("mdi6.skip-previous", slot=self._play_prev)
        self.play_pause_btn = self._icon_button("mdi6.play", slot=self._toggle_pause)
        self.stop_btn = self._icon_button("mdi6.stop", slot=self._stop)
        self.next_btn = self._icon_button("mdi6.skip-next", slot=self._play_next)
        self.shuffle_btn = self._icon_button("mdi6.shuffle", slot=self._cycle_shuffle,
                                             checkable=True)
        for b in (self.prev_btn, self.play_pause_btn, self.stop_btn,
                  self.next_btn, self.shuffle_btn):
            row.addWidget(b)

        # Buffering indicator — animated spinner + accented label so it's
        # impossible to miss.
        self.buffering_indicator = QWidget()
        bi_lay = QHBoxLayout(self.buffering_indicator)
        bi_lay.setContentsMargins(6, 0, 6, 0)
        bi_lay.setSpacing(6)
        self._buffering_icon = qta.IconWidget()
        self._buffering_icon.setIconSize(QSize(22, 22))
        self._buffering_icon.setFixedSize(QSize(24, 24))
        self._buffering_spin = qta.Spin(self._buffering_icon, interval=25, step=12)
        self._buffering_icon.setIcon(
            qta.icon("mdi6.loading", color="#00BFFF",
                     animation=self._buffering_spin)
        )
        bi_lay.addWidget(self._buffering_icon)
        self._buffering_label = QLabel("Loading…")
        self._buffering_label.setStyleSheet(
            "color: #00BFFF; font-weight: 600; letter-spacing: 0.5px;"
        )
        bi_lay.addWidget(self._buffering_label)
        self.buffering_indicator.setToolTip("Buffering…")
        self.buffering_indicator.setVisible(False)
        row.addWidget(self.buffering_indicator)

        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setStyleSheet("color: palette(mid); font-family: monospace;")
        row.addWidget(self.time_label)

        row.addStretch(1)

        self.mute_btn = self._icon_button("mdi6.volume-high", slot=self._toggle_mute)
        row.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setMaximumHeight(16)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.volume_slider)

        self.cast_btn = self._icon_button("mdi6.cast", slot=self._show_cast_menu)
        self.cast_btn.setToolTip("Cast to device")
        if not self.cast.available:
            self.cast_btn.setEnabled(False)
            self.cast_btn.setToolTip("Casting unavailable on this system")
        row.addWidget(self.cast_btn)

        self.cinema_btn = self._icon_button("mdi6.fit-to-screen-outline",
                                            slot=self._toggle_cinema_mode,
                                            checkable=True)
        self.cinema_btn.setToolTip("Cinema mode (Ctrl+M)")
        row.addWidget(self.cinema_btn)

        self.fs_btn = self._icon_button("mdi6.fullscreen", slot=self._toggle_fullscreen)
        self.fs_btn.setToolTip("Fullscreen (F)")
        row.addWidget(self.fs_btn)

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
        if v > 0 and self._is_muted:
            self._is_muted = False
            self.video.set_mute(False)
        self._update_mute_icon()

    def _toggle_mute(self):
        self._is_muted = not self._is_muted
        self.video.set_mute(self._is_muted)
        self._update_mute_icon()

    def _update_mute_icon(self):
        muted = self._is_muted or self.volume_slider.value() == 0
        name = "mdi6.volume-mute" if muted else "mdi6.volume-high"
        self.mute_btn.setIcon(qta.icon(name))

    def _sync_audio_state(self):
        # Called from MediaPlayerPlaying — audio output now exists, so push
        # the UI's source-of-truth state to libVLC.
        self.video.set_volume(self.volume_slider.value())
        self.video.set_mute(self._is_muted)

    def _update_play_pause_icon(self):
        name = "mdi6.pause" if self.video.is_playing() else "mdi6.play"
        self.play_pause_btn.setIcon(qta.icon(name))

    def _stop(self):
        self.video.stop()
        self.current_file = None
        self.setWindowTitle(APP_BRAND)
        self.tree.set_playing(None)

    # Casting ----------------------------------------------------------
    def _build_cast_overlay(self):
        """Translucent panel inside the video frame, shown while casting."""
        self.cast_overlay = QWidget(self.video)
        self.cast_overlay.setObjectName("CastOverlay")
        self.cast_overlay.setStyleSheet(
            "QWidget#CastOverlay { background-color: rgba(0, 0, 0, 215); }"
            " QLabel { color: white; background: transparent; }"
        )
        lay = QVBoxLayout(self.cast_overlay)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(16)

        self._cast_icon_label = QLabel()
        self._cast_icon_label.setPixmap(
            qta.icon("mdi6.cast-connected", color="white").pixmap(96, 96))
        self._cast_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._cast_icon_label)

        self._cast_overlay_text = QLabel("")
        self._cast_overlay_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._cast_overlay_text.font()
        font.setPointSize(max(font.pointSize() + 4, 16))
        self._cast_overlay_text.setFont(font)
        lay.addWidget(self._cast_overlay_text)

        self.cast_overlay.hide()
        self.video.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.video and event.type() == QEvent.Type.Resize:
            self.cast_overlay.setGeometry(0, 0, self.video.width(), self.video.height())
        return super().eventFilter(obj, event)

    @staticmethod
    def _renderer_name(item) -> str:
        try:
            n = item.name()
        except Exception:
            return "Unknown device"
        if isinstance(n, bytes):
            return n.decode("utf-8", "replace")
        return n or "Unknown device"

    def _show_cast_menu(self):
        menu = QMenu(self)
        devices = self.cast.devices()
        if devices:
            for item in devices:
                name = self._renderer_name(item)
                act = menu.addAction(name)
                act.setCheckable(True)
                act.setChecked(item is self._active_cast)
                act.triggered.connect(lambda _checked=False, it=item, nm=name:
                                      self._set_cast(it, nm))
        else:
            empty = menu.addAction("Searching for devices…")
            empty.setEnabled(False)
        if self._active_cast is not None:
            menu.addSeparator()
            stop_act = menu.addAction("Stop casting")
            stop_act.triggered.connect(lambda: self._set_cast(None, ""))
        # Drop the menu just below the cast button.
        pos = self.cast_btn.mapToGlobal(self.cast_btn.rect().bottomLeft())
        menu.exec(pos)

    def _set_cast(self, item, name: str):
        """Switch the renderer target. Pass (None, '') to revert to local."""
        cur = self.current_file
        was_playing = cur is not None
        self.video.stop()
        try:
            self.video.set_renderer(item)
        except Exception:
            pass
        self._active_cast = item
        self._active_cast_name = name
        if item is not None:
            self.cast_btn.setIcon(qta.icon("mdi6.cast-connected"))
            self.cast_btn.setToolTip(f"Casting to: {name}")
            self._cast_overlay_text.setText(f"Casting to {name}")
            self.cast_overlay.setGeometry(0, 0, self.video.width(), self.video.height())
            self.cast_overlay.show()
            self.cast_overlay.raise_()
        else:
            self.cast_btn.setIcon(qta.icon("mdi6.cast"))
            self.cast_btn.setToolTip("Cast to device")
            self.cast_overlay.hide()
        if was_playing and cur is not None:
            self._play(cur)

    def _cycle_shuffle(self):
        idx = self._SHUFFLE_CYCLE.index(self._shuffle_mode)
        self._shuffle_mode = self._SHUFFLE_CYCLE[(idx + 1) % len(self._SHUFFLE_CYCLE)]
        self._apply_shuffle_visual()
        self.db.ui_set("shuffle_mode", self._shuffle_mode)

    def _apply_shuffle_visual(self):
        color, tip = self._SHUFFLE_VISUALS[self._shuffle_mode]
        if color is None:
            self.shuffle_btn.setIcon(qta.icon("mdi6.shuffle"))
        else:
            self.shuffle_btn.setIcon(qta.icon("mdi6.shuffle", color=color))
        if not self.shuffle_btn.isEnabled():
            tip = f"{tip} — disabled while playing from queue"
        self.shuffle_btn.setToolTip(tip)
        self.shuffle_btn.setChecked(self._shuffle_mode != "off")

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
            self._ensure_tree_pane_width()
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
        # Keep the toolbar button's checked state in sync regardless of
        # whether this was triggered by the button itself or by Ctrl+M.
        if hasattr(self, "cinema_btn"):
            self.cinema_btn.setChecked(self._cinema)

    def _on_escape(self):
        if self._fullscreen:
            self._toggle_fullscreen()
        elif self._cinema:
            self._toggle_cinema_mode()

    def _update_queue_visibility(self):
        has_items = self.queue_model.rowCount() > 0
        self.queue_panel.setVisible(has_items)
        if has_items and hasattr(self, "root_split"):
            self._ensure_queue_pane_width()
        # Shuffle is meaningless while the queue is driving playback —
        # disable the button so the state is obvious, and re-apply the
        # tooltip so the disabled reason is visible.
        if hasattr(self, "shuffle_btn"):
            self.shuffle_btn.setEnabled(not has_items)
            self._apply_shuffle_visual()

    def _ensure_queue_pane_width(self):
        # QSplitter collapses a hidden child to width 0, and the saved state
        # carries that 0 across restarts. Re-showing the panel via
        # setVisible(True) alone leaves the pane at 0 width — give it real
        # space by stealing from the video column.
        sizes = self.root_split.sizes()
        if len(sizes) < 3 or sizes[2] > 0:
            return
        queue_w = self._queue_pane_width
        sizes[1] = max(200, sizes[1] - queue_w)
        sizes[2] = queue_w
        self.root_split.setSizes(sizes)

    def _ensure_tree_pane_width(self):
        # Same Qt-splitter-collapses-to-0 workaround as _ensure_queue_pane_width,
        # applied to the library tree on the left.
        sizes = self.root_split.sizes()
        if len(sizes) < 3 or sizes[0] > 0:
            return
        tree_w = self._tree_pane_width
        sizes[1] = max(200, sizes[1] - tree_w)
        sizes[0] = tree_w
        self.root_split.setSizes(sizes)

    def _on_root_split_moved(self, *_):
        sizes = self.root_split.sizes()
        if len(sizes) >= 3 and sizes[0] > 0:
            self._tree_pane_width = sizes[0]
        if len(sizes) >= 3 and sizes[2] > 0:
            self._queue_pane_width = sizes[2]

    # First-load --------------------------------------------------------
    def _restore_state(self):
        self.queue_model.append(self.db.load_queue())

        raw = self.db.ui_get("splitter.root")
        if raw is not None:
            try:
                self.root_split.restoreState(QByteArray.fromHex(raw.encode()))
            except Exception:
                pass

        mode = self.db.ui_get("shuffle_mode")
        if mode in self._SHUFFLE_CYCLE:
            self._shuffle_mode = mode
        self._apply_shuffle_visual()

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
            lambda total: (self.statusBar().showMessage(f"Indexed {total} file(s)", 10_000),
                           self.tree.reload())
        )
        self.scanner.start()

    # Queue ops --------------------------------------------------------
    def _add_to_queue_front(self, files: list[FileRow]):
        self.queue_model.prepend(files)
        self._persist_queue()

    def _queue_play_next(self, files: list[FileRow]):
        """Prepend the given files to the queue; start playback if idle."""
        self.queue_model.prepend(files)
        self._persist_queue()
        if self.current_file is None:
            self._play_next()

    def _persist_queue(self):
        self.db.save_queue([f.id for f in self.queue_model.files()])

    def _clear_queue(self):
        self.queue_model.clear_queue()
        self._persist_queue()

    def _play_next(self):
        """Transport ⏭: respect shuffle mode (off / within / between)."""
        f = self._take_next_for_mode()
        if f is None:
            return
        self._play(f)

    def _play_queue_index(self, row: int):
        files = self.queue_model.files()
        if not (0 <= row < len(files)):
            return
        f = files[row]
        self.queue_model.remove_indices([row])
        self._persist_queue()
        self._play(f)

    def _take_next_for_mode(self):
        """Return the next FileRow to play based on self._shuffle_mode, or None.

        Queue items always play in FIFO order — shuffle only affects the
        no-queue fallback. The shuffle button is disabled in the UI while
        the queue is non-empty, mirroring this contract."""
        # Queue is always FIFO regardless of shuffle mode.
        f = self.queue_model.take_next()
        self._persist_queue()
        if f:
            return f

        cur = self.current_file
        if cur is None:
            return None
        if self._shuffle_mode == "within":
            if cur.library_id is None:
                return None
            return self.db.random_file_in_library(cur.library_id, exclude_id=cur.id)
        if self._shuffle_mode == "between":
            return self.db.random_file_anywhere(exclude_id=cur.id)
        # mode == "off": alphabetical next in same folder
        if cur.library_id is None:
            return None
        return self.db.next_file_in_folder(cur.library_id, cur.parent_dir, cur.filename)

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
        self.setWindowTitle(f"{APP_BRAND} — {f.filename}")
        self.tree.set_playing(f.id)
        # Show the spinner immediately; libVLC's MediaPlayerPlaying event
        # will hide it once playback actually begins.
        self.buffering_indicator.setVisible(True)

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
        # Belt-and-suspenders: in case the VLC event slipped past, hide the
        # buffering indicator whenever playback is actually rolling.
        if self.video.is_playing() and self.buffering_indicator.isVisible():
            self.buffering_indicator.setVisible(False)
        if self.current_file and self.video.is_ended():
            nxt = self._take_next_for_mode()
            if nxt:
                self._play(nxt)
            else:
                self.current_file = None

    # cleanup ----------------------------------------------------------
    def closeEvent(self, ev):
        self.video.stop()
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(2000)
        self.cast.stop()
        self.db.ui_set("splitter.root", self.root_split.saveState().toHex().data().decode())
        super().closeEvent(ev)


def _icon_path() -> str:
    """Window-icon path. Honors LOOT_PLAYER_ICON (set by the AppImage AppRun),
    falling back to the in-repo SVG for source runs."""
    env = os.environ.get("LOOT_PLAYER_ICON")
    if env and Path(env).is_file():
        return env
    return str(_LOGO_PATH)


def selfcheck() -> int:
    """Smoke-test the runtime so a broken bundle never ships.

    Verifies the Qt platform plugin (xcb) loads, libVLC loads, and VLC plugins
    are discoverable (an empty/blank plugin path yields no audio-output
    modules). Returns 0 on success, 1 otherwise. Run in CI as `--selfcheck`
    under xvfb.
    """
    try:
        from PyQt6.QtWidgets import QApplication, QWidget
        import vlc
    except Exception as exc:  # pragma: no cover - import failure path
        print(f"selfcheck: import failed: {exc}", file=sys.stderr)
        return 1

    # An import alone never dlopens the Qt platform plugin (libqxcb.so) or its
    # bundled prerequisites — constructing a QApplication and showing a widget
    # does, which is exactly what a broken GUI bundle fails at. (A truly
    # unloadable plugin makes Qt abort the process, which still fails CI.)
    try:
        app = QApplication.instance() or QApplication(["loot-player"])
        w = QWidget()
        w.show()
        app.processEvents()
        w.close()
    except Exception as exc:  # pragma: no cover - platform-plugin failure path
        print(f"selfcheck: Qt platform init failed: {exc}", file=sys.stderr)
        return 1

    inst = vlc.Instance(["--quiet"])
    if inst is None:
        print("selfcheck: vlc.Instance() returned None (libVLC/plugins not loadable)",
              file=sys.stderr)
        return 1

    if not inst.audio_output_list_get():
        print("selfcheck: no VLC audio output modules found (PYTHON_VLC_MODULE_PATH wrong?)",
              file=sys.stderr)
        return 1

    version = (vlc.libvlc_get_version() or b"unknown").decode(errors="replace")
    print(f"selfcheck OK: loot-player {__version__}, libvlc {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]

    if "--version" in args:
        print(__version__)
        return 0

    if "--selfcheck" in args:
        return selfcheck()

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    icon = QIcon(_icon_path())
    app.setWindowIcon(icon)
    try:
        w = MainWindow()
    except RuntimeError as exc:
        print(f"loot-player: {exc}", file=sys.stderr)
        QMessageBox.critical(None, APP_BRAND, str(exc))
        return 1
    w.setWindowIcon(icon)
    w.show()
    w.video.attach()
    return app.exec()
