"""Reusable small widgets: the book row card for list view, and the cover
cell for the image-preview grid."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

STATUS_CHIP_STYLE = (
    "color: white; border-radius: 8px; padding: 1px 8px;"
    "font-size: 11px; font-weight: bold;"
)


def human_size(num_bytes):
    if num_bytes is None or num_bytes < 0:
        return "file missing"
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class BookCard(QWidget):
    """A single book row for the Simple Text list view. Left-click buttons
    handle Favorite/Open/Remove directly; Details is only available via the
    right-click context menu, so browsing the list doesn't keep popping it open."""

    open_requested = Signal(int)
    favorite_toggled = Signal(int)
    remove_requested = Signal(int)
    details_requested = Signal(int)  # emitted only from the right-click menu

    def __init__(self, book: dict, parent=None):
        super().__init__(parent)
        self.book_id = book["id"]
        self.setObjectName("BookCard")
        self.setAttribute(Qt.WA_StyledBackground, True)  # let stylesheet hover/background paint
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        text_layout = QVBoxLayout()

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(f"<b>{_escape(book['title'])}</b>")
        title.setTextFormat(Qt.RichText)
        title_row.addWidget(title)

        status = book.get("status") or "unread"
        if status == "finished":
            chip = QLabel("\u2713 Finished")
            chip.setStyleSheet(f"background-color: #228b3c; {STATUS_CHIP_STYLE}")
            title_row.addWidget(chip)
        elif status == "reading":
            chip = QLabel("\U0001F4D6 Reading")
            chip.setStyleSheet(f"background-color: #2173eb; {STATUS_CHIP_STYLE}")
            title_row.addWidget(chip)
        title_row.addStretch()
        text_layout.addLayout(title_row)

        meta_bits = [human_size(book["file_size"])]
        if book.get("page_count"):
            meta_bits.append(f"{book['page_count']} pages")
        if book.get("author"):
            meta_bits.append(book["author"])
        if book.get("genre"):
            meta_bits.append(book["genre"])
        if book.get("last_opened"):
            meta_bits.append(f"last read {book['last_opened'][:16].replace('T', ' ')}")
        else:
            meta_bits.append("not read yet")
        if book.get("last_page"):
            meta_bits.append(f"page {book['last_page'] + 1}")
        meta = QLabel(" \u00b7 ".join(meta_bits))
        meta.setStyleSheet("color: #888;")
        text_layout.addWidget(meta)

        layout.addLayout(text_layout, stretch=1)

        self.fav_btn = QPushButton("\u2605" if book["is_favorite"] else "\u2606")
        self.fav_btn.setFixedWidth(36)
        self.fav_btn.setCheckable(True)
        self.fav_btn.setChecked(bool(book["is_favorite"]))
        self.fav_btn.setToolTip("Toggle favorite")
        self.fav_btn.clicked.connect(lambda: self.favorite_toggled.emit(self.book_id))
        layout.addWidget(self.fav_btn)

        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda: self.open_requested.emit(self.book_id))
        layout.addWidget(open_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.book_id))
        layout.addWidget(remove_btn)

        self.setToolTip("Right-click for details (author, series, notes...)")

    def _show_context_menu(self, pos):
        menu = self._build_context_menu()
        menu.exec(self.mapToGlobal(pos))

    def _build_context_menu(self):
        menu = QMenu(self)
        menu.addAction("Open").triggered.connect(lambda: self.open_requested.emit(self.book_id))
        menu.addAction("Details").triggered.connect(lambda: self.details_requested.emit(self.book_id))
        menu.addAction("Toggle Favorite").triggered.connect(
            lambda: self.favorite_toggled.emit(self.book_id)
        )
        menu.addAction("Remove from Library").triggered.connect(
            lambda: self.remove_requested.emit(self.book_id)
        )
        return menu


class CoverCell(QWidget):
    """A single book cover cell for the image-preview grid: thumbnail + title.
    Double click opens the reader; Details (and everything else) lives in the
    right-click context menu, so browsing the grid doesn't keep popping it open."""

    open_requested = Signal(int)
    details_requested = Signal(int)  # emitted only from the right-click menu
    favorite_toggled = Signal(int)
    remove_requested = Signal(int)

    CELL_WIDTH = 150

    def __init__(self, book: dict, pixmap, parent=None):
        super().__init__(parent)
        self.book_id = book["id"]
        self.setObjectName("CoverCell")
        self.setAttribute(Qt.WA_StyledBackground, True)  # let stylesheet hover/background paint
        self.setFixedWidth(self.CELL_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        cover_label = QLabel()
        cover_label.setPixmap(
            pixmap.scaled(140, 190, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        cover_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(cover_label)

        title_label = QLabel(_escape(book["title"]))
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        title_label.setTextFormat(Qt.RichText)
        layout.addWidget(title_label)

        tooltip_bits = [book["title"], human_size(book.get("file_size", -1))]
        if book.get("author"):
            tooltip_bits.append(book["author"])
        if book.get("genre"):
            tooltip_bits.append(book["genre"])
        if book.get("is_favorite"):
            tooltip_bits.append("\u2605 Favorite")
        status = book.get("status") or "unread"
        if status == "finished":
            tooltip_bits.append("\u2713 Finished")
        elif status == "reading":
            tooltip_bits.append("Currently reading")
        tooltip_bits.append("Double-click to open \u00b7 right-click for details")
        self.setToolTip("\n".join(tooltip_bits))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.open_requested.emit(self.book_id)
        super().mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        menu = self._build_context_menu()
        menu.exec(self.mapToGlobal(pos))

    def _build_context_menu(self):
        menu = QMenu(self)
        menu.addAction("Open").triggered.connect(lambda: self.open_requested.emit(self.book_id))
        menu.addAction("Details").triggered.connect(lambda: self.details_requested.emit(self.book_id))
        menu.addAction("Toggle Favorite").triggered.connect(
            lambda: self.favorite_toggled.emit(self.book_id)
        )
        menu.addAction("Remove from Library").triggered.connect(
            lambda: self.remove_requested.emit(self.book_id)
        )
        return menu


def _escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
