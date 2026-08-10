"""A QComboBox that lets you check multiple items instead of picking just
one -- the popup stays open across clicks so you can check several items in
one go, and the closed box shows a comma-joined summary of what's checked.
Used for Language, since a book can have more than one.
"""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox


class MultiSelectComboBox(QComboBox):
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("(none selected)")
        # An editable combo's line-edit area only opens the popup via the
        # dropdown arrow by default -- clicking the text/box itself just
        # tries to place a text cursor. Since the line edit is read-only
        # anyway (it's just a display summary, not something to type in),
        # intercept clicks on it and open the popup instead.
        self.lineEdit().installEventFilter(self)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.view().pressed.connect(self._on_item_pressed)
        # Qt's own item delegate independently toggles the checkbox when a
        # click lands precisely on its glyph, through an internal mechanism
        # that never emits the 'pressed' signal above at all -- watching the
        # model directly is the only reliable way to catch every toggle,
        # regardless of which of the two mechanisms actually caused it.
        self._model.dataChanged.connect(self._on_data_changed)
        self._skip_next_hide = False
        self._suppress_signal = False  # True while WE'RE bulk-syncing state

    def eventFilter(self, obj, event):
        if obj is self.lineEdit():
            if event.type() == QEvent.MouseButtonPress:
                # Swallow the press -- opening the popup here would tie it to
                # Qt's classic press-hold-drag-release combo-box gesture, so
                # it would only stay open for as long as the button stays
                # held down. Wait for release instead, once the button truly
                # isn't held anymore, so it opens as an independent popup.
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self.showPopup()
                return True
        return super().eventFilter(obj, event)

    def add_items(self, items):
        for text in items:
            if self.find_item(text) is not None:
                continue  # avoid duplicate entries
            item = QStandardItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            self._model.appendRow(item)

    def find_item(self, text):
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item.text() == text:
                return item
        return None

    def _on_item_pressed(self, index):
        """Fires for a click landing anywhere in a row EXCEPT precisely on
        the checkbox glyph -- a glyph click is handled entirely by Qt's own
        delegate instead (see _on_data_changed), and never reaches this
        signal at all, so there's no risk of canceling that out by also
        toggling here."""
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        self._skip_next_hide = True  # keep the popup open for more picks
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _on_data_changed(self, top_left, bottom_right, roles):
        """The single source of truth for reacting to a checkbox actually
        toggling -- catches both our own manual toggle above (a click
        anywhere in a row except the glyph) and Qt's own internal toggle (a
        click landing precisely on the glyph), which never fires 'pressed'."""
        if self._suppress_signal:
            return
        self._skip_next_hide = True  # also keep the popup open for a glyph click
        self._update_display_text()
        self.selection_changed.emit()

    def hidePopup(self):
        if self._skip_next_hide:
            self._skip_next_hide = False
            return
        super().hidePopup()

    def checked_items(self):
        return [
            self._model.item(row).text()
            for row in range(self._model.rowCount())
            if self._model.item(row).checkState() == Qt.Checked
        ]

    def set_checked_items(self, values):
        values_set = set(values)
        self._suppress_signal = True
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            item.setCheckState(Qt.Checked if item.text() in values_set else Qt.Unchecked)
        self._suppress_signal = False
        self._update_display_text()

    def clear_selection(self):
        self._suppress_signal = True
        for row in range(self._model.rowCount()):
            self._model.item(row).setCheckState(Qt.Unchecked)
        self._suppress_signal = False
        self._update_display_text()

    def clear_items(self):
        self._model.clear()
        self._update_display_text()

    def _update_display_text(self):
        self.lineEdit().setText(", ".join(self.checked_items()))
