from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)

import qtawesome as qta


class QueuePanel(QWidget):
    play_next_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    remove_requested = pyqtSignal(list)        # list[int] of row indices
    play_at_requested = pyqtSignal(int)        # row index to play immediately

    def __init__(self, queue_model, parent=None):
        super().__init__(parent)
        self.view = QTableView()
        self.view.setModel(queue_model)
        self.view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.doubleClicked.connect(lambda idx: self.play_at_requested.emit(idx.row()))

        self.view.setDragEnabled(True)
        self.view.setAcceptDrops(True)
        self.view.setDropIndicatorShown(True)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.view.setDragDropOverwriteMode(False)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.verticalHeader().setVisible(False)

        next_btn = QPushButton(qta.icon("mdi6.skip-next"), "Next")
        clear_btn = QPushButton(qta.icon("mdi6.delete-sweep"), "Clear")
        remove_btn = QPushButton(qta.icon("mdi6.playlist-minus"), "Remove")
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
