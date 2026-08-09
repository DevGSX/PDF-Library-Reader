"""Reader window: renders PDF pages, and supports simple-text mode, bookmarks,
text size / zoom, dark mode and favoriting a book while reading it."""
import pymupdf as fitz  # PyMuPDF (module renamed from "fitz")
from PySide6.QtCore import QEvent, Qt, QTimer
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
        self.dark_pages = db.get_setting("reader_dark_pages", "0") == "1"

        self.setWindowTitle(self.book["title"])
        self.resize(920, 800)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.render_page)

        self._panning = False
        self._pan_start_pos = None
        self._pan_start_h = 0
        self._pan_start_v = 0

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
        self.page_spin.setFocusPolicy(Qt.ClickFocus)  # don't let it grab arrow keys by default
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
        self.dark_btn.setToolTip("Light/dark app theme (toolbars, menus, text mode)")
        self.dark_btn.setCheckable(True)
        self.dark_btn.setChecked(self.dark_mode)
        self.dark_btn.clicked.connect(self.toggle_dark_mode)
        toolbar.addWidget(self.dark_btn)

        self.dark_pages_btn = QPushButton("Dark Pages")
        self.dark_pages_btn.setToolTip(
            "Invert rendered page colors (dark file), independent of the app theme"
        )
        self.dark_pages_btn.setCheckable(True)
        self.dark_pages_btn.setChecked(self.dark_pages)
        self.dark_pages_btn.clicked.connect(self.toggle_dark_pages)
        toolbar.addWidget(self.dark_pages_btn)

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

        self.bookmarks_btn = QPushButton("Bookmarks")
        self.bookmarks_btn.setToolTip("Show or hide the bookmarks panel")
        self.bookmarks_btn.setCheckable(True)
        self.bookmarks_btn.setChecked(True)  # the panel starts open
        self.bookmarks_btn.clicked.connect(self.toggle_bookmarks_dock)
        toolbar.addWidget(self.bookmarks_btn)

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

        # Ctrl+scroll to zoom, plain scroll to turn pages (see eventFilter / _handle_wheel).
        # Left-click-drag pans a zoomed-in page (see _handle_pan_*).
        self.scroll_area.viewport().installEventFilter(self)
        self.text_browser.viewport().installEventFilter(self)
        self.page_label.installEventFilter(self)

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

        self.bookmarks_dock = dock
        # Keep the toolbar button in sync if the panel is closed via its own
        # [x] button (or reopened some other way), not just via our toggle.
        dock.visibilityChanged.connect(self._on_bookmarks_dock_visibility_changed)

    def toggle_bookmarks_dock(self, checked):
        self.bookmarks_btn.setChecked(checked)
        self.bookmarks_dock.setVisible(checked)
        if checked:
            self.bookmarks_dock.raise_()

    def _on_bookmarks_dock_visibility_changed(self, visible):
        self.bookmarks_btn.setChecked(visible)

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
            if self.dark_pages:
                pix.invert_irect(pix.irect)
            fmt = QImage.Format_RGB888 if pix.n < 4 else QImage.Format_RGBA8888
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            self.page_label.setPixmap(QPixmap.fromImage(image.copy()))
            # Deferred: the scroll area's scrollbar range isn't updated synchronously
            # after setPixmap(), so evaluating "is this scrollable" has to wait for
            # the pending layout pass to actually finish.
            QTimer.singleShot(0, self._update_pan_cursor)

        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)
        self.db.update_progress(self.book_id, self.current_page)

    # ------------- Navigation -------------
    def keyPressEvent(self, event):
        # Belt-and-suspenders alongside the Prev/Next QAction shortcuts: guarantees
        # Left/Right always turn pages even if some focused child widget would
        # otherwise swallow the key first. Up/Down are intentionally left alone.
        if event.key() == Qt.Key_Left:
            self.prev_page()
            event.accept()
            return
        if event.key() == Qt.Key_Right:
            self.next_page()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and obj in (
            self.scroll_area.viewport(),
            self.text_browser.viewport(),
        ):
            return self._handle_wheel(event)
        if obj is self.page_label:
            if event.type() == QEvent.MouseButtonPress:
                return self._handle_pan_press(event)
            if event.type() == QEvent.MouseMove:
                return self._handle_pan_move(event)
            if event.type() == QEvent.MouseButtonRelease:
                return self._handle_pan_release(event)
        return super().eventFilter(obj, event)

    def _handle_wheel(self, event):
        """Ctrl+scroll zooms (or resizes text). Plain scroll turns pages only
        when the page is fit to the screen (nothing to accidentally scroll
        past) or in Simple Text mode (scroll past the top/bottom edge). Once
        you've zoomed in manually, plain scroll only pans the page -- holding
        the middle mouse button while scrolling explicitly turns the page
        instead, so you can't flip pages by accident while panning around a
        zoomed-in page."""
        if self.doc is None:
            return False

        modifiers = event.modifiers()

        if modifiers & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.increase_text_size()
            elif delta < 0:
                self.decrease_text_size()
            return True

        delta_y = event.angleDelta().y()
        if delta_y == 0:
            return False

        if self.simple_text_mode:
            vbar = self.text_browser.verticalScrollBar()
            at_top = vbar.value() <= vbar.minimum()
            at_bottom = vbar.value() >= vbar.maximum()
            if delta_y > 0 and not at_top:
                return False  # room to scroll up within the text -- let it scroll normally
            if delta_y < 0 and not at_bottom:
                return False  # room to scroll down within the text -- let it scroll normally
            if delta_y > 0:
                self.prev_page()
            else:
                self.next_page()
            return True

        if self.auto_fit:
            # Page fits the screen entirely -- nothing to accidentally scroll
            # past, so plain scroll always turns the page.
            if delta_y > 0:
                self.prev_page()
            else:
                self.next_page()
            return True

        # Zoomed in manually: plain scroll only pans, never changes pages by
        # accident. Holding the middle mouse button while scrolling is the
        # explicit "turn the page anyway" gesture.
        if event.buttons() & Qt.MiddleButton:
            if delta_y > 0:
                self.prev_page()
            else:
                self.next_page()
            return True

        return False  # let the scroll area pan normally

    # ------------- Click-and-drag panning (zoomed-in pages) -------------
    def _handle_pan_press(self, event):
        if event.button() != Qt.LeftButton or self.simple_text_mode:
            return False
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        if hbar.maximum() <= hbar.minimum() and vbar.maximum() <= vbar.minimum():
            return False  # page fits entirely -- nothing to pan
        self._panning = True
        self._pan_start_pos = event.globalPosition().toPoint()
        self._pan_start_h = hbar.value()
        self._pan_start_v = vbar.value()
        self.page_label.setCursor(Qt.ClosedHandCursor)
        return True

    def _handle_pan_move(self, event):
        if not self._panning:
            return False
        current = event.globalPosition().toPoint()
        delta = current - self._pan_start_pos
        self.scroll_area.horizontalScrollBar().setValue(self._pan_start_h - delta.x())
        self.scroll_area.verticalScrollBar().setValue(self._pan_start_v - delta.y())
        return True

    def _handle_pan_release(self, event):
        if event.button() != Qt.LeftButton or not self._panning:
            return False
        self._panning = False
        self._update_pan_cursor()
        return True

    def _update_pan_cursor(self):
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        scrollable = hbar.maximum() > hbar.minimum() or vbar.maximum() > vbar.minimum()
        self.page_label.setCursor(Qt.OpenHandCursor if scrollable else Qt.ArrowCursor)

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

    def toggle_dark_pages(self, checked):
        self.dark_pages_btn.setChecked(checked)
        self.dark_pages = checked
        self.db.set_setting("reader_dark_pages", "1" if checked else "0")
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
