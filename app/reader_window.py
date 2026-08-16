"""Reader window: renders PDF pages, and supports simple-text mode, bookmarks,
text size / zoom, dark mode, text selection/copy, two-page view, and
favoriting a book while reading it."""
import os

import pymupdf as fitz  # PyMuPDF (module renamed from "fitz")
from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFormLayout,
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
    QSpinBox,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .database import Database
from .highlights_notes import build_highlights_notes
from .search_dialog import TextSearchDialog
from .text_selection import (
    char_index_at_point,
    chars_from_rawdict,
    combined_selected_text,
    paragraph_bounds_at_index,
    resolve_multi_page_selection,
    selected_text as selected_text_for_range,
    selection_rects,
    word_bounds_at_index,
)
from .themes import DARK_THEME, LIGHT_THEME

MIN_ZOOM = 0.2
MAX_ZOOM = 6.0
VIEWPORT_MARGIN = 24  # px of breathing room so a fitted page never touches the edges
PAGE_GAP = 12  # px between the two pages in Two-Page View
DEFAULT_HIGHLIGHT_COLOR = "#3878FF"
FAR_POINT = (10 ** 9, 10 ** 9)     # a page-space point past any real content -- see char_index_at_point
NEAR_POINT = (-10 ** 9, -10 ** 9)  # ditto, before any real content


