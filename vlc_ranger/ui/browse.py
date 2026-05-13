from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from vlc_ranger.db import LibraryDB
from vlc_ranger.ui.views.generic import GenericView
from vlc_ranger.ui.views.movies import MoviesView


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
        self.movies = MoviesView()
        self.stack.addWidget(self.movies)

        for v in (self.generic, self.movies):
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
        if type_ == "movies":
            self.movies.set_rows(rows)
            self.stack.setCurrentWidget(self.movies)
        else:
            self.generic.set_rows(rows)
            self.stack.setCurrentWidget(self.generic)

    def _on_search(self, text: str):
        rows = self.db.search(text) if text.strip() else []
        self.generic.set_rows(rows)
        self.stack.setCurrentWidget(self.generic)
