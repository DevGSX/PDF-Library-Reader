"""Background worker that scans every book in the library for matching text.

Runs on a QThread so the UI stays responsive while potentially many PDFs
are opened and scanned page by page.
"""
import os

import pymupdf as fitz
from PySide6.QtCore import QThread, Signal

MAX_RESULTS = 500
SNIPPET_PADDING = 40


class TextSearchWorker(QThread):
    result_found = Signal(dict)          # {book_id, book_title, page_number, snippet}
    progress = Signal(int, int, str)      # current, total, current_book_title
    finished_search = Signal(int)         # total results found

    def __init__(self, books, query, parent=None):
        super().__init__(parent)
        self.books = books
        self.query = query
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        query_lower = self.query.lower()
        total_results = 0
        total = len(self.books)

        for i, book in enumerate(self.books):
            if self._cancelled:
                break
            self.progress.emit(i + 1, total, book["title"])

            filepath = book["filepath"]
            if not os.path.exists(filepath):
                continue
            try:
                doc = fitz.open(filepath)
            except Exception:
                continue

            for page_num in range(doc.page_count):
                if self._cancelled or total_results >= MAX_RESULTS:
                    break
                text = doc[page_num].get_text("text")
                text_lower = text.lower()
                idx = text_lower.find(query_lower)
                if idx == -1:
                    continue
                start = max(0, idx - SNIPPET_PADDING)
                end = min(len(text), idx + len(self.query) + SNIPPET_PADDING)
                snippet = text[start:end].replace("\n", " ").strip()
                if start > 0:
                    snippet = "\u2026" + snippet
                if end < len(text):
                    snippet = snippet + "\u2026"
                self.result_found.emit(
                    {
                        "book_id": book["id"],
                        "book_title": book["title"],
                        "page_number": page_num,
                        "snippet": snippet,
                    }
                )
                total_results += 1

            doc.close()
            if total_results >= MAX_RESULTS:
                break

        self.finished_search.emit(total_results)
