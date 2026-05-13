from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QListView, QMenu, QPushButton,
    QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from vlc_ranger.db import LibraryDB
from vlc_ranger.models import FileRow


class MusicView(QWidget):
    play_requested = pyqtSignal(object)
    queue_end_requested = pyqtSignal(list)
    queue_front_requested = pyqtSignal(list)
    play_next_requested = pyqtSignal(list)

    def __init__(self, db: LibraryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self.library_id: int | None = None
        self.current_artist: str | None = None
        self.current_album: str | None = None

        self.breadcrumb = QLabel("")
        self.back = QPushButton("← Back")
        self.back.clicked.connect(self._go_up)

        top = QVBoxLayout()
        top.addWidget(self.back)
        top.addWidget(self.breadcrumb)

        self.stack = QStackedWidget()
        self.artists = QListView()
        self.artists_model = QStandardItemModel()
        self.artists.setModel(self.artists_model)
        self.artists.setViewMode(QListView.ViewMode.IconMode)
        self.artists.setResizeMode(QListView.ResizeMode.Adjust)
        self.artists.doubleClicked.connect(self._click_artist)

        self.albums = QListView()
        self.albums_model = QStandardItemModel()
        self.albums.setModel(self.albums_model)
        self.albums.doubleClicked.connect(self._click_album)

        self.tracks = QTableView()
        self.tracks_model = QStandardItemModel()
        self.tracks_model.setHorizontalHeaderLabels(["#", "Title", "File"])
        self.tracks.setModel(self.tracks_model)
        self.tracks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tracks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tracks.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tracks.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tracks.doubleClicked.connect(self._click_track)
        self.tracks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tracks.customContextMenuRequested.connect(self._track_menu)
        self._track_rows: list[FileRow] = []

        self.stack.addWidget(self.artists)
        self.stack.addWidget(self.albums)
        self.stack.addWidget(self.tracks)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.stack, 1)

    def set_library(self, library_id: int):
        self.library_id = library_id
        self.current_artist = None
        self.current_album = None
        self._render_artists()

    def _render_artists(self):
        self.stack.setCurrentWidget(self.artists)
        self.breadcrumb.setText("Music")
        self.artists_model.clear()
        for artist, count in self.db.music_artists(self.library_id):
            item = QStandardItem(f"{artist}\n({count})")
            item.setData(artist, Qt.ItemDataRole.UserRole)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.artists_model.appendRow(item)

    def _render_albums(self):
        self.stack.setCurrentWidget(self.albums)
        self.breadcrumb.setText(f"Music / {self.current_artist}")
        self.albums_model.clear()
        for album, count in self.db.music_albums(self.library_id, self.current_artist):
            item = QStandardItem(f"{album} ({count})")
            item.setData(album, Qt.ItemDataRole.UserRole)
            self.albums_model.appendRow(item)

    def _render_tracks(self):
        self.stack.setCurrentWidget(self.tracks)
        self.breadcrumb.setText(f"Music / {self.current_artist} / {self.current_album}")
        self._track_rows = self.db.music_tracks(self.library_id,
                                                self.current_artist,
                                                self.current_album)
        self.tracks_model.setRowCount(0)
        for f in self._track_rows:
            tr = "" if f.track is None else str(f.track)
            self.tracks_model.appendRow([
                QStandardItem(tr),
                QStandardItem(f.title or f.filename),
                QStandardItem(f.filename),
            ])

    def _click_artist(self, idx):
        artist = self.artists_model.itemFromIndex(idx).data(Qt.ItemDataRole.UserRole)
        self.current_artist = artist
        self.current_album = None
        self._render_albums()

    def _click_album(self, idx):
        album = self.albums_model.itemFromIndex(idx).data(Qt.ItemDataRole.UserRole)
        self.current_album = album
        self._render_tracks()

    def _click_track(self, idx):
        if 0 <= idx.row() < len(self._track_rows):
            self.play_requested.emit(self._track_rows[idx.row()])

    def _go_up(self):
        if self.stack.currentWidget() is self.tracks:
            self._render_albums()
        elif self.stack.currentWidget() is self.albums:
            self._render_artists()

    def _track_menu(self, point):
        rows = sorted({i.row() for i in self.tracks.selectionModel().selectedRows()})
        sel = [self._track_rows[r] for r in rows]
        if not sel:
            return
        m = QMenu(self)
        m.addAction("▶ Play now",        lambda: self.play_requested.emit(sel[0]))
        m.addAction("Queue (end)",       lambda: self.queue_end_requested.emit(sel))
        m.addAction("Queue (front)",     lambda: self.queue_front_requested.emit(sel))
        m.addAction("Play next",         lambda: self.play_next_requested.emit(sel))
        m.exec(self.tracks.viewport().mapToGlobal(point))
