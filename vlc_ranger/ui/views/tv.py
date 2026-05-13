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

    def set_library(self, library_id: int):
        self.library_id = library_id
        self.current_show = None
        self.current_season = None
        self._render_shows()

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
