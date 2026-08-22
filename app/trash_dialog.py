"""The Trash dialog -- lists every book currently in Trash (moved there by
"Delete from Disk" instead of removed outright), and lets the user restore
one or more of them exactly as they were (file, bookmarks, highlights, and
category memberships all included), or permanently delete them for good.
"""
import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class TrashDialog(QDialog):
    def __init__(self, library_window, parent=None):
        super().__init__(parent)
        self.library_window = library_window
        self.db = library_window.db
        self.setWindowTitle("Trash")
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Books deleted from your library stay here for 30 days before being "
            "permanently removed, unless you restore or delete them yourself first."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        restore_btn = QPushButton("Restore Selected")
        restore_btn.clicked.connect(self._restore_selected)
        btn_row.addWidget(restore_btn)
        delete_btn = QPushButton("Delete Permanently")
        delete_btn.clicked.connect(self._delete_selected_permanently)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        empty_btn = QPushButton("Empty Trash")
        empty_btn.clicked.connect(self._empty_trash)
        btn_row.addWidget(empty_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for entry in self.db.get_trash_entries():
            deleted_date = (entry["deleted_date"] or "")[:10]
            item = QListWidgetItem(f"{entry['title']}  \u2014  deleted {deleted_date}")
            item.setData(Qt.UserRole, entry["id"])
            self.list_widget.addItem(item)

    def _selected_ids(self):
        return [item.data(Qt.UserRole) for item in self.list_widget.selectedItems()]

    def _restore_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        restored, failed = 0, []
        for trash_id in ids:
            entry = self.db.get_trash_entry(trash_id)
            if entry is None:
                continue
            original_path = entry["original_filepath"]
            trash_path = entry["trash_filepath"]
            restored_path = original_path
            if trash_path:
                try:
                    if os.path.exists(trash_path):
                        restored_path = self.library_window._unique_destination(original_path)
                        shutil.move(trash_path, restored_path)
                    # else: the trashed file itself has since vanished -- still
                    # worth restoring the metadata, it'll just show up as missing
                except OSError as exc:
                    failed.append((entry["title"], str(exc)))
                    continue
            self.db.restore_book_from_trash(trash_id, restored_path)
            restored += 1

        self._refresh_list()
        self.library_window.refresh_list()
        self.library_window.refresh_categories_sidebar()
        self.library_window._update_trash_button()
        if failed:
            details = "\n".join(f"\u2022 {title}: {err}" for title, err in failed)
            QMessageBox.warning(
                self, "Some books couldn't be restored",
                f"Restored {restored} of {len(ids)} book(s). The rest couldn't be "
                f"moved back:\n\n{details}",
            )

    def _delete_selected_permanently(self):
        ids = self._selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(
            self, "Delete permanently",
            f"Permanently delete {len(ids)} book(s) from Trash, including their "
            f"files? This cannot be undone.",
        )
        if reply != QMessageBox.Yes:
            return
        self._purge(ids)

    def _empty_trash(self):
        entries = self.db.get_trash_entries()
        if not entries:
            return
        reply = QMessageBox.question(
            self, "Empty Trash",
            f"Permanently delete all {len(entries)} book(s) in Trash, including "
            f"their files? This cannot be undone.",
        )
        if reply != QMessageBox.Yes:
            return
        self._purge([e["id"] for e in entries])

    def _purge(self, trash_ids):
        for trash_id in trash_ids:
            entry = self.db.get_trash_entry(trash_id)
            if entry is None:
                continue
            if entry["trash_filepath"] and os.path.exists(entry["trash_filepath"]):
                try:
                    os.remove(entry["trash_filepath"])
                except OSError:
                    pass  # already gone, or truly can't be removed -- either way, drop the record
            self.db.delete_trash_entry(trash_id)
        self._refresh_list()
        self.library_window._update_trash_button()
