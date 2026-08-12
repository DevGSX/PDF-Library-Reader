"""Dialog for previewing a book's cover and editing its metadata:
title, author, series, genre(s), language(s), annotation, favorite and status.

Genre and Language are both checkable multi-select dropdowns (a book can
have more than one of either), each with a "Custom" checkbox that adds one
more freely-typed value on top of whatever's picked from the list. Multiple
values are joined with '_' -- e.g. "Science Fiction_Fantasy" or
"English_Bulgarian".
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
from .multi_select_combo import MultiSelectComboBox
from .presets import GENRE_PRESETS, LANGUAGE_PRESETS
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
        self.resize(440, 660)
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

        # Genre: checkable multi-select dropdown (a book can be more than one
        # genre), plus an optional extra custom genre typed on top of that.
        self.genre_combo = MultiSelectComboBox()
        self.genre_combo.add_items(GENRE_PRESETS)
        self.genre_custom_check = QCheckBox("Custom")
        self.genre_custom_check.toggled.connect(self._on_genre_custom_toggled)
        self.genre_custom_edit = QLineEdit()
        self.genre_custom_edit.setPlaceholderText("Add another genre...")
        self.genre_custom_edit.hide()
        genre_row = QHBoxLayout()
        genre_row.addWidget(self.genre_combo, stretch=1)
        genre_row.addWidget(self.genre_custom_edit, stretch=1)
        genre_row.addWidget(self.genre_custom_check)

        # Language: same treatment -- a book can have more than one.
        self.language_combo = MultiSelectComboBox()
        self.language_combo.add_items(LANGUAGE_PRESETS)
        self.language_custom_check = QCheckBox("Custom")
        self.language_custom_check.toggled.connect(self._on_language_custom_toggled)
        self.language_custom_edit = QLineEdit()
        self.language_custom_edit.setPlaceholderText("Add another language...")
        self.language_custom_edit.hide()
        language_row = QHBoxLayout()
        language_row.addWidget(self.language_combo, stretch=1)
        language_row.addWidget(self.language_custom_edit, stretch=1)
        language_row.addWidget(self.language_custom_check)

        self.status_combo = QComboBox()
        for value, label in STATUS_OPTIONS:
            self.status_combo.addItem(label, value)
        self.annotation_edit = QTextEdit()
        self.annotation_edit.setPlaceholderText("Notes about this book...")
        self.annotation_edit.setFixedHeight(90)

        form.addRow("Title", self.title_edit)
        form.addRow("Author", self.author_edit)
        form.addRow("Series", self.series_edit)
        form.addRow("Genre", genre_row)
        form.addRow("Language", language_row)
        form.addRow("Status", self.status_combo)
        form.addRow("Annotation", self.annotation_edit)
        layout.addLayout(form)

        hint = QLabel(
            "Saving renames the file to \u201cTitle - Author - Series - Genre - "
            "Language.pdf\u201d, so the info travels with it if you move or copy it "
            "to another device. A book with more than one genre or language "
            "shows as e.g. \u201cScience Fiction_Fantasy\u201d or "
            "\u201cEnglish_Bulgarian\u201d, and is found when searching for any one "
            "of them."
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

    def _on_genre_custom_toggled(self, checked):
        self.genre_custom_edit.setVisible(checked)

    def _on_language_custom_toggled(self, checked):
        self.language_custom_edit.setVisible(checked)

    def load_book(self, book_id):
        self.book_id = book_id
        book = self.db.get_book(book_id)
        if not book:
            return
        self.setWindowTitle(f"Book Details \u2014 {book['title']}")

        pixmap, _is_corrupted = ensure_thumbnail(book_id, book["filepath"])
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
        self.annotation_edit.setPlainText(book["annotation"] or "")

        self._load_multi_value(
            book["genre"] or "", GENRE_PRESETS,
            self.genre_combo, self.genre_custom_check, self.genre_custom_edit,
        )
        self._on_genre_custom_toggled(self.genre_custom_check.isChecked())

        self._load_multi_value(
            book["language"] or "", LANGUAGE_PRESETS,
            self.language_combo, self.language_custom_check, self.language_custom_edit,
        )
        self._on_language_custom_toggled(self.language_custom_check.isChecked())

        status = book["status"] or "unread"
        idx = self.status_combo.findData(status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.favorite_btn.setChecked(bool(book["is_favorite"]))
        self.favorite_btn.setText("\u2605 Favorited" if book["is_favorite"] else "\u2606 Favorite")

    @staticmethod
    def _load_multi_value(raw_value, presets, combo, custom_check, custom_edit):
        """Split a '_'-joined value: preset tokens get checked in the
        dropdown, anything else goes into the Custom field (joined back with
        '_' if there's more than one non-preset value)."""
        tokens = [t.strip() for t in raw_value.split("_") if t.strip()]
        preset_set = set(presets)
        preset_tokens = [t for t in tokens if t in preset_set]
        custom_tokens = [t for t in tokens if t not in preset_set]
        combo.set_checked_items(preset_tokens)
        if custom_tokens:
            custom_check.setChecked(True)
            custom_edit.setText("_".join(custom_tokens))
        else:
            custom_check.setChecked(False)
            custom_edit.setText("")

    def _toggle_favorite(self):
        if self.book_id is None:
            return
        self.db.toggle_favorite(self.book_id)
        book = self.db.get_book(self.book_id)
        self.favorite_btn.setChecked(bool(book["is_favorite"]))
        self.favorite_btn.setText("\u2605 Favorited" if book["is_favorite"] else "\u2606 Favorite")

    @staticmethod
    def _combine_multi_value(combo, custom_check, custom_edit):
        parts = list(combo.checked_items())
        if custom_check.isChecked():
            custom = custom_edit.text().strip()
            if custom:
                parts.extend(p.strip() for p in custom.split("_") if p.strip())
        # de-duplicate while preserving order
        seen = set()
        ordered = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return "_".join(ordered)

    def _current_genre(self):
        return self._combine_multi_value(self.genre_combo, self.genre_custom_check, self.genre_custom_edit)

    def _current_language(self):
        return self._combine_multi_value(self.language_combo, self.language_custom_check, self.language_custom_edit)

    def _save(self):
        if self.book_id is None:
            return
        try:
            self.db.update_metadata(
                self.book_id,
                title=self.title_edit.text().strip() or "Untitled",
                author=self.author_edit.text().strip(),
                series=self.series_edit.text().strip(),
                genre=self._current_genre(),
                language=self._current_language(),
                annotation=self.annotation_edit.toPlainText().strip(),
            )
            self.db.set_status(self.book_id, self.status_combo.currentData())
            renamed, info = sync_filename(self.db, self.book_id)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Couldn't save changes",
                f"Something went wrong while saving:\n{exc}",
            )
            return  # leave the dialog open so nothing is lost

        if info and not renamed:
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
