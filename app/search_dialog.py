"""Dialog for searching text content across every book in the library."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .search_worker import TextSearchWorker


class TextSearchDialog(QDialog):
    def __init__(self, db, on_open_result, parent=None):
        super().__init__(parent)
        self.db = db
        self.on_open_result = on_open_result  # callback(book_id, page_number)
        self.worker = None

        self.setWindowTitle("Search Text in Library")
        self.resize(560, 480)

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Search for text across all your books...")
        self.query_edit.returnPressed.connect(self.start_search)
        search_row.addWidget(self.query_edit, stretch=1)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.start_search)
        search_row.addWidget(self.search_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_search)
        self.cancel_btn.hide()
        search_row.addWidget(self.cancel_btn)

        layout.addLayout(search_row)

        self.status_label = QLabel("Enter a search term to look across every book in your library.")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        self.results_list.setWordWrap(True)
        self.results_list.itemDoubleClicked.connect(self.open_selected)
        layout.addWidget(self.results_list)

        hint = QLabel("Double-click a result to jump straight to that page.")
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

    def start_search(self):
        query = self.query_edit.text().strip()
        if not query:
            return
        if self.worker is not None and self.worker.isRunning():
            return

        self.results_list.clear()
        books = self.db.get_books()  # search the whole library, ignoring any current filter
        if not books:
            self.status_label.setText("Your library is empty \u2014 add some books first.")
            return

        self.search_btn.setEnabled(False)
        self.cancel_btn.show()
        self.status_label.setText(f"Searching 0 of {len(books)} books...")

        self.worker = TextSearchWorker(books, query)
        self.worker.result_found.connect(self.add_result)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_search.connect(self.search_finished)
        self.worker.start()

    def cancel_search(self):
        if self.worker is not None:
            self.worker.cancel()

    def update_progress(self, current, total, book_title):
        self.status_label.setText(f"Searching {current} of {total}: {book_title}")

    def add_result(self, result):
        item = QListWidgetItem(
            f"{result['book_title']} \u2014 page {result['page_number'] + 1}\n{result['snippet']}"
        )
        item.setData(Qt.UserRole, result["book_id"])
        item.setData(Qt.UserRole + 1, result["page_number"])
        self.results_list.addItem(item)

    def search_finished(self, total_results):
        self.search_btn.setEnabled(True)
        self.cancel_btn.hide()
        if total_results == 0:
            self.status_label.setText("No matches found.")
        else:
            self.status_label.setText(f"{total_results} match(es) found.")

    def open_selected(self, item):
        book_id = item.data(Qt.UserRole)
        page_number = item.data(Qt.UserRole + 1)
        self.on_open_result(book_id, page_number)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)