class TextSelectionOverlay(QWidget):
    """A transparent overlay sitting on top of the rendered page pixmap.
    Only shown while "Select Text" mode is on -- lets you drag over the
    page and highlights exactly the text a real PDF viewer would, in
    reading order (not just whatever falls inside the drag rectangle:
    see app/text_selection.py for why that distinction matters). Layered
    over the pixel-perfect rendered image rather than replacing it, so
    visual fidelity (fonts, layout, embedded images) is unaffected.

    The overlay only tracks raw mouse positions; all the actual text
    logic (which words are selected, what rectangles to highlight) lives
    in ReaderWindow, which knows about pages, zoom, and two-page offsets
    that this widget doesn't need to care about."""

    def __init__(self, reader, parent=None):
        super().__init__(parent)
        self.reader = reader
        self.setCursor(Qt.IBeamCursor)
        self._drag_start = None
        self._drag_current = None
        self._highlight_rects = []
        self._saved_highlights = []
        self._live_color = QColor(60, 120, 255, 90)
        self._click_count = 0
        self._last_click_pos = None
        self._click_timer = QElapsedTimer()
        self._autoscroll_direction = 0
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(30)
        self._autoscroll_timer.timeout.connect(self._autoscroll_step)
        self.hide()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        if self._is_rapid_repeat_click(pos):
            self._click_count += 1
        else:
            self._click_count = 1
        self._register_click(pos)

        if self._click_count >= 3:
            # Qt has no native triple-click event -- the 2nd click of any
            # rapid sequence already arrives as mouseDoubleClickEvent
            # below, so a 3rd press this close in time and position to it
            # is the triple-click.
            self.reader.select_word_or_paragraph_at(pos, paragraph=True)
            self.reader.show_selection_popup()
            self._click_count = 0  # a 4th click starts a fresh count, not "quadruple"
            return

        self.reader.selection_popup.hide()  # a fresh drag replaces whatever was selected before
        self._drag_start = pos
        self._drag_current = pos
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        self._drag_current = event.position()
        self.reader.update_text_selection(self._drag_start, self._drag_current, finished=False)
        self._update_autoscroll(self._drag_current)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_start is None or event.button() != Qt.LeftButton:
            return
        start, end = self._drag_start, self._drag_current
        self._drag_start = None
        self._drag_current = None
        self._autoscroll_timer.stop()
        self._autoscroll_direction = 0
        self.reader.update_text_selection(start, end, finished=True)
        self.reader.show_selection_popup()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        self._click_count = 2
        self._register_click(pos)
        self.reader.select_word_or_paragraph_at(pos, paragraph=False)
        self.reader.show_selection_popup()

    def _is_rapid_repeat_click(self, pos):
        if self._last_click_pos is None or not self._click_timer.isValid():
            return False
        close_enough = (pos - self._last_click_pos).manhattanLength() < 6
        fast_enough = self._click_timer.elapsed() < QApplication.doubleClickInterval()
        return close_enough and fast_enough

    def _register_click(self, pos):
        self._last_click_pos = pos
        self._click_timer.restart()

    def _update_autoscroll(self, drag_pos):
        """While dragging a selection, if the mouse is near the top/bottom
        edge of the visible scroll area, keep scrolling in that direction
        for as long as it stays there -- otherwise a selection that needs
        to extend past what's currently on screen is simply impossible to
        make, since the mouse can't drag past the viewport's own edge."""
        viewport_pos = self.mapTo(self.reader.scroll_area.viewport(), drag_pos.toPoint())
        viewport_h = self.reader.scroll_area.viewport().height()
        margin = 40
        if viewport_pos.y() < margin:
            self._autoscroll_direction = -1
        elif viewport_pos.y() > viewport_h - margin:
            self._autoscroll_direction = 1
        else:
            self._autoscroll_direction = 0

        if self._autoscroll_direction != 0 and not self._autoscroll_timer.isActive():
            self._autoscroll_timer.start()
        elif self._autoscroll_direction == 0:
            self._autoscroll_timer.stop()

    def _autoscroll_step(self):
        if self._autoscroll_direction == 0 or self._drag_start is None:
            self._autoscroll_timer.stop()
            return
        vbar = self.reader.scroll_area.verticalScrollBar()
        vbar.setValue(vbar.value() + self._autoscroll_direction * 18)
        # The page hasn't moved, only the viewport's scroll position, so
        # the drag's live highlight needs to be recomputed against the
        # same (unchanged) overlay-space coordinates -- but since the
        # mouse itself hasn't moved, re-driving the same current drag
        # point is enough to keep the highlight extending correctly.
        self.reader.update_text_selection(self._drag_start, self._drag_current, finished=False)

    def contextMenuEvent(self, event):
        pos = event.position()
        menu = QMenu(self)
        if self.reader.selected_text:
            copy_action = menu.addAction("Copy")
            search_action = menu.addAction("Search in Book")
            save_action = menu.addAction("Save Highlight...")
            select_all_action = menu.addAction("Select All")
            chosen = menu.exec(event.globalPos())
            if chosen is copy_action:
                self.reader.copy_selection()
            elif chosen is search_action:
                self.reader.search_selection_in_book()
            elif chosen is save_action:
                self.reader.save_selection_as_highlight()
            elif chosen is select_all_action:
                self.reader.select_all_text()
            return

        existing = self.highlight_at_point(pos)
        if existing is not None:
            edit_action = menu.addAction("Edit Highlight...")
            delete_action = menu.addAction("Delete Highlight")
            chosen = menu.exec(event.globalPos())
            if chosen is edit_action:
                self.reader.edit_highlight(existing["id"])
            elif chosen is delete_action:
                self.reader.delete_highlight(existing["id"])
            return

        select_all_action = menu.addAction("Select All")
        chosen = menu.exec(event.globalPos())
        if chosen is select_all_action:
            self.reader.select_all_text()

    def set_highlight_rects(self, rects):
        self._highlight_rects = rects
        self.update()

    def set_live_color(self, color):
        self._live_color = QColor(color)
        self.update()

    def set_saved_highlights(self, highlights):
        """highlights: a list of {"id": int, "color": QColor, "rects":
        [QRectF, ...]} -- already converted to this overlay's own pixel
        space by the caller (ReaderWindow knows about zoom and two-page
        offsets that this widget doesn't need to)."""
        self._saved_highlights = highlights
        self.update()

    def highlight_at_point(self, pos):
        """The saved highlight (as passed to set_saved_highlights) whose
        rects contain `pos`, or None. Used to route a right-click either
        to the "made a new selection" menu or the "clicked an existing
        highlight" menu."""
        for h in self._saved_highlights:
            for r in h["rects"]:
                if r.contains(pos):
                    return h
        return None

    def clear(self):
        self._drag_start = None
        self._drag_current = None
        self._highlight_rects = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Saved highlights draw first (underneath), each in its own
        # stored color and style, so the just-finished selection (drawn
        # last, below) is never visually lost underneath one it overlaps.
        for h in self._saved_highlights:
            self._paint_highlight(painter, h["rects"], QColor(h["color"]), h.get("style", "fill"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._live_color)
        for r in self._highlight_rects:
            painter.drawRect(r)
        painter.end()

    @staticmethod
    def _paint_highlight(painter, rects, color, style):
        if style == "underline":
            pen_color = QColor(color)
            pen_color.setAlpha(220)
            painter.setPen(QPen(pen_color, 2))
            painter.setBrush(Qt.NoBrush)
            for r in rects:
                y = r.bottom() - 1
                painter.drawLine(r.left(), y, r.right(), y)
        elif style == "strikethrough":
            pen_color = QColor(color)
            pen_color.setAlpha(220)
            painter.setPen(QPen(pen_color, 2))
            painter.setBrush(Qt.NoBrush)
            for r in rects:
                y = r.top() + r.height() / 2
                painter.drawLine(r.left(), y, r.right(), y)
        else:  # "fill" -- a translucent highlighter-marker block
            fill_color = QColor(color)
            fill_color.setAlpha(110)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            for r in rects:
                painter.drawRect(r)


class SelectionPopup(QWidget):
    """A small floating toolbar that appears next to a just-finished text
    selection -- offering Copy and Search in Book right there, instead of
    only via the right-click menu or Ctrl+C. A plain child widget of the
    ReaderWindow itself (not a separate top-level popup), positioned with
    an explicit move() and shown/hidden explicitly, rather than relying
    on a native popup window's own focus/dismiss behavior -- simpler and
    more predictable than fighting Qt.Popup's auto-grab quirks."""

    def __init__(self, reader, parent=None):
        super().__init__(parent)
        self.reader = reader
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "SelectionPopup { background: palette(window); border: 1px solid palette(mid); "
            "border-radius: 4px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        copy_btn = QPushButton("Copy")
        copy_btn.setFlat(True)
        copy_btn.clicked.connect(self._copy)
        layout.addWidget(copy_btn)
        search_btn = QPushButton("Search in Book")
        search_btn.setFlat(True)
        search_btn.clicked.connect(self._search)
        layout.addWidget(search_btn)
        save_btn = QPushButton("Save Highlight")
        save_btn.setFlat(True)
        save_btn.clicked.connect(self._save_highlight)
        layout.addWidget(save_btn)
        self.hide()

    def _copy(self):
        self.reader.copy_selection()
        self.hide()

    def _search(self):
        self.reader.search_selection_in_book()
        self.hide()

    def _save_highlight(self):
        self.reader.save_selection_as_highlight()
        self.hide()

    def show_near(self, local_pos):
        self.adjustSize()
        self.move(int(local_pos.x()), int(local_pos.y()) + 14)
        self.show()
        self.raise_()


class HighlightDialog(QDialog):
    """Prompts for a highlight's name, color, and style -- used both when
    saving a brand new highlight and when editing an existing one. The
    color swatch always starts on whatever color was already chosen (the
    current default when saving new, or the highlight's own color when
    editing), and "Choose Color..." opens the full picker (basic swatches,
    a spectrum/wheel, and exact RGB/HSV/hex entry) to change it -- letting
    someone highlight different passages in different colors of their own
    choosing, one save at a time. Style picks between a solid highlighter
    fill, an underline, or a strikethrough, matching the distinct
    annotation tools a real PDF editor offers rather than just one look.
    When editing an existing highlight, text_preview shows what was
    actually highlighted, read-only, so it's easy to tell highlights
    apart without having to jump to the page."""

    STYLES = [("fill", "Highlight (fill)"), ("underline", "Underline"), ("strikethrough", "Strikethrough")]

    def __init__(self, title, initial_name, initial_color, initial_style="fill", text_preview=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._color = QColor(initial_color)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(initial_name or "")
        self.name_edit.setPlaceholderText("Leave blank to use the page number")
        form.addRow("Name", self.name_edit)

        color_row = QHBoxLayout()
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(22, 22)
        self._update_swatch()
        color_row.addWidget(self.color_swatch)
        choose_btn = QPushButton("Choose Color...")
        choose_btn.clicked.connect(self._choose_color)
        color_row.addWidget(choose_btn)
        color_row.addStretch()
        form.addRow("Color", color_row)

        self.style_combo = QComboBox()
        for value, label in self.STYLES:
            self.style_combo.addItem(label, value)
        idx = self.style_combo.findData(initial_style)
        self.style_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Style", self.style_combo)
        layout.addLayout(form)

        if text_preview is not None:
            preview_label = QLabel("Highlighted text:")
            layout.addWidget(preview_label)
            preview = QTextBrowser()
            preview.setPlainText(text_preview or "(no text captured)")
            preview.setReadOnly(True)
            preview.setMaximumHeight(110)
            layout.addWidget(preview)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _update_swatch(self):
        self.color_swatch.setStyleSheet(
            f"background-color: {self._color.name()}; border: 1px solid palette(mid);"
        )

    def _choose_color(self):
        color = QColorDialog.getColor(self._color, self, "Choose Highlight Color")
        if color.isValid():
            self._color = color
            self._update_swatch()

    def result_values(self):
        """(name, QColor, style) -- call only after exec() returns QDialog.Accepted."""
        return self.name_edit.text().strip(), self._color, self.style_combo.currentData()


class ReaderWindow(QMainWindow):
    def __init__(self, db: Database, book_id: int, on_close=None, password=None, open_book_at_page=None):
        super().__init__()
        self.db = db
        self.book_id = book_id
        self.on_close = on_close
        self.open_book_at_page = open_book_at_page  # callback(book_id, page_number) -- lets a
        # search result for a DIFFERENT book (searching is library-wide) actually open it;
        # this window has no way to do that itself, since it only ever owns one book

        db.mark_as_reading_if_new(book_id)  # first open promotes 'unread' -> 'reading'
        self.book = db.get_book(book_id)

        try:
            self.doc = fitz.open(self.book["filepath"])
            if self.doc.needs_pass:
                # The caller (library_window.open_book) already verified this
                # password is correct before ever constructing this window.
                self.doc.authenticate(password or "")
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
        self.two_page_mode = db.get_setting("reader_two_page", "0") == "1"
        if self.two_page_mode:
            self.current_page = self._pair_start(self.current_page)

        self.setWindowTitle(self.book["title"])
        self.resize(920, 800)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.render_page)

        self._panning = False
        self._pan_start_pos = None
        self._pan_start_h = 0
        self._pan_start_v = 0

        self._current_render_zoom = 1.0

        self.select_text_mode = False
        self.selected_text = ""
        self._chars_cache = {}  # page_index -> chars_from_rawdict() result, built lazily
        self._left_page_px_width = 0  # set on every two-page render; used to map clicks to the right page
        self._pending_overlay_size = (0, 0)
        self._last_selection_pos = None  # overlay-local point to anchor the selection popup near
        self._search_dialog = None
        self._last_selection_page_ranges = []
        self._last_selection_chars_by_page = {}
        self.highlight_color = db.get_setting("highlight_color", DEFAULT_HIGHLIGHT_COLOR)

        self._build_ui()
        self._build_bookmarks_dock()
        self.render_page()
        self.refresh_bookmarks()
        self.refresh_highlights()

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

        self.two_page_btn = QPushButton("Two-Page View")
        self.two_page_btn.setToolTip(
            "Show two pages side by side, like a book spread -- handy on a wide screen"
        )
        self.two_page_btn.setCheckable(True)
        self.two_page_btn.setChecked(self.two_page_mode)
        self.two_page_btn.clicked.connect(self.toggle_two_page_mode)
        toolbar.addWidget(self.two_page_btn)

        toolbar.addSeparator()

        self.select_text_btn = QPushButton("Select Text")
        self.select_text_btn.setCheckable(True)
        self.select_text_btn.clicked.connect(self.toggle_select_text_mode)
        toolbar.addWidget(self.select_text_btn)

        highlight_color_btn = QPushButton("Highlight Color")
        highlight_color_btn.setToolTip(
            "Set the default color used for the live selection highlight and for new saved highlights"
        )
        highlight_color_btn.clicked.connect(self.choose_default_highlight_color)
        toolbar.addWidget(highlight_color_btn)

        self.copy_feedback_label = QLabel("")
        self.copy_feedback_label.setStyleSheet("color: #888; padding-left: 6px;")
        toolbar.addWidget(self.copy_feedback_label)

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

        self.bookmarks_btn = QPushButton("Bookmarks/Highlights")
        self.bookmarks_btn.setToolTip("Show or hide the bookmarks and highlights panel")
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

        self.text_overlay = TextSelectionOverlay(self, self.page_label)
        live_color = QColor(self.highlight_color)
        live_color.setAlpha(90)
        self.text_overlay.set_live_color(live_color)
        self.selection_popup = SelectionPopup(self, self)

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
        dock = QDockWidget("Bookmarks/Highlights", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        holder = QWidget()
        layout = QVBoxLayout(holder)

        # Bookmarks stay on top...
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemDoubleClicked.connect(self.jump_to_bookmark)
        layout.addWidget(self.bookmark_list)
        remove_btn = QPushButton("Remove selected bookmark")
        remove_btn.clicked.connect(self.remove_selected_bookmark)
        layout.addWidget(remove_btn)

        # ...with Highlights right below, in the same scrollable panel, so
        # both are easy to browse without needing a whole separate dock.
        highlights_label = QLabel("Highlights")
        highlights_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(highlights_label)
        self.highlight_list = QListWidget()
        self.highlight_list.itemDoubleClicked.connect(self.jump_to_highlight)
        self.highlight_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.highlight_list.customContextMenuRequested.connect(self._show_highlight_list_menu)
        layout.addWidget(self.highlight_list)
        remove_highlight_btn = QPushButton("Remove selected highlight")
        remove_highlight_btn.clicked.connect(self.remove_selected_highlight)
        layout.addWidget(remove_highlight_btn)

        export_highlights_btn = QPushButton("Export Highlights...")
        export_highlights_btn.setToolTip(
            "Save every highlight in this book as a plain-text notes file (Markdown)"
        )
        export_highlights_btn.clicked.connect(self.export_highlights_notes)
        layout.addWidget(export_highlights_btn)

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
        # Simple Text mode already supports selecting/copying its text
        # natively (it's a plain QTextBrowser) -- our custom drag-select
        # overlay only applies to the rendered page image.
        self.select_text_btn.setEnabled(not self.simple_text_mode)
        self.select_text_btn.setToolTip(
            "Text in Simple Text mode can already be selected and copied directly"
            if self.simple_text_mode else
            "Drag over text on the page to select it, then Ctrl+C or right-click to copy"
        )
        if self.simple_text_mode:
            self.text_overlay.hide()
        else:
            # The overlay stays visible whenever there's a rendered page to
            # show it over -- even outside Select Text mode -- so saved
            # highlights are always visible while reading normally, not
            # just while actively selecting. It only INTERCEPTS mouse
            # input (for making a new selection) while Select Text mode
            # is on; otherwise clicks pass through to the page underneath
            # so panning keeps working exactly as before.
            self.text_overlay.show()
            self.text_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, not self.select_text_mode)
        # Two-Page View is a rendered-image concept, so it doesn't apply to
        # Simple Text mode's plain extracted text either.
        self.two_page_btn.setEnabled(not self.simple_text_mode)
        self.two_page_btn.setToolTip(
            "Not available in Simple Text mode"
            if self.simple_text_mode else
            "Show two pages side by side, like a book spread -- handy on a wide screen"
        )

    def _compute_fit_zoom(self, page):
        """Zoom level that scales this page to fit the current viewport,
        preserving aspect ratio. Pages within a book can differ in size, so
        this is recalculated for every page rather than assumed constant."""
        rect = page.rect
        return self._fit_zoom_for_size(rect.width, rect.height)

    def _compute_fit_zoom_two_page(self, left_page, right_page):
        """Like _compute_fit_zoom, but fits BOTH pages side by side (their
        combined width, and the taller of the two heights) into the viewport."""
        left_rect = left_page.rect
        right_rect = right_page.rect if right_page is not None else left_rect
        combined_w = left_rect.width + PAGE_GAP + (right_rect.width if right_page is not None else 0)
        combined_h = max(left_rect.height, right_rect.height)
        return self._fit_zoom_for_size(combined_w, combined_h)

    def _fit_zoom_for_size(self, content_w, content_h):
        if content_w <= 0 or content_h <= 0:
            return 1.0
        viewport = self.scroll_area.viewport()
        avail_w = viewport.width() - VIEWPORT_MARGIN
        avail_h = viewport.height() - VIEWPORT_MARGIN
        if avail_w <= 0 or avail_h <= 0:
            return 1.0  # window not laid out yet; corrected on the next showEvent/resize
        zoom = min(avail_w / content_w, avail_h / content_h)
        return max(MIN_ZOOM, min(zoom, MAX_ZOOM))

    @staticmethod
    def _pair_start(page_index):
        """The left-hand page index of the two-page spread containing this
        page (spreads pair 0&1, 2&3, 4&5, ... -- the common convention most
        readers use without a separate "cover page alone" exception)."""
        return page_index - (page_index % 2)

    def render_page(self):
        if self.doc is None:
            return
        if self.simple_text_mode:
            page = self.doc[self.current_page]
            text = page.get_text("text").strip() or "(This page has no extractable text.)"
            self.text_browser.setStyleSheet(f"font-size: {self.font_size}pt; padding: 24px;")
            self.text_browser.setPlainText(text)
        elif self.two_page_mode:
            self._render_two_page_spread()
        else:
            self._render_single_page()

        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)
        self.db.update_progress(self.book_id, self.current_page)

    def _render_single_page(self):
        page = self.doc[self.current_page]
        zoom = self._compute_fit_zoom(page) if self.auto_fit else self.zoom
        self._current_render_zoom = zoom
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        if self.dark_pages:
            pix.invert_irect(pix.irect)
        fmt = QImage.Format_RGB888 if pix.n < 4 else QImage.Format_RGBA8888
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        self.page_label.setPixmap(QPixmap.fromImage(image.copy()))
        self._sync_overlay_geometry(pix.width, pix.height)

    def _render_two_page_spread(self):
        left_idx = self._pair_start(self.current_page)
        right_idx = left_idx + 1
        left_page = self.doc[left_idx]
        right_page = self.doc[right_idx] if right_idx < self.page_count else None

        zoom = self._compute_fit_zoom_two_page(left_page, right_page) if self.auto_fit else self.zoom
        self._current_render_zoom = zoom
        matrix = fitz.Matrix(zoom, zoom)

        left_pix = left_page.get_pixmap(matrix=matrix)
        right_pix = right_page.get_pixmap(matrix=matrix) if right_page is not None else None
        if self.dark_pages:
            left_pix.invert_irect(left_pix.irect)
            if right_pix is not None:
                right_pix.invert_irect(right_pix.irect)

        total_w = left_pix.width + PAGE_GAP + (right_pix.width if right_pix is not None else 0)
        total_h = max(left_pix.height, right_pix.height if right_pix is not None else 0)

        combined = QImage(total_w, total_h, QImage.Format_RGB888)
        combined.fill(QColor(60, 60, 60) if self.dark_pages else QColor(235, 235, 235))
        painter = QPainter(combined)
        left_fmt = QImage.Format_RGB888 if left_pix.n < 4 else QImage.Format_RGBA8888
        painter.drawImage(0, 0, QImage(left_pix.samples, left_pix.width, left_pix.height, left_pix.stride, left_fmt))
        if right_pix is not None:
            right_fmt = QImage.Format_RGB888 if right_pix.n < 4 else QImage.Format_RGBA8888
            painter.drawImage(
                left_pix.width + PAGE_GAP, 0,
                QImage(right_pix.samples, right_pix.width, right_pix.height, right_pix.stride, right_fmt),
            )
        painter.end()

        # Text selection needs this later (mouse events arrive well after
        # this render call returns) to know where the right page starts
        # in the combined image's pixel space.
        self._left_page_px_width = left_pix.width

        self.page_label.setPixmap(QPixmap.fromImage(combined))
        self._sync_overlay_geometry(total_w, total_h)

    def _sync_overlay_geometry(self, width, height):
        # A new page/zoom/spread invalidates any old highlight immediately.
        self.text_overlay.clear()
        self.selected_text = ""
        self.selection_popup.hide()
        self._pending_overlay_size = (width, height)
        self._load_saved_highlights_for_current_view()
        self._check_no_selectable_text()
        # Deferred: page_label is resized to fill the scroll area's viewport
        # (setWidgetResizable(True)) and centers the pixmap within itself
        # (AlignCenter) whenever the page is smaller than the window --  so
        # the overlay has to be positioned at the pixmap's actual centered
        # offset within the label, not just the label's own (0, 0) origin,
        # or it ends up sitting over empty label space instead of the page
        # itself. But page_label's post-resize size isn't guaranteed to be
        # up to date synchronously right after setPixmap() -- same reason
        # _update_pan_cursor below already has to wait a beat -- so this
        # has to be computed after the pending layout pass actually finishes.
        QTimer.singleShot(0, self._apply_pending_overlay_geometry)
        QTimer.singleShot(0, self._update_pan_cursor)

    def _apply_pending_overlay_geometry(self):
        width, height = self._pending_overlay_size
        offset_x = max(0, (self.page_label.width() - width) // 2)
        offset_y = max(0, (self.page_label.height() - height) // 2)
        self.text_overlay.setGeometry(offset_x, offset_y, width, height)
        self.text_overlay.raise_()

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
        if event.matches(QKeySequence.Copy) and self.selected_text:
            self.copy_selection()
            event.accept()
            return
        if event.matches(QKeySequence.SelectAll) and self.select_text_mode and not self.simple_text_mode:
            self.select_all_text()
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

    # ------------- Text selection / copy -------------
    def toggle_select_text_mode(self, checked):
        self.select_text_btn.setChecked(checked)
        self.select_text_mode = checked
        if not self.simple_text_mode:
            self.text_overlay.show()  # stays visible either way, to show saved highlights
            self.text_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, not checked)
        if not checked:
            self.text_overlay.clear()
            self.selected_text = ""
            self.selection_popup.hide()
            self._update_pan_cursor()
        else:
            self._check_no_selectable_text()

    def _get_page_chars(self, page_index):
        """get_text("rawdict") is a real (if fast) PDF-parsing call, and
        this can be invoked many times per second while dragging -- cache
        each page's character list the first time it's needed rather
        than re-extracting it on every mouse-move event."""
        if page_index not in self._chars_cache:
            self._chars_cache[page_index] = chars_from_rawdict(self.doc[page_index].get_text("rawdict"))
        return self._chars_cache[page_index]

    def _page_and_point_at(self, overlay_pos):
        """Maps a point in the overlay's pixel coordinates (same space as
        the rendered pixmap) to (page_index, (x, y)) in that page's own
        PDF coordinate space -- accounting for the current zoom, and in
        Two-Page View, for which of the two pages the point actually
        falls on and that page's x-offset within the combined image.
        This is exactly the mapping the old implementation got wrong: it
        always resolved to self.current_page (the left page), regardless
        of where the point actually was."""
        zoom = self._current_render_zoom or 1.0
        x, y = overlay_pos.x(), overlay_pos.y()
        if not self.two_page_mode:
            return self.current_page, (x / zoom, y / zoom)

        left_idx = self._pair_start(self.current_page)
        right_idx = left_idx + 1
        boundary = self._left_page_px_width + PAGE_GAP / 2
        if x < boundary or right_idx >= self.page_count:
            return left_idx, (x / zoom, y / zoom)
        x_offset = self._left_page_px_width + PAGE_GAP
        return right_idx, ((x - x_offset) / zoom, y / zoom)

    def _page_x_offset_px(self, page_index):
        """Inverse of the offset applied in _page_and_point_at -- how far
        (in overlay pixels) this page's own (0, 0) sits from the combined
        image's left edge. 0 in single-page mode or for the left page of
        a spread; the left page's rendered width plus the gap for the
        right page."""
        if not self.two_page_mode or page_index == self._pair_start(self.current_page):
            return 0
        return self._left_page_px_width + PAGE_GAP

    def update_text_selection(self, start_pos, end_pos, finished):
        """Recomputes the highlighted rectangles and pending selected text
        for a drag from start_pos to end_pos (both in overlay pixel
        coordinates, in either order). Called continuously while dragging
        (finished=False, for a live-updating highlight -- not just
        computed once when the mouse button comes up) and once more on
        release (finished=True)."""
        if self.doc is None:
            return
        rect = QRectF(start_pos, end_pos).normalized()
        if finished and rect.width() < 3 and rect.height() < 3:
            # A near-zero-size drag is a click, not a real selection --
            # clear any existing highlight rather than "select" a sliver.
            self.text_overlay.set_highlight_rects([])
            self.selected_text = ""
            self.selection_popup.hide()
            return

        start_page, start_pt = self._page_and_point_at(start_pos)
        end_page, end_pt = self._page_and_point_at(end_pos)
        chars_by_page = {start_page: self._get_page_chars(start_page)}
        if end_page != start_page:
            chars_by_page[end_page] = self._get_page_chars(end_page)

        page_ranges = resolve_multi_page_selection(chars_by_page, start_page, start_pt, end_page, end_pt)
        self._apply_page_ranges(page_ranges, chars_by_page)
        self._last_selection_pos = end_pos

    def select_word_or_paragraph_at(self, pos, paragraph):
        """Double-click (paragraph=False) selects the whole word under
        pos; triple-click (paragraph=True) selects its whole paragraph,
        however many lines it wraps to. pos is in overlay pixel
        coordinates, same as update_text_selection."""
        if self.doc is None:
            return
        page_idx, (x, y) = self._page_and_point_at(pos)
        chars = self._get_page_chars(page_idx)
        if not chars:
            return
        idx = char_index_at_point(chars, x, y)
        if idx is None:
            return
        bounds = paragraph_bounds_at_index(chars, idx) if paragraph else word_bounds_at_index(chars, idx)
        if bounds is None:
            return
        self._apply_page_ranges([(page_idx, *bounds)], {page_idx: chars})
        self._last_selection_pos = pos

    def select_all_text(self):
        """Selects everything on the current page (or both pages of the
        current spread, in Two-Page View)."""
        if self.doc is None:
            return
        if self.two_page_mode:
            left_idx = self._pair_start(self.current_page)
            right_idx = left_idx + 1
            start_page, end_page = left_idx, (right_idx if right_idx < self.page_count else left_idx)
        else:
            start_page = end_page = self.current_page

        chars_by_page = {start_page: self._get_page_chars(start_page)}
        if end_page != start_page:
            chars_by_page[end_page] = self._get_page_chars(end_page)
        page_ranges = resolve_multi_page_selection(chars_by_page, start_page, NEAR_POINT, end_page, FAR_POINT)
        self._apply_page_ranges(page_ranges, chars_by_page)
        if self.selected_text:
            self.copy_feedback_label.setText(f"{len(self.selected_text)} characters selected")
            QTimer.singleShot(2500, lambda: self.copy_feedback_label.setText(""))

    def _apply_page_ranges(self, page_ranges, chars_by_page):
        """Shared by update_text_selection, select_word_or_paragraph_at,
        and select_all_text: turns a list of (page_index, start_char,
        end_char) ranges into the actual selected text and the overlay's
        highlight rectangles (each scaled by zoom and shifted by that
        page's x-offset in the combined image, so a right-page rect in
        Two-Page View lands in the right place)."""
        self.selected_text = combined_selected_text(chars_by_page, page_ranges)
        self._last_selection_page_ranges = page_ranges  # used by save_selection_as_highlight
        self._last_selection_chars_by_page = chars_by_page
        highlight_rects = []
        zoom = self._current_render_zoom or 1.0
        for (page_idx, s, e) in page_ranges:
            x_offset = self._page_x_offset_px(page_idx)
            for (rx0, ry0, rx1, ry1) in selection_rects(chars_by_page[page_idx], s, e):
                highlight_rects.append(QRectF(
                    rx0 * zoom + x_offset, ry0 * zoom, (rx1 - rx0) * zoom, (ry1 - ry0) * zoom,
                ))
        self.text_overlay.set_highlight_rects(highlight_rects)

    # ------------- Saved (persistent) highlights -------------
    def _visible_page_indices(self):
        """The page index(es) currently on screen -- just current_page in
        single-page mode, or the current spread's pages in Two-Page View."""
        if not self.two_page_mode:
            return [self.current_page]
        left_idx = self._pair_start(self.current_page)
        right_idx = left_idx + 1
        return [left_idx] + ([right_idx] if right_idx < self.page_count else [])

    def _load_saved_highlights_for_current_view(self):
        """Loads every saved highlight for whichever page(s) are currently
        visible, converts each one's stored PDF-point rects to this
        render's pixel space, and hands them to the overlay to draw.
        Called on every render (new page, zoom change, or spread), so a
        saved highlight always shows up correctly regardless of zoom
        level or which page it happens to fall on in Two-Page View."""
        if self.doc is None:
            return
        zoom = self._current_render_zoom or 1.0

        overlay_highlights = []
        for page_idx in self._visible_page_indices():
            x_offset = self._page_x_offset_px(page_idx)
            for h in self.db.get_highlights_for_page(self.book_id, page_idx):
                rects = [
                    QRectF(x0 * zoom + x_offset, y0 * zoom, (x1 - x0) * zoom, (y1 - y0) * zoom)
                    for (x0, y0, x1, y1) in h["rects"]
                ]
                overlay_highlights.append({
                    "id": h["id"], "color": QColor(h["color"]), "rects": rects,
                    "style": h.get("style") or "fill",
                })
        self.text_overlay.set_saved_highlights(overlay_highlights)

    def _check_no_selectable_text(self):
        """While Select Text mode is on, if the current page (or both
        pages of a spread) has no extractable text at all -- most likely
        a scanned image with no OCR text layer -- let the user know via
        the same feedback label used for copy/select-all messages,
        instead of leaving them to wonder why dragging over the page
        silently does nothing."""
        if self.doc is None or not self.select_text_mode:
            return
        has_text = any(self._get_page_chars(p) for p in self._visible_page_indices())
        if not has_text:
            self.copy_feedback_label.setText(
                "No selectable text on this page \u2014 it may be a scanned image"
            )
            QTimer.singleShot(4000, lambda: self.copy_feedback_label.setText(""))

    def save_selection_as_highlight(self):
        if not self.selected_text or not self._last_selection_page_ranges:
            return
        dialog = HighlightDialog("Save Highlight", "", self.highlight_color, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        custom_name, color, style = dialog.result_values()
        chars_by_page = self._last_selection_chars_by_page
        for (page_idx, s, e) in self._last_selection_page_ranges:
            chars = chars_by_page.get(page_idx)
            if not chars:
                continue
            rects = selection_rects(chars, s, e)
            text = selected_text_for_range(chars, s, e)
            label = custom_name or self._default_highlight_label(page_idx)
            self.db.add_highlight(
                self.book_id, page_idx, color.name(), rects, text=text, label=label, style=style
            )
        self.selected_text = ""
        self.text_overlay.set_highlight_rects([])
        self.selection_popup.hide()
        self._load_saved_highlights_for_current_view()
        self.refresh_highlights()

    def _default_highlight_label(self, page_idx):
        """"Page N" for the first highlight on a page when the user
        doesn't type a name of their own; "Page N - 1", "Page N - 2", etc.
        for subsequent ones on that same page, so they stay distinguishable
        in the sidebar list."""
        existing_count = len(self.db.get_highlights_for_page(self.book_id, page_idx))
        if existing_count == 0:
            return f"Page {page_idx + 1}"
        return f"Page {page_idx + 1} - {existing_count}"

    def delete_highlight(self, highlight_id):
        self.db.delete_highlight(highlight_id)
        self._load_saved_highlights_for_current_view()
        self.refresh_highlights()

    def edit_highlight(self, highlight_id):
        highlight = next((h for h in self.db.get_highlights(self.book_id) if h["id"] == highlight_id), None)
        if highlight is None:
            return
        dialog = HighlightDialog(
            "Edit Highlight", highlight["label"], highlight["color"],
            initial_style=highlight.get("style") or "fill", text_preview=highlight["text"], parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        name, color, style = dialog.result_values()
        label = name or f"Page {highlight['page_number'] + 1}"
        self.db.update_highlight_label(highlight_id, label)
        self.db.update_highlight_color(highlight_id, color.name())
        self.db.update_highlight_style(highlight_id, style)
        self._load_saved_highlights_for_current_view()
        self.refresh_highlights()

    def choose_default_highlight_color(self):
        color = QColorDialog.getColor(QColor(self.highlight_color), self, "Default Highlight Color")
        if not color.isValid():
            return
        self.highlight_color = color.name()
        self.db.set_setting("highlight_color", self.highlight_color)
        live_color = QColor(self.highlight_color)
        live_color.setAlpha(90)
        self.text_overlay.set_live_color(live_color)



    def copy_selection(self):
        if not self.selected_text:
            return
        QApplication.clipboard().setText(self.selected_text)
        self._flash_copy_feedback(len(self.selected_text))

    def _flash_copy_feedback(self, n_chars):
        self.copy_feedback_label.setText(f"Copied {n_chars} character{'s' if n_chars != 1 else ''}")
        QTimer.singleShot(2500, lambda: self.copy_feedback_label.setText(""))

    def show_selection_popup(self):
        if not self.selected_text or self._last_selection_pos is None:
            self.selection_popup.hide()
            return
        global_pt = self.text_overlay.mapToGlobal(self._last_selection_pos.toPoint())
        local_pt = self.mapFromGlobal(global_pt)
        self.selection_popup.show_near(local_pt)

    def search_selection_in_book(self):
        if not self.selected_text:
            return
        query = " ".join(self.selected_text.split())  # collapse newlines/extra whitespace to one line
        if self._search_dialog is None:
            self._search_dialog = TextSearchDialog(self.db, self._handle_search_result, self)
        self._search_dialog.query_edit.setText(query)
        self._search_dialog.start_search()
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()

    def _handle_search_result(self, book_id, page_number):
        if book_id == self.book_id:
            self.jump_to_page(page_number + 1)
            self.raise_()
            self.activateWindow()
        elif self.open_book_at_page:
            # A result in a DIFFERENT book -- this window only ever owns
            # the one book, so hand off to the library window's own
            # open-any-book logic (threaded through at construction time).
            self.open_book_at_page(book_id, page_number)

    def prev_page(self):
        if self.two_page_mode:
            prev_left = self._pair_start(self.current_page) - 2
            if prev_left >= 0:
                self.current_page = prev_left
                self.render_page()
        elif self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if self.two_page_mode:
            next_left = self._pair_start(self.current_page) + 2
            if next_left < self.page_count:
                self.current_page = next_left
                self.render_page()
        elif self.current_page < self.page_count - 1:
            self.current_page += 1
            self.render_page()

    def jump_to_page(self, value):
        page = value - 1
        if not (0 <= page < self.page_count):
            return
        target = self._pair_start(page) if self.two_page_mode else page
        if target != self.current_page:
            self.current_page = target
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
        if self.two_page_mode:
            left_idx = self._pair_start(self.current_page)
            right_idx = left_idx + 1
            left_page = self.doc[left_idx]
            right_page = self.doc[right_idx] if right_idx < self.page_count else None
            self.zoom = self._compute_fit_zoom_two_page(left_page, right_page)
        else:
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

    def toggle_two_page_mode(self, checked):
        self.two_page_btn.setChecked(checked)
        self.two_page_mode = checked
        self.db.set_setting("reader_two_page", "1" if checked else "0")
        if checked:
            # Snap to a pairing boundary so the spread shows sensible pages
            # immediately, rather than the single page you happened to be on.
            self.current_page = self._pair_start(self.current_page)
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

    def refresh_highlights(self):
        self.highlight_list.clear()
        for h in self.db.get_highlights(self.book_id):
            text = h["label"] or f"Page {h['page_number'] + 1}"
            snippet = (h["text"] or "").strip().replace("\n", " ")
            if snippet:
                text += f" \u2014 {snippet[:40]}{'...' if len(snippet) > 40 else ''}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, h["id"])
            item.setData(Qt.UserRole + 1, h["page_number"])
            item.setForeground(QColor(h["color"]))
            self.highlight_list.addItem(item)

    def jump_to_highlight(self, item):
        self.current_page = item.data(Qt.UserRole + 1)
        self.render_page()

    def _show_highlight_list_menu(self, pos):
        item = self.highlight_list.itemAt(pos)
        if item is None:
            return
        highlight_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        jump_action = menu.addAction("Jump to Page")
        edit_action = menu.addAction("Edit Highlight...")
        delete_action = menu.addAction("Delete Highlight")
        chosen = menu.exec(self.highlight_list.mapToGlobal(pos))
        if chosen is jump_action:
            self.jump_to_highlight(item)
        elif chosen is edit_action:
            self.edit_highlight(highlight_id)
        elif chosen is delete_action:
            self.delete_highlight(highlight_id)

    def remove_selected_highlight(self):
        item = self.highlight_list.currentItem()
        if not item:
            return
        self.db.delete_highlight(item.data(Qt.UserRole))
        self.refresh_highlights()
        self._load_saved_highlights_for_current_view()

    def export_highlights_notes(self):
        highlights = self.db.get_highlights(self.book_id)
        if not highlights:
            QMessageBox.information(self, "No highlights", "This book doesn't have any saved highlights yet.")
            return
        book_title = self.book["title"] or "Untitled"
        default_name = f"{book_title} - Highlights.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Highlights", os.path.expanduser(f"~/{default_name}"),
            "Markdown files (*.md);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        content = build_highlights_notes(book_title, highlights)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", f"Couldn't write that file:\n{exc}")
            return
        QMessageBox.information(
            self, "Export complete", f"Exported {len(highlights)} highlight(s) to:\n{path}"
        )

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
