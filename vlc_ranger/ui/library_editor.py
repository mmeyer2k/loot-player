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
