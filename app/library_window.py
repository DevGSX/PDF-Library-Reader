"""Main library window: browse, search, sort, filter, favorite and open PDF books."""
import os
from collections import OrderedDict

import pymupdf as fitz  # PyMuPDF (module renamed from "fitz")
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .badges import decorate_thumbnail
from .book_details_dialog import BookDetailsDialog
from .database import Database
from .flow_layout import FlowLayout
from .reader_window import ReaderWindow
from .search_dialog import TextSearchDialog
from .themes import DARK_THEME, LIGHT_THEME
from .thumbnails import delete_thumbnail, ensure_thumbnail
from .widgets import BookCard, CoverCell

# index in the sort combo -> (sort key, descending?)
SORT_OPTIONS = {
    0: ("title", False),   # Title A-Z
    1: ("title", True),    # Title Z-A
    2: ("recent", True),   # Recently read first
    3: ("recent", False),  # Least recently read first
    4: ("size", True),     # Largest file first
    5: ("size", False),    # Smallest file first
}

# index in the status filter combo -> status value passed to the database
STATUS_FILTER_OPTIONS = [
    ("None", None),
    ("Currently Reading", "reading"),
    ("Finished", "finished"),
    ("Unread", "unread"),
]


def _group_letter(title):
    stripped = (title or "").strip()
    if not stripped:
        return "#"
    first = stripped[0].upper()
    return first if first.isalpha() else "#"


class LibraryWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle("PDF Library")
        self.resize(880, 640)
        self.reader_windows = {}  # book_id -> ReaderWindow, kept alive while open
        self.show_favorites_only = False
        self.view_mode = db.get_setting("library_view_mode", "list")  # "list" or "grid"
        self._search_dialog = None
        self._details_dialog = None

        self._build_ui()
        self._apply_theme(self.db.get_setting("theme", "light"))
        self.text_view_btn.setChecked(self.view_mode == "list")
        self.image_view_btn.setChecked(self.view_mode == "grid")
        self.refresh_list()

    # ---------------- UI ----------------
    def _build_ui(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        add_action = QAction("Add Book(s)", self)
        add_action.triggered.connect(self.add_books)
        toolbar.addAction(add_action)

        add_folder_action = QAction("Add Folder", self)
        add_folder_action.triggered.connect(self.add_folder)
        toolbar.addAction(add_folder_action)

        toolbar.addSeparator()

        self.all_btn = QPushButton("All Books")
        self.all_btn.setCheckable(True)
        self.all_btn.setChecked(True)
        self.all_btn.clicked.connect(lambda: self.set_favorites_filter(False))
        toolbar.addWidget(self.all_btn)

        self.fav_btn = QPushButton("\u2605 Favorites")
        self.fav_btn.setCheckable(True)
        self.fav_btn.clicked.connect(lambda: self.set_favorites_filter(True))
        toolbar.addWidget(self.fav_btn)

        toolbar.addSeparator()

        self.text_view_btn = QPushButton("Simple Text")
        self.text_view_btn.setCheckable(True)
        self.text_view_btn.setToolTip("Show the library as a detailed text list")
        self.text_view_btn.clicked.connect(lambda: self.set_view_mode("list"))
        toolbar.addWidget(self.text_view_btn)

        self.image_view_btn = QPushButton("Image Preview")
        self.image_view_btn.setCheckable(True)
        self.image_view_btn.setToolTip("Show the library as a grid of page-1 thumbnails")
        self.image_view_btn.clicked.connect(lambda: self.set_view_mode("grid"))
        toolbar.addWidget(self.image_view_btn)

        toolbar.addSeparator()

        search_text_action = QAction("Search Text", self)
        search_text_action.setToolTip("Search for text inside all your books")
        search_text_action.triggered.connect(self.open_text_search)
        toolbar.addAction(search_text_action)

        toolbar.addSeparator()

        self.theme_btn = QPushButton("Dark Mode")
        self.theme_btn.setCheckable(True)
        self.theme_btn.clicked.connect(self.toggle_theme)
        toolbar.addWidget(self.theme_btn)

        central = QWidget()
        layout = QVBoxLayout(central)

        controls = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "Filter by title, author, or series... (use \u201cSearch Text\u201d to search inside books)"
        )
        self.search_box.textChanged.connect(self.refresh_list)
        self.search_box.textChanged.connect(self._update_search_suggestions)
        controls.addWidget(self.search_box, stretch=1)

        controls.addWidget(QLabel("Status:"))
        self.status_filter_combo = QComboBox()
        for label, value in STATUS_FILTER_OPTIONS:
            self.status_filter_combo.addItem(label, value)
        self.status_filter_combo.currentIndexChanged.connect(self.refresh_list)
        controls.addWidget(self.status_filter_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(
            [
                "Title (A-Z)",
                "Title (Z-A)",
                "Recently Read",
                "Oldest Read",
                "File Size (Largest)",
                "File Size (Smallest)",
            ]
        )
        self.sort_combo.currentIndexChanged.connect(self.refresh_list)
        controls.addWidget(self.sort_combo)
        layout.addLayout(controls)

        # Live categorized preview (Titles / Authors / Series) shown while typing
        # in the filter box; hidden whenever there's no text or no matches.
        self.suggestion_panel = QWidget()
        self.suggestion_layout = QVBoxLayout(self.suggestion_panel)
        self.suggestion_layout.setContentsMargins(6, 4, 6, 4)
        self.suggestion_layout.setSpacing(1)
        self.suggestion_panel.setStyleSheet(
            "background-color: rgba(127, 127, 127, 30); border: 1px solid #ccc; border-radius: 4px;"
        )
        layout.addWidget(self.suggestion_panel)
        self.suggestion_panel.hide()

        # "Simple Text" view: a detailed list of BookCard rows.
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget)

        # "Image Preview" view: a scrollable, wrapping grid of cover thumbnails,
        # optionally grouped under a letter header when sorted alphabetically.
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.grid_scroll)

        self.empty_label = QLabel(
            'No books yet. Click "Add Book(s)" or "Add Folder" to build your library.'
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #999; padding: 40px;")
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

        self.setCentralWidget(central)

    # ------------- Actions -------------
    def add_books(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select PDF files", os.path.expanduser("~"), "PDF files (*.pdf)"
        )
        for path in paths:
            self._import_pdf(path)
        self.refresh_list()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if not folder:
            return
        count = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".pdf"):
                    self._import_pdf(os.path.join(root, f))
                    count += 1
        self.refresh_list()
        QMessageBox.information(self, "Import complete", f"Added {count} PDF file(s).")

    def _import_pdf(self, path):
        title = os.path.splitext(os.path.basename(path))[0]
        page_count = 0
        try:
            doc = fitz.open(path)
            meta_title = (doc.metadata or {}).get("title") or ""
            if meta_title.strip():
                title = meta_title.strip()
            page_count = doc.page_count
            doc.close()
        except Exception:
            pass  # keep filename-derived title, page_count stays 0
        self.db.add_book(os.path.abspath(path), title, page_count)

    def set_favorites_filter(self, favorites_only):
        self.show_favorites_only = favorites_only
        self.all_btn.setChecked(not favorites_only)
        self.fav_btn.setChecked(favorites_only)
        self.refresh_list()

    def toggle_theme(self, checked):
        self.theme_btn.setChecked(checked)
        theme = "dark" if checked else "light"
        self.db.set_setting("theme", theme)
        self._apply_theme(theme)

    def _apply_theme(self, theme):
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(DARK_THEME if theme == "dark" else LIGHT_THEME)
        self.theme_btn.setChecked(theme == "dark")

    def refresh_list(self):
        sort_by, descending = SORT_OPTIONS[self.sort_combo.currentIndex()]
        search = self.search_box.text().strip() or None
        status_filter = self.status_filter_combo.currentData()
        books = self.db.get_books(
            favorites_only=self.show_favorites_only,
            search=search,
            sort_by=sort_by,
            descending=descending,
            status=status_filter,
        )

        self.empty_label.setVisible(len(books) == 0)
        self.list_widget.setVisible(self.view_mode == "list" and len(books) > 0)
        self.grid_scroll.setVisible(self.view_mode == "grid" and len(books) > 0)

        if self.view_mode == "grid":
            self._render_grid(books, sort_by)
        else:
            self._render_list(books)

    # ------------- Search suggestions preview -------------
    def _update_search_suggestions(self, text):
        text = text.strip()
        self._clear_suggestion_layout()
        if not text:
            self.suggestion_panel.hide()
            return

        results = self.db.search_suggestions(text, limit=5)
        if not (results["titles"] or results["authors"] or results["series"]):
            self.suggestion_panel.hide()
            return

        if results["titles"]:
            self._add_suggestion_header("Titles")
            for row in results["titles"]:
                self._add_suggestion_row(row["title"], row["title"])
        if results["authors"]:
            self._add_suggestion_header("Authors")
            for row in results["authors"]:
                label = f"{row['name']} ({row['count']} book{'s' if row['count'] != 1 else ''})"
                self._add_suggestion_row(label, row["name"])
        if results["series"]:
            self._add_suggestion_header("Series")
            for row in results["series"]:
                label = f"{row['name']} ({row['count']} book{'s' if row['count'] != 1 else ''})"
                self._add_suggestion_row(label, row["name"])

        self.suggestion_panel.show()

    def _clear_suggestion_layout(self):
        while self.suggestion_layout.count():
            item = self.suggestion_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()  # deleteLater() is deferred; hide it now so it can't linger visually
                w.deleteLater()

    def _add_suggestion_header(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; color: #888; font-size: 11px; padding-top: 4px;")
        self.suggestion_layout.addWidget(label)

    def _add_suggestion_row(self, label_text, filter_value):
        btn = QPushButton(label_text)
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("text-align: left; padding: 2px 8px; border: none;")
        btn.clicked.connect(lambda: self._apply_suggestion(filter_value))
        self.suggestion_layout.addWidget(btn)

    def _apply_suggestion(self, value):
        self.search_box.setText(value)  # triggers refresh_list + _update_search_suggestions
        self.suggestion_panel.hide()    # then collapse the preview -- selection made

    # ------------- Simple Text (list) view -------------
    def _render_list(self, books):
        self.list_widget.clear()
        for book in books:
            item = QListWidgetItem()
            card = BookCard(book)
            card.open_requested.connect(self.open_book)
            card.favorite_toggled.connect(self.toggle_favorite)
            card.remove_requested.connect(self.remove_book)
            card.details_requested.connect(self.open_book_details)
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

    # ------------- Image Preview (grid) view -------------
    def _render_grid(self, books, sort_by):
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(6)

        if sort_by == "title" and books:
            groups = OrderedDict()
            for book in books:
                groups.setdefault(_group_letter(book["title"]), []).append(book)
            for letter, group_books in groups.items():
                header = QLabel(letter)
                header.setStyleSheet(
                    "font-weight: bold; font-size: 15px; color: #666;"
                    "padding: 4px 2px; border-bottom: 2px solid #cfcfcf; margin-top: 6px;"
                )
                outer.addWidget(header)
                outer.addWidget(self._build_cover_group(group_books))
        elif books:
            outer.addWidget(self._build_cover_group(books))

        outer.addStretch()
        self.grid_scroll.setWidget(content)

    def _build_cover_group(self, books):
        group_widget = QWidget()
        flow = FlowLayout(group_widget, margin=0, hspacing=14, vspacing=14)
        for book in books:
            pixmap = ensure_thumbnail(book["id"], book["filepath"])
            pixmap = decorate_thumbnail(pixmap, book.get("status") or "unread")
            cell = CoverCell(book, pixmap)
            cell.open_requested.connect(self.open_book)
            cell.details_requested.connect(self.open_book_details)
            cell.favorite_toggled.connect(self.toggle_favorite)
            cell.remove_requested.connect(self.remove_book)
            flow.addWidget(cell)
        return group_widget

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.db.set_setting("library_view_mode", mode)
        self.text_view_btn.setChecked(mode == "list")
        self.image_view_btn.setChecked(mode == "grid")
        self.refresh_list()

    def open_text_search(self):
        if self._search_dialog is None:
            self._search_dialog = TextSearchDialog(self.db, self.open_book_at_page, self)
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()

    def open_book_details(self, book_id):
        if self._details_dialog is None:
            self._details_dialog = BookDetailsDialog(self.db, self)
            self._details_dialog.book_updated.connect(self.refresh_list)
            self._details_dialog.open_requested.connect(self.open_book)
        self._details_dialog.load_book(book_id)
        self._details_dialog.show()
        self._details_dialog.raise_()
        self._details_dialog.activateWindow()

    def open_book_at_page(self, book_id, page_number):
        self.open_book(book_id)
        win = self.reader_windows.get(book_id)
        if win is not None:
            win.jump_to_page(page_number + 1)
            win.raise_()
            win.activateWindow()

    def toggle_favorite(self, book_id):
        self.db.toggle_favorite(book_id)
        self.refresh_list()

    def remove_book(self, book_id):
        reply = QMessageBox.question(
            self,
            "Remove book",
            "Remove this book from your library? The file itself will not be deleted.",
        )
        if reply == QMessageBox.Yes:
            self.db.remove_book(book_id)
            delete_thumbnail(book_id)
            self.refresh_list()

    def open_book(self, book_id):
        book = self.db.get_book(book_id)
        if not book:
            return
        if not os.path.exists(book["filepath"]):
            QMessageBox.warning(self, "File missing", "This file could not be found on disk.")
            return

        existing = self.reader_windows.get(book_id)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        win = ReaderWindow(self.db, book_id, on_close=self.refresh_list)
        self.reader_windows[book_id] = win
        win.show()
