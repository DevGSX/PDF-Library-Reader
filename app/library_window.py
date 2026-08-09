"""Main library window: browse, search, sort, filter, favorite, categorize,
and open PDF books."""
import os
from collections import OrderedDict

import pymupdf as fitz  # PyMuPDF (module renamed from "fitz")
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .add_to_category_dialog import AddToCategoryDialog
from .badges import decorate_thumbnail
from .book_details_dialog import BookDetailsDialog
from .database import Database
from .file_naming import parse_filename
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

ALPHABET_INDEX = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["#"]


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
        self.resize(1080, 640)
        self.reader_windows = {}  # book_id -> ReaderWindow, kept alive while open
        self.show_favorites_only = False
        self.view_mode = db.get_setting("library_view_mode", "list")  # "list" or "grid"
        self._search_dialog = None
        self._details_dialog = None
        self._letter_headers = {}  # letter -> header QLabel, populated by _render_grid
        self.selected_category_id = None  # None = "All Books" (no category filter)
        self._selected_book_ids = set()  # multi-selection for bulk actions
        self.select_mode = False  # while off, clicking a book does nothing (prevents accidental selection)
        self.library_page = 1  # current page when paginating (only applies to non-alphabetical sorts)

        self._build_ui()
        self._apply_theme(self.db.get_setting("theme", "light"))
        self.text_view_btn.setChecked(self.view_mode == "list")
        self.image_view_btn.setChecked(self.view_mode == "grid")
        self.refresh_categories_sidebar()
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

        self.select_mode_btn = QPushButton("Select")
        self.select_mode_btn.setCheckable(True)
        self.select_mode_btn.setToolTip(
            "Turn on to click books and select them for bulk actions "
            "(add to a category, remove several at once)"
        )
        self.select_mode_btn.clicked.connect(self.toggle_select_mode)
        toolbar.addWidget(self.select_mode_btn)

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

        # ---- Overall layout: category sidebar (left) + main content (right) ----
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_category_sidebar())

        main_content = QWidget()
        layout = QVBoxLayout(main_content)

        controls = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "Filter by title, author, series, or genre... (use \u201cSearch Text\u201d to search inside books)"
        )
        self.search_box.textChanged.connect(self._reset_page_and_refresh)
        self.search_box.textChanged.connect(self._update_search_suggestions)
        controls.addWidget(self.search_box, stretch=1)

        controls.addWidget(QLabel("Status:"))
        self.status_filter_combo = QComboBox()
        for label, value in STATUS_FILTER_OPTIONS:
            self.status_filter_combo.addItem(label, value)
        self.status_filter_combo.currentIndexChanged.connect(self._reset_page_and_refresh)
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
        self.sort_combo.currentIndexChanged.connect(self._reset_page_and_refresh)
        controls.addWidget(self.sort_combo)

        controls.addWidget(QLabel("Per page:"))
        self.per_page_combo = QComboBox()
        self.per_page_combo.addItems(["All", "10", "25", "50", "100"])
        self.per_page_combo.setToolTip(
            "Split Recently Read / Oldest Read / File Size results into pages "
            "instead of showing them all at once (not available for Title sort, "
            "which uses the A-Z index instead)"
        )
        self.per_page_combo.currentIndexChanged.connect(self._reset_page_and_refresh)
        controls.addWidget(self.per_page_combo)
        layout.addLayout(controls)

        # Selection indicator: shown only while one or more books are selected.
        selection_row = QHBoxLayout()
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet("color: #888;")
        selection_row.addWidget(self.selection_label)
        selection_row.addStretch()
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self.clear_selection)
        selection_row.addWidget(self.clear_selection_btn)
        layout.addLayout(selection_row)
        self.selection_label.hide()
        self.clear_selection_btn.hide()

        # Live categorized preview (Titles / Authors / Series / Genres) shown
        # while typing in the filter box; hidden whenever no text or no matches.
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
        # grouped under a letter header when sorted alphabetically, with a
        # clickable A-Z index strip pinned above the grid.
        self.grid_container = QWidget()
        grid_col = QVBoxLayout(self.grid_container)
        grid_col.setContentsMargins(0, 0, 0, 0)
        grid_col.setSpacing(4)

        self.alpha_bar_top, self._alpha_buttons_top = self._build_alpha_bar()
        self.alpha_bar_top.hide()
        grid_col.addWidget(self.alpha_bar_top)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QScrollArea.NoFrame)
        grid_col.addWidget(self.grid_scroll, stretch=1)

        layout.addWidget(self.grid_container)

        self.empty_label = QLabel(
            'No books yet. Click "Add Book(s)" or "Add Folder" to build your library.'
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #999; padding: 40px;")
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

        # Pagination nav: only shown when "Per page" isn't "All" and the sort
        # isn't Title (which uses the A-Z index instead of pages).
        self.pagination_widget = QWidget()
        self.pagination_row = QHBoxLayout(self.pagination_widget)
        self.pagination_row.addStretch()
        self.prev_page_btn = QPushButton("\u25c0 Previous")
        self.prev_page_btn.clicked.connect(self._go_to_prev_page)
        self.pagination_row.addWidget(self.prev_page_btn)
        self.page_indicator_label = QLabel("")
        self.pagination_row.addWidget(self.page_indicator_label)
        self.next_page_btn = QPushButton("Next \u25b6")
        self.next_page_btn.clicked.connect(self._go_to_next_page)
        self.pagination_row.addWidget(self.next_page_btn)
        self.pagination_row.addStretch()
        layout.addWidget(self.pagination_widget)
        self.pagination_widget.hide()

        outer.addWidget(main_content, stretch=1)
        self.setCentralWidget(central)

        # Clicking empty space (no book under the cursor) in either view clears
        # the current multi-selection, so you don't have to click a selected
        # book again or hunt for the Clear Selection button.
        self.list_widget.viewport().installEventFilter(self)
        self.grid_scroll.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if obj is self.list_widget.viewport():
                if self.list_widget.itemAt(event.position().toPoint()) is None:
                    self.clear_selection()
            elif obj is self.grid_scroll.viewport():
                content = self.grid_scroll.widget()
                if content is not None:
                    local_pos = content.mapFromParent(event.position().toPoint())
                    if content.childAt(local_pos) is None:
                        self.clear_selection()
        return super().eventFilter(obj, event)

    def _build_alpha_bar(self):
        """A horizontal, wrapping row of A-Z (+#) buttons that jump to that
        letter's section in the grid. Returns (widget, {letter: button})."""
        bar = QWidget()
        bar_layout = FlowLayout(bar, margin=2, hspacing=2, vspacing=2)
        buttons = {}
        for letter in ALPHABET_INDEX:
            btn = QPushButton(letter)
            btn.setFlat(True)
            btn.setFixedSize(24, 22)
            btn.setToolTip(f"Jump to \u201c{letter}\u201d")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("font-size: 10px; padding: 0px;")
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked=False, l=letter: self._jump_to_letter(l))
            bar_layout.addWidget(btn)
            buttons[letter] = btn
        return bar, buttons

    def _build_category_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("Categories")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        sidebar_layout.addWidget(header)

        new_cat_btn = QPushButton("+ New Category")
        new_cat_btn.clicked.connect(self.create_new_category)
        sidebar_layout.addWidget(new_cat_btn)

        self.category_list = QListWidget()
        self.category_list.itemClicked.connect(self._on_category_selected)
        self.category_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.category_list.customContextMenuRequested.connect(self._show_category_context_menu)
        sidebar_layout.addWidget(self.category_list)

        hint = QLabel(
            "Right-click a category to add books, favorite, rename, or delete it. "
            "Right-click any book (or a multi-selection) to add it to a category."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        sidebar_layout.addWidget(hint)

        return sidebar

    # ------------- Categories -------------
    def refresh_categories_sidebar(self):
        self.category_list.clear()
        none_item = QListWidgetItem("All Books (None)")
        none_item.setData(Qt.UserRole, None)
        self.category_list.addItem(none_item)

        selected_row = 0
        for i, cat in enumerate(self.db.get_categories(), start=1):
            star = "\u2605 " if cat["is_favorite"] else ""
            item = QListWidgetItem(f"{star}{cat['name']} ({cat['book_count']})")
            item.setData(Qt.UserRole, cat["id"])
            self.category_list.addItem(item)
            if cat["id"] == self.selected_category_id:
                selected_row = i
        self.category_list.setCurrentRow(selected_row)

    def _on_category_selected(self, item):
        self.category_list.setCurrentItem(item)  # keep the highlight correct even
        self.selected_category_id = item.data(Qt.UserRole)  # if called programmatically
        self.library_page = 1
        self.refresh_list()

    def create_new_category(self):
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if ok and name.strip():
            self.db.create_category(name.strip())
            self.refresh_categories_sidebar()

    def _show_category_context_menu(self, pos):
        item = self.category_list.itemAt(pos)
        if item is None:
            return
        category_id = item.data(Qt.UserRole)
        if category_id is None:
            return  # the "All Books (None)" pseudo-entry has no actions
        category = self.db.get_category(category_id)
        if category is None:
            return

        menu = QMenu(self)
        add_action = menu.addAction("Add Books...")
        fav_label = "Remove from Favorite Categories" if category["is_favorite"] else "Favorite Category"
        fav_action = menu.addAction(fav_label)
        rename_action = menu.addAction("Rename...")
        delete_action = menu.addAction("Delete Category")
        chosen = menu.exec(self.category_list.viewport().mapToGlobal(pos))

        if chosen == add_action:
            self._open_add_to_category_dialog(category_id, category["name"])
        elif chosen == fav_action:
            self.db.toggle_category_favorite(category_id)
            self.refresh_categories_sidebar()
        elif chosen == rename_action:
            self._rename_category(category_id, category["name"])
        elif chosen == delete_action:
            self._delete_category(category_id, category["name"])

    def _rename_category(self, category_id, current_name):
        name, ok = QInputDialog.getText(
            self, "Rename Category", "New name:", text=current_name
        )
        if ok and name.strip():
            if not self.db.rename_category(category_id, name.strip()):
                QMessageBox.warning(
                    self, "Couldn't rename", "A category with that name already exists."
                )
            self.refresh_categories_sidebar()

    def _delete_category(self, category_id, name):
        reply = QMessageBox.question(
            self,
            "Delete category",
            f"Delete the category \u201c{name}\u201d? Your books stay in the "
            f"library \u2014 they're just removed from this category.",
        )
        if reply == QMessageBox.Yes:
            self.db.delete_category(category_id)
            if self.selected_category_id == category_id:
                self.selected_category_id = None
            self.refresh_categories_sidebar()
            self.refresh_list()

    def _open_add_to_category_dialog(self, category_id, category_name):
        dialog = AddToCategoryDialog(self.db, category_id, category_name, self)
        dialog.books_added.connect(self.refresh_categories_sidebar)
        dialog.books_added.connect(self.refresh_list)
        dialog.exec()

    # ------------- Multi-select & bulk actions -------------
    def toggle_book_selection(self, book_id):
        # Deferred: this is called synchronously from within the clicked
        # card/cell's own mousePressEvent, and refresh_list() destroys that
        # same widget tree -- rebuilding immediately would delete the widget
        # while Qt is still mid-dispatch on its event, causing a crash.
        if book_id in self._selected_book_ids:
            self._selected_book_ids.discard(book_id)
        else:
            self._selected_book_ids.add(book_id)
        self._update_selection_indicator()
        QTimer.singleShot(0, self.refresh_list)

    def clear_selection(self):
        # Deferred for the same reason -- this can also be triggered from a
        # book's own right-click context menu ("Clear Selection").
        if not self._selected_book_ids:
            return  # nothing to do -- avoid an unnecessary re-render
        self._selected_book_ids.clear()
        self._update_selection_indicator()
        QTimer.singleShot(0, self.refresh_list)

    def _update_selection_indicator(self):
        n = len(self._selected_book_ids)
        self.selection_label.setVisible(n > 0 or self.select_mode)
        self.clear_selection_btn.setVisible(n > 0)
        if n > 0:
            self.selection_label.setText(
                f"{n} book{'s' if n != 1 else ''} selected \u2014 right-click any "
                f"selected book to add them all to a category"
            )
        elif self.select_mode:
            self.selection_label.setText("Select mode is on \u2014 click books to select them")

    def show_book_context_menu(self, book_id, global_pos):
        if book_id in self._selected_book_ids and len(self._selected_book_ids) > 1:
            self._show_bulk_context_menu(set(self._selected_book_ids), global_pos)
        else:
            self._show_single_context_menu(book_id, global_pos)

    def _show_single_context_menu(self, book_id, global_pos):
        menu = QMenu(self)
        menu.addAction("Open").triggered.connect(lambda: self.open_book(book_id))
        menu.addAction("Details").triggered.connect(lambda: self.open_book_details(book_id))
        menu.addAction("Toggle Favorite").triggered.connect(lambda: self.toggle_favorite(book_id))
        add_menu = menu.addMenu("Add to Category")
        # Single-book action: don't touch any unrelated active multi-selection.
        self._populate_category_menu(add_menu, [book_id], clear_selection_after=False)
        menu.addAction("Remove from Library").triggered.connect(lambda: self.remove_book(book_id))
        menu.exec(global_pos)

    def _show_bulk_context_menu(self, book_ids, global_pos):
        n = len(book_ids)
        menu = QMenu(self)
        add_menu = menu.addMenu(f"Add {n} Selected to Category")
        # Bulk action: the selection has now been "used", so clear it once done.
        self._populate_category_menu(add_menu, list(book_ids), clear_selection_after=True)
        menu.addAction(f"Remove {n} Selected from Library").triggered.connect(
            lambda: self._bulk_remove_books(list(book_ids))
        )
        menu.addAction("Clear Selection").triggered.connect(self.clear_selection)
        menu.exec(global_pos)

    def _populate_category_menu(self, menu, book_ids, clear_selection_after=False):
        categories = self.db.get_categories()
        if not categories:
            empty_action = menu.addAction("(No categories yet)")
            empty_action.setEnabled(False)
        for cat in categories:
            action = menu.addAction(cat["name"])
            action.triggered.connect(
                lambda checked=False, cid=cat["id"]: self._add_books_to_category(
                    cid, book_ids, clear_selection_after
                )
            )
        menu.addSeparator()
        menu.addAction("New Category...").triggered.connect(
            lambda: self._create_category_and_add(book_ids, clear_selection_after)
        )

    def _add_books_to_category(self, category_id, book_ids, clear_selection_after=False):
        self.db.add_books_to_category(category_id, book_ids)
        self.refresh_categories_sidebar()
        if clear_selection_after:
            self.clear_selection()

    def _create_category_and_add(self, book_ids, clear_selection_after=False):
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if not ok or not name.strip():
            return
        category = self.db.create_category(name.strip())
        if category:
            self.db.add_books_to_category(category["id"], book_ids)
            self.refresh_categories_sidebar()
            if clear_selection_after:
                self.clear_selection()

    def _bulk_remove_books(self, book_ids):
        reply = QMessageBox.question(
            self,
            "Remove books",
            f"Remove {len(book_ids)} book(s) from your library? "
            f"The files themselves won't be deleted.",
        )
        if reply == QMessageBox.Yes:
            for book_id in book_ids:
                self.db.remove_book(book_id)
                delete_thumbnail(book_id)
                self._selected_book_ids.discard(book_id)
            self._update_selection_indicator()
            # Deferred: this can be triggered from a right-click on one of the
            # very books being removed, whose event Qt is still dispatching.
            QTimer.singleShot(0, self.refresh_list)
            QTimer.singleShot(0, self.refresh_categories_sidebar)

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
        abs_path = os.path.abspath(path)
        is_new_book = self.db.get_book_by_path(abs_path) is None

        # Title (and Author/Series/Genre, when present) come from the filename
        # itself -- e.g. "Dune * Frank Herbert * Dune Saga * Sci-Fi.pdf" --
        # rather than the PDF's own internal metadata, which often reflects
        # whatever a document's first heading happened to be, not the actual
        # book title.
        parsed = parse_filename(os.path.basename(path))

        page_count = 0
        try:
            doc = fitz.open(path)
            page_count = doc.page_count
            doc.close()
        except Exception:
            pass  # page_count stays 0; title still comes from the filename

        book = self.db.add_book(abs_path, parsed["title"], page_count)
        if book and is_new_book and (parsed["author"] or parsed["series"] or parsed["genre"]):
            # Only backfill these for a genuinely new import -- never overwrite
            # metadata someone already edited by hand on a book already in the library.
            self.db.update_metadata(
                book["id"],
                author=parsed["author"],
                series=parsed["series"],
                genre=parsed["genre"],
            )

    def set_favorites_filter(self, favorites_only):
        self.show_favorites_only = favorites_only
        self.all_btn.setChecked(not favorites_only)
        self.fav_btn.setChecked(favorites_only)
        self.library_page = 1
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
            category_id=self.selected_category_id,
        )

        # Pagination only makes sense for the non-alphabetical sorts (Title
        # sort uses the A-Z index instead of pages).
        is_paginated_sort = sort_by != "title"
        self.per_page_combo.setEnabled(is_paginated_sort)
        per_page = self._get_per_page() if is_paginated_sort else None

        if per_page:
            total_books = len(books)
            total_pages = max(1, (total_books + per_page - 1) // per_page)
            self.library_page = min(max(self.library_page, 1), total_pages)
            start = (self.library_page - 1) * per_page
            books = books[start:start + per_page]
            self._update_pagination_controls(total_pages, total_books)
            self.pagination_widget.setVisible(total_pages > 1)
        else:
            self.pagination_widget.hide()

        self.empty_label.setVisible(len(books) == 0)
        self.list_widget.setVisible(self.view_mode == "list" and len(books) > 0)
        self.grid_container.setVisible(self.view_mode == "grid" and len(books) > 0)

        if self.view_mode == "grid":
            self._render_grid(books, sort_by)
        else:
            self._render_list(books)

    def _reset_page_and_refresh(self):
        self.library_page = 1
        self.refresh_list()

    def _get_per_page(self):
        text = self.per_page_combo.currentText()
        return None if text == "All" else int(text)

    def _update_pagination_controls(self, total_pages, total_books):
        self.prev_page_btn.setEnabled(self.library_page > 1)
        self.next_page_btn.setEnabled(self.library_page < total_pages)
        self.page_indicator_label.setText(
            f"Page {self.library_page} of {total_pages} ({total_books} books)"
        )

    def _go_to_prev_page(self):
        if self.library_page > 1:
            self.library_page -= 1
            self.refresh_list()

    def _go_to_next_page(self):
        self.library_page += 1  # refresh_list() clamps this to the valid range
        self.refresh_list()

    # ------------- Search suggestions preview -------------
    def _update_search_suggestions(self, text):
        text = text.strip()
        self._clear_suggestion_layout()
        if not text:
            self.suggestion_panel.hide()
            return

        results = self.db.search_suggestions(text, limit=5)
        if not (results["titles"] or results["authors"] or results["series"] or results["genres"]):
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
        if results["genres"]:
            self._add_suggestion_header("Genres")
            for row in results["genres"]:
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
            card = BookCard(
                book,
                selected=book["id"] in self._selected_book_ids,
                select_mode=self.select_mode,
            )
            card.open_requested.connect(self.open_book)
            card.favorite_toggled.connect(self.toggle_favorite)
            card.remove_requested.connect(self.remove_book)
            card.details_requested.connect(self.open_book_details)
            card.selection_toggled.connect(self.toggle_book_selection)
            card.context_menu_requested.connect(self.show_book_context_menu)
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

    # ------------- Image Preview (grid) view -------------
    def _render_grid(self, books, sort_by):
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(6)

        self._letter_headers = {}
        is_alpha_sort = sort_by == "title"
        self.alpha_bar_top.setVisible(is_alpha_sort)

        if is_alpha_sort and books:
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
                self._letter_headers[letter] = header
            self._update_alpha_bars(set(groups.keys()))
        elif books:
            outer.addWidget(self._build_cover_group(books))

        outer.addStretch()
        self.grid_scroll.setWidget(content)

    def _update_alpha_bars(self, active_letters):
        for letter in ALPHABET_INDEX:
            self._alpha_buttons_top[letter].setEnabled(letter in active_letters)

    def _jump_to_letter(self, letter):
        header = self._letter_headers.get(letter)
        if header is not None:
            self.grid_scroll.verticalScrollBar().setValue(header.y())

    def _build_cover_group(self, books):
        group_widget = QWidget()
        flow = FlowLayout(group_widget, margin=0, hspacing=14, vspacing=14)
        for book in books:
            pixmap = ensure_thumbnail(book["id"], book["filepath"])
            pixmap = decorate_thumbnail(pixmap, book.get("status") or "unread", bool(book.get("is_favorite")))
            cell = CoverCell(
                book,
                pixmap,
                selected=book["id"] in self._selected_book_ids,
                select_mode=self.select_mode,
            )
            cell.open_requested.connect(self.open_book)
            cell.details_requested.connect(self.open_book_details)
            cell.favorite_toggled.connect(self.toggle_favorite)
            cell.remove_requested.connect(self.remove_book)
            cell.selection_toggled.connect(self.toggle_book_selection)
            cell.context_menu_requested.connect(self.show_book_context_menu)
            flow.addWidget(cell)
        return group_widget

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.db.set_setting("library_view_mode", mode)
        self.text_view_btn.setChecked(mode == "list")
        self.image_view_btn.setChecked(mode == "grid")
        self.refresh_list()

    def toggle_select_mode(self, checked):
        self.select_mode_btn.setChecked(checked)
        self.select_mode = checked
        self._update_selection_indicator()
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
        # Deferred: this is reachable from the card/cell's own fav button or
        # right-click menu, both nested within that widget's own event chain.
        self.db.toggle_favorite(book_id)
        QTimer.singleShot(0, self.refresh_list)

    def remove_book(self, book_id):
        reply = QMessageBox.question(
            self,
            "Remove book",
            "Remove this book from your library? The file itself will not be deleted.",
        )
        if reply == QMessageBox.Yes:
            self.db.remove_book(book_id)
            delete_thumbnail(book_id)
            self._selected_book_ids.discard(book_id)
            self._update_selection_indicator()
            # Deferred: reachable from the book's own right-click menu / remove
            # button, whose event Qt may still be dispatching on this widget.
            QTimer.singleShot(0, self.refresh_list)
            QTimer.singleShot(0, self.refresh_categories_sidebar)

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
