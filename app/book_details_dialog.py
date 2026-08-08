"""Dialog for previewing a book's cover and editing its metadata:
title, author, series, language, annotation, favorite and reading status.
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .file_naming import sync_filename
from .thumbnails import ensure_thumbnail
from .widgets import human_size

STATUS_OPTIONS = [("unread", "Unread"), ("reading", "Reading"), ("finished", "Finished")]


class BookDetailsDialog(QDialog):
    book_updated = Signal()       # emitted after Save, so the caller can refresh its view
    open_requested = Signal(int)  # emitted when "Open Book" is clicked

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.book_id = None
        self.setWindowTitle("Book Details")
        self.resize(420, 600)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.cover_label = QLabel()
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setFixedHeight(190)
        layout.addWidget(self.cover_label)

        self.meta_label = QLabel()
        self.meta_label.setAlignment(Qt.AlignCenter)
        self.meta_label.setStyleSheet("color: #888;")
        layout.addWidget(self.meta_label)

        self.filename_label = QLabel()
        self.filename_label.setAlignment(Qt.AlignCenter)
        self.filename_label.setWordWrap(True)
        self.filename_label.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(self.filename_label)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.series_edit = QLineEdit()
        self.language_edit = QLineEdit()
        self.language_edit.setPlaceholderText("e.g. English, Spanish, French...")
        self.status_combo = QComboBox()
        for value, label in STATUS_OPTIONS:
            self.status_combo.addItem(label, value)
        self.annotation_edit = QTextEdit()
        self.annotation_edit.setPlaceholderText("Notes about this book...")
        self.annotation_edit.setFixedHeight(90)

        form.addRow("Title", self.title_edit)
        form.addRow("Author", self.author_edit)
        form.addRow("Series", self.series_edit)
        form.addRow("Language", self.language_edit)
        form.addRow("Status", self.status_combo)
        form.addRow("Annotation", self.annotation_edit)
        layout.addLayout(form)

        hint = QLabel(
            "Saving renames the file to \u201cTitle * Author * Series.pdf\u201d, so the "
            "info travels with it if you move or copy it to another device."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        self.favorite_btn = QPushButton("\u2606 Favorite")
        self.favorite_btn.setCheckable(True)
        self.favorite_btn.clicked.connect(self._toggle_favorite)
        btn_row.addWidget(self.favorite_btn)

        btn_row.addStretch()

        open_btn = QPushButton("Open Book")
        open_btn.clicked.connect(self._open_book)
        btn_row.addWidget(open_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def load_book(self, book_id):
        self.book_id = book_id
        book = self.db.get_book(book_id)
        if not book:
            return
        self.setWindowTitle(f"Book Details \u2014 {book['title']}")

        pixmap = ensure_thumbnail(book_id, book["filepath"])
        self.cover_label.setPixmap(
            pixmap.scaled(140, 190, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

        try:
            size = os.path.getsize(book["filepath"])
        except OSError:
            size = -1
        meta_bits = [human_size(size)]
        if book["page_count"]:
            meta_bits.append(f"{book['page_count']} pages")
        self.meta_label.setText(" \u00b7 ".join(meta_bits))
        self.filename_label.setText(f"File: {os.path.basename(book['filepath'])}")

        self.title_edit.setText(book["title"] or "")
        self.author_edit.setText(book["author"] or "")
        self.series_edit.setText(book["series"] or "")
        self.language_edit.setText(book["language"] or "")
        self.annotation_edit.setPlainText(book["annotation"] or "")

        status = book["status"] or "unread"
        idx = self.status_combo.findData(status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.favorite_btn.setChecked(bool(book["is_favorite"]))
        self.favorite_btn.setText("\u2605 Favorited" if book["is_favorite"] else "\u2606 Favorite")

    def _toggle_favorite(self):
        if self.book_id is None:
            return
        self.db.toggle_favorite(self.book_id)
        book = self.db.get_book(self.book_id)
        self.favorite_btn.setChecked(bool(book["is_favorite"]))
        self.favorite_btn.setText("\u2605 Favorited" if book["is_favorite"] else "\u2606 Favorite")

    def _save(self):
        if self.book_id is None:
            return
        self.db.update_metadata(
            self.book_id,
            title=self.title_edit.text().strip() or "Untitled",
            author=self.author_edit.text().strip(),
            series=self.series_edit.text().strip(),
            language=self.language_edit.text().strip(),
            annotation=self.annotation_edit.toPlainText().strip(),
        )
        self.db.set_status(self.book_id, self.status_combo.currentData())

        _renamed, info = sync_filename(self.db, self.book_id)
        if info and not _renamed:
            # sync_filename returns (False, error_message) only when a rename
            # was needed but failed; (False, None) means nothing needed renaming.
            QMessageBox.warning(
                self,
                "Couldn't rename file",
                f"Your changes were saved, but the file on disk couldn't be renamed "
                f"to match:\n{info}",
            )

        self.book_updated.emit()
        self.close()

    def _open_book(self):
        if self.book_id is not None:
            self.open_requested.emit(self.book_id)
        self.close()
