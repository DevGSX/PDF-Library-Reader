"""Dialog for adding books to a category by searching Title (adds one book),
Author, or Series (each adds every matching book) -- reuses the same
categorized search used by the library's live filter suggestions. Results
can be viewed as a plain text list or as a grid of cover thumbnails.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .flow_layout import FlowLayout
from .thumbnails import ensure_thumbnail


class _MiniCoverCell(QWidget):
    """A small clickable cover thumbnail used in the dialog's Image Preview
    results (Titles only -- Author/Series matches represent multiple books,
    so they stay as text rows even in image mode)."""

    clicked = Signal(int)  # book_id

    def __init__(self, book_id, title, pixmap, parent=None):
        super().__init__(parent)
        self.book_id = book_id
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(90)
        self.setToolTip(f"{title}\nClick to add this book")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        cover = QLabel()
        cover.setPixmap(pixmap.scaled(80, 108, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        cover.setAlignment(Qt.AlignCenter)
        layout.addWidget(cover)

        caption = QLabel(title)
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        caption.setStyleSheet("font-size: 10px;")
        layout.addWidget(caption)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.book_id)
        super().mousePressEvent(event)


class AddToCategoryDialog(QDialog):
    books_added = Signal()  # so the caller can refresh category counts / the book list

    def __init__(self, db, category_id, category_name, parent=None):
        super().__init__(parent)
        self.db = db
        self.category_id = category_id
        self.total_added = 0
        self.view_mode = "text"  # "text" or "image"

        self.setWindowTitle(f"Add Books to \u201c{category_name}\u201d")
        self.resize(480, 460)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Search by title to add one book, or by author/series to add every "
            "matching book at once."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        top_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search title, author, or series...")
        self.search_box.textChanged.connect(self._update_results)
        top_row.addWidget(self.search_box, stretch=1)

        self.text_view_btn = QPushButton("Text")
        self.text_view_btn.setCheckable(True)
        self.text_view_btn.setChecked(True)
        self.text_view_btn.setToolTip("Show results as a text list")
        self.text_view_btn.clicked.connect(lambda: self._set_view_mode("text"))
        top_row.addWidget(self.text_view_btn)

        self.image_view_btn = QPushButton("Image Preview")
        self.image_view_btn.setCheckable(True)
        self.image_view_btn.setToolTip("Show title matches as cover thumbnails")
        self.image_view_btn.clicked.connect(lambda: self._set_view_mode("image"))
        top_row.addWidget(self.image_view_btn)
        layout.addLayout(top_row)

        # Text view: a single list of grouped, clickable rows.
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.results_list)

        # Image view: cover thumbnails for title matches (in a wrapping flow),
        # with author/series matches listed as text rows underneath.
        self.image_results_scroll = QScrollArea()
        self.image_results_scroll.setWidgetResizable(True)
        self.image_results_scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.image_results_scroll)
        self.image_results_scroll.hide()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        done_btn = QPushButton("Done")
        done_btn.setDefault(True)
        done_btn.clicked.connect(self.accept)
        btn_row.addWidget(done_btn)
        layout.addLayout(btn_row)

    def _set_view_mode(self, mode):
        self.view_mode = mode
        self.text_view_btn.setChecked(mode == "text")
        self.image_view_btn.setChecked(mode == "image")
        self.results_list.setVisible(mode == "text")
        self.image_results_scroll.setVisible(mode == "image")
        self._update_results(self.search_box.text())

    def _update_results(self, text):
        text = text.strip()
        if self.view_mode == "text":
            self._render_text_results(text)
        else:
            self._render_image_results(text)

    # ------------- Text results -------------
    def _render_text_results(self, text):
        self.results_list.clear()
        if not text:
            return
        results = self.db.search_suggestions(text, limit=8)

        if results["titles"]:
            self._add_header("Titles \u2014 click to add that one book")
            for row in results["titles"]:
                self._add_row(row["title"], ("title", row["id"], row["title"]))
        if results["authors"]:
            self._add_header("Authors \u2014 click to add every book by them")
            for row in results["authors"]:
                label = f"{row['name']} ({row['count']} book{'s' if row['count'] != 1 else ''})"
                self._add_row(label, ("author", row["name"], row["name"]))
        if results["series"]:
            self._add_header("Series \u2014 click to add every book in it")
            for row in results["series"]:
                label = f"{row['name']} ({row['count']} book{'s' if row['count'] != 1 else ''})"
                self._add_row(label, ("series", row["name"], row["name"]))

        if not (results["titles"] or results["authors"] or results["series"]):
            item = QListWidgetItem("No matches.")
            item.setFlags(Qt.NoItemFlags)
            self.results_list.addItem(item)

    def _add_header(self, text):
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setForeground(Qt.gray)
        self.results_list.addItem(item)

    def _add_row(self, label, payload):
        item = QListWidgetItem(f"  {label}")
        item.setData(Qt.UserRole, payload)
        self.results_list.addItem(item)

    def _on_item_clicked(self, item):
        payload = item.data(Qt.UserRole)
        if not payload:
            return
        self._apply_payload(payload)

    # ------------- Image results -------------
    def _render_image_results(self, text):
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)

        if text:
            results = self.db.search_suggestions(text, limit=8)

            if results["titles"]:
                header = QLabel("Titles \u2014 click a cover to add that book")
                header.setStyleSheet("color: gray;")
                outer.addWidget(header)
                covers_row = QWidget()
                flow = FlowLayout(covers_row, margin=0, hspacing=8, vspacing=8)
                for row in results["titles"]:
                    book = self.db.get_book(row["id"])
                    if not book:
                        continue
                    pixmap, _is_corrupted = ensure_thumbnail(book["id"], book["filepath"])
                    cell = _MiniCoverCell(book["id"], row["title"], pixmap)
                    cell.clicked.connect(
                        lambda bid: self._apply_payload(("title", bid, self.db.get_book(bid)["title"]))
                    )
                    flow.addWidget(cell)
                outer.addWidget(covers_row)

            if results["authors"]:
                header = QLabel("Authors \u2014 click to add every book by them")
                header.setStyleSheet("color: gray;")
                outer.addWidget(header)
                for row in results["authors"]:
                    label = f"{row['name']} ({row['count']} book{'s' if row['count'] != 1 else ''})"
                    outer.addWidget(self._build_image_text_row(label, ("author", row["name"], row["name"])))

            if results["series"]:
                header = QLabel("Series \u2014 click to add every book in it")
                header.setStyleSheet("color: gray;")
                outer.addWidget(header)
                for row in results["series"]:
                    label = f"{row['name']} ({row['count']} book{'s' if row['count'] != 1 else ''})"
                    outer.addWidget(self._build_image_text_row(label, ("series", row["name"], row["name"])))

            if not (results["titles"] or results["authors"] or results["series"]):
                outer.addWidget(QLabel("No matches."))

        outer.addStretch()
        self.image_results_scroll.setWidget(content)

    def _build_image_text_row(self, label, payload):
        btn = QPushButton(label)
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("text-align: left; padding: 2px 8px; border: none;")
        btn.clicked.connect(lambda: self._apply_payload(payload))
        return btn

    # ------------- Shared add logic -------------
    def _apply_payload(self, payload):
        kind, value, display = payload
        if kind == "title":
            added = self.db.add_books_to_category(self.category_id, [value])
            self.status_label.setText(f"Added \u201c{display}\u201d.")
        elif kind == "author":
            ids = self.db.get_book_ids_by_author(value)
            added = self.db.add_books_to_category(self.category_id, ids)
            self.status_label.setText(
                f"Added {added} book{'s' if added != 1 else ''} by {display}."
            )
        elif kind == "series":
            ids = self.db.get_book_ids_by_series(value)
            added = self.db.add_books_to_category(self.category_id, ids)
            self.status_label.setText(
                f"Added {added} book{'s' if added != 1 else ''} from {display}."
            )
        else:
            return
        self.total_added += added
        self.books_added.emit()
