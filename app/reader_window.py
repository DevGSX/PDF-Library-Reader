"""Reader window: renders PDF pages, and supports simple-text mode, bookmarks,
text size / zoom, dark mode and favoriting a book while reading it."""
import pymupdf as fitz  # PyMuPDF (module renamed from "fitz")
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .database import Database
from .themes import DARK_THEME, LIGHT_THEME

MIN_ZOOM = 0.2
MAX_ZOOM = 6.0
VIEWPORT_MARGIN = 24  # px of breathing room so a fitted page never touches the edges


class ReaderWindow(QMainWindow):
    def __init__(self, db: Database, book_id: int, on_close=None):
        super().__init__()
        self.db = db
        self.book_id = book_id
        self.on_close = on_close

        db.mark_as_reading_if_new(book_id)  # first open promotes 'unread' -> 'reading'
        self.book = db.get_book(book_id)

        try:
            self.doc = fitz.open(self.book["filepath"])
        except Exception as exc:
            QMessageBox.critical(self, "Could not open file", str(exc))
            self.doc = None
            self.page_count = 0
            self.current_page = 0
            return

        self.page_count = max(self.doc.page_count, 1)
        self.current_page = min(max(self.book["last_page"] or 0, 0), self.page_count - 1)

        self.zoom = float(db.get_setting("reader_zoom", 1.3))
        self.auto_fit = db.get_setting("reader_auto_fit", "1") == "1"
        self.font_size = int(db.get_setting("reader_font_size", 15))
        self.simple_text_mode = db.get_setting("reader_text_mode", "normal") == "simple"
        self.dark_mode = db.get_setting("theme", "light") == "dark"

        self.setWindowTitle(self.book["title"])
        self.resize(920, 800)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.render_page)

        self._build_ui()
        self._build_bookmarks_dock()
        self.render_page()
        self.refresh_bookmarks()

    # ---------------- UI ----------------
    def _build_ui(self):
        toolbar = QToolBar("Reader")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        prev_action = QAction("\u25c0 Prev", self)
        prev_action.setShortcut(QKeySequence(Qt.Key_Left))
        prev_action.triggered.connect(self.prev_page)
        toolbar.addAction(prev_action)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(self.page_count)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.valueChanged.connect(self.jump_to_page)
        toolbar.addWidget(self.page_spin)

        toolbar.addWidget(QLabel(f" / {self.page_count}   "))

        next_action = QAction("Next \u25b6", self)
        next_action.setShortcut(QKeySequence(Qt.Key_Right))
        next_action.triggered.connect(self.next_page)
        toolbar.addAction(next_action)

        toolbar.addSeparator()

        dec_action = QAction("A-", self)
        dec_action.setShortcut(QKeySequence("Ctrl+-"))
        dec_action.setToolTip("Decrease text size / zoom out")
        dec_action.triggered.connect(self.decrease_text_size)
        toolbar.addAction(dec_action)

        inc_action = QAction("A+", self)
        inc_action.setShortcut(QKeySequence("Ctrl+="))
        inc_action.setToolTip("Increase text size / zoom in")
        inc_action.triggered.connect(self.increase_text_size)
        toolbar.addAction(inc_action)

        self.fit_btn = QPushButton("Fit to Screen")
        self.fit_btn.setToolTip(
            "Automatically scale each page to fit the window (pages can vary in size)"
        )
        self.fit_btn.setCheckable(True)
        self.fit_btn.setChecked(self.auto_fit)
        self.fit_btn.clicked.connect(self.toggle_auto_fit)
        toolbar.addWidget(self.fit_btn)

        toolbar.addSeparator()

        self.simple_btn = QPushButton("Simple Text")
        self.simple_btn.setToolTip("Show only the extracted text of this page")
        self.simple_btn.setCheckable(True)
        self.simple_btn.setChecked(self.simple_text_mode)
        self.simple_btn.clicked.connect(self.toggle_simple_text)
        toolbar.addWidget(self.simple_btn)

        self.dark_btn = QPushButton("Dark Mode")
        self.dark_btn.setCheckable(True)
        self.dark_btn.setChecked(self.dark_mode)
        self.dark_btn.clicked.connect(self.toggle_dark_mode)
        toolbar.addWidget(self.dark_btn)

        toolbar.addSeparator()

        self.fav_btn = QPushButton(self._fav_label())
        self.fav_btn.setCheckable(True)
        self.fav_btn.setChecked(bool(self.book["is_favorite"]))
        self.fav_btn.clicked.connect(self.toggle_favorite)
        toolbar.addWidget(self.fav_btn)

        self.finished_btn = QPushButton(self._finished_label())
        self.finished_btn.setToolTip("Mark this book as finished / not finished")
        self.finished_btn.setCheckable(True)
        self.finished_btn.setChecked(self.book["status"] == "finished")
        self.finished_btn.clicked.connect(self.toggle_finished)
        toolbar.addWidget(self.finished_btn)

        bookmark_action = QAction("+ Bookmark", self)
        bookmark_action.setShortcut(QKeySequence("Ctrl+D"))
        bookmark_action.triggered.connect(self.add_bookmark)
        toolbar.addAction(bookmark_action)

        # Central viewing area holds both the page-image view and the plain
        # text view; only one is visible at a time depending on the mode.
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        self.page_label = QLabel()
        self.page_label.setObjectName("pageLabel")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.page_label)

        self.text_browser = QTextBrowser()
        self.text_browser.setReadOnly(True)

        v.addWidget(self.scroll_area)
        v.addWidget(self.text_browser)
        self.setCentralWidget(container)
        self._update_mode_visibility()

    def _build_bookmarks_dock(self):
        dock = QDockWidget("Bookmarks", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemDoubleClicked.connect(self.jump_to_bookmark)
        layout.addWidget(self.bookmark_list)
        remove_btn = QPushButton("Remove selected bookmark")
        remove_btn.clicked.connect(self.remove_selected_bookmark)
        layout.addWidget(remove_btn)
        dock.setWidget(holder)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _fav_label(self):
        return "\u2605 Favorited" if self.book["is_favorite"] else "\u2606 Favorite"

    def _finished_label(self):
        return "\u2713 Finished" if self.book["status"] == "finished" else "Mark Finished"

    # ------------- Rendering -------------
    def _update_mode_visibility(self):
        self.scroll_area.setVisible(not self.simple_text_mode)
        self.text_browser.setVisible(self.simple_text_mode)

    def _compute_fit_zoom(self, page):
        """Zoom level that scales this page to fit the current viewport,
        preserving aspect ratio. Pages within a book can differ in size, so
        this is recalculated for every page rather than assumed constant."""
        rect = page.rect
        page_w, page_h = rect.width, rect.height
        if page_w <= 0 or page_h <= 0:
            return 1.0
        viewport = self.scroll_area.viewport()
        avail_w = viewport.width() - VIEWPORT_MARGIN
        avail_h = viewport.height() - VIEWPORT_MARGIN
        if avail_w <= 0 or avail_h <= 0:
            return 1.0  # window not laid out yet; corrected on the next showEvent/resize
        zoom = min(avail_w / page_w, avail_h / page_h)
        return max(MIN_ZOOM, min(zoom, MAX_ZOOM))

    def render_page(self):
        if self.doc is None:
            return
        page = self.doc[self.current_page]
        if self.simple_text_mode:
            text = page.get_text("text").strip() or "(This page has no extractable text.)"
            self.text_browser.setStyleSheet(f"font-size: {self.font_size}pt; padding: 24px;")
            self.text_browser.setPlainText(text)
        else:
            zoom = self._compute_fit_zoom(page) if self.auto_fit else self.zoom
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            if self.dark_mode:
                pix.invert_irect(pix.irect)
            fmt = QImage.Format_RGB888 if pix.n < 4 else QImage.Format_RGBA8888
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            self.page_label.setPixmap(QPixmap.fromImage(image.copy()))

        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)
        self.db.update_progress(self.book_id, self.current_page)

    # ------------- Navigation -------------
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if self.current_page < self.page_count - 1:
            self.current_page += 1
            self.render_page()

    def jump_to_page(self, value):
        page = value - 1
        if page != self.current_page and 0 <= page < self.page_count:
            self.current_page = page
            self.render_page()

    # ------------- View options -------------
    def increase_text_size(self):
        if self.simple_text_mode:
            self.font_size = min(self.font_size + 1, 48)
            self.db.set_setting("reader_font_size", self.font_size)
        else:
            self._leave_auto_fit_if_needed()
            self.zoom = min(round(self.zoom + 0.1, 2), MAX_ZOOM)
            self.db.set_setting("reader_zoom", self.zoom)
        self.render_page()

    def decrease_text_size(self):
        if self.simple_text_mode:
            self.font_size = max(self.font_size - 1, 8)
            self.db.set_setting("reader_font_size", self.font_size)
        else:
            self._leave_auto_fit_if_needed()
            self.zoom = max(round(self.zoom - 0.1, 2), MIN_ZOOM)
            self.db.set_setting("reader_zoom", self.zoom)
        self.render_page()

    def _leave_auto_fit_if_needed(self):
        """Manually adjusting zoom overrides auto-fit; start from the size the
        page is currently showing at so the change feels continuous."""
        if not self.auto_fit or self.doc is None:
            return
        self.zoom = self._compute_fit_zoom(self.doc[self.current_page])
        self.auto_fit = False
        self.fit_btn.setChecked(False)
        self.db.set_setting("reader_auto_fit", "0")

    def toggle_auto_fit(self, checked):
        self.fit_btn.setChecked(checked)
        self.auto_fit = checked
        self.db.set_setting("reader_auto_fit", "1" if checked else "0")
        self.render_page()

    def toggle_simple_text(self, checked):
        self.simple_btn.setChecked(checked)
        self.simple_text_mode = checked
        self.db.set_setting("reader_text_mode", "simple" if checked else "normal")
        self._update_mode_visibility()
        self.render_page()

    def toggle_dark_mode(self, checked):
        from PySide6.QtWidgets import QApplication

        self.dark_btn.setChecked(checked)
        self.dark_mode = checked
        theme = "dark" if checked else "light"
        self.db.set_setting("theme", theme)
        QApplication.instance().setStyleSheet(DARK_THEME if checked else LIGHT_THEME)
        self.render_page()

    def toggle_favorite(self):
        self.db.toggle_favorite(self.book_id)
        self.book = self.db.get_book(self.book_id)
        self.fav_btn.setText(self._fav_label())

    def toggle_finished(self, checked):
        self.finished_btn.setChecked(checked)
        status = "finished" if checked else "reading"
        self.db.set_status(self.book_id, status)
        self.book = self.db.get_book(self.book_id)
        self.finished_btn.setText(self._finished_label())

    # ------------- Bookmarks -------------
    def add_bookmark(self):
        label, ok = QInputDialog.getText(self, "Add bookmark", "Label (optional):")
        if not ok:
            return
        self.db.add_bookmark(self.book_id, self.current_page, label.strip())
        self.refresh_bookmarks()

    def refresh_bookmarks(self):
        self.bookmark_list.clear()
        for bm in self.db.get_bookmarks(self.book_id):
            text = f"Page {bm['page_number'] + 1}"
            if bm["label"]:
                text += f" \u2014 {bm['label']}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, bm["id"])
            item.setData(Qt.UserRole + 1, bm["page_number"])
            self.bookmark_list.addItem(item)

    def jump_to_bookmark(self, item):
        self.current_page = item.data(Qt.UserRole + 1)
        self.render_page()

    def remove_selected_bookmark(self):
        item = self.bookmark_list.currentItem()
        if not item:
            return
        self.db.delete_bookmark(item.data(Qt.UserRole))
        self.refresh_bookmarks()

    # ------------- Lifecycle -------------
    def showEvent(self, event):
        super().showEvent(event)
        # The viewport has no real size until the window is actually shown/laid
        # out, so the very first render_page() (called from __init__) may have
        # used a placeholder size. Recompute now that geometry is final.
        if self.auto_fit and not self.simple_text_mode and self.doc is not None:
            self.render_page()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit and not self.simple_text_mode and self.doc is not None:
            self._resize_timer.start(120)  # debounce so dragging the edge doesn't re-render every pixel

    def closeEvent(self, event):
        self._resize_timer.stop()  # cancel any pending debounced re-fit
        if self.doc is not None:
            self.db.update_progress(self.book_id, self.current_page)
            self.doc.close()
            self.doc = None
        if self.on_close:
            self.on_close()
        super().closeEvent(event)
