"""A QComboBox that lets you check multiple items instead of picking just
one -- the popup stays open across clicks so you can check several items in
one go, and the closed box shows a comma-joined summary of what's checked.
Used for Language, since a book can have more than one.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox


class MultiSelectComboBox(QComboBox):
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("(none selected)")
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.view().pressed.connect(self._on_item_pressed)
        self._skip_next_hide = False

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
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self._skip_next_hide = True  # keep the popup open for more picks -- set this
        self._update_display_text()  # BEFORE emitting, in case a listener reacts
        self.selection_changed.emit()  # reentrantly (e.g. rebuilds this combo's own model)

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
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            item.setCheckState(Qt.Checked if item.text() in values_set else Qt.Unchecked)
        self._update_display_text()

    def clear_selection(self):
        for row in range(self._model.rowCount()):
            self._model.item(row).setCheckState(Qt.Unchecked)
        self._update_display_text()

    def clear_items(self):
        self._model.clear()
        self._update_display_text()

    def _update_display_text(self):
        self.lineEdit().setText(", ".join(self.checked_items()))
