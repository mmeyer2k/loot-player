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
