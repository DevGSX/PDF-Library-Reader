"""Export/import book bookmarks as a portable JSON file, matched by
filename rather than full path -- the same portability approach used for
categories (see category_export.py).
"""
import json
import os
from datetime import datetime

FORMAT_VERSION = 1


def build_export_data(db, book_ids=None):
    """Build the exportable dict. If book_ids is given, only include those
    books' bookmarks; otherwise include every book that has at least one."""
    if book_ids is None:
        book_ids = [b["id"] for b in db.get_books()]

    books_out = {}
    for book_id in book_ids:
        book = db.get_book(book_id)
        if not book:
            continue
        bookmarks = db.get_bookmarks(book_id)
        if not bookmarks:
            continue
        filename = os.path.basename(book["filepath"])
        books_out[filename] = [
            {"page_number": bm["page_number"], "label": bm["label"] or ""} for bm in bookmarks
        ]

    return {
        "kind": "bookmarks",
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "books": books_out,
    }


def write_export_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_export_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_import_data(db, data):
    """Add each matched book's bookmarks (found by filename). An entry with
    the same page number and label as one already present is skipped, so
    re-importing the same file is always safe and never creates duplicates.
    Returns a summary dict: matched, skipped, bookmarks_added."""
    books = data.get("books", {})
    matched, skipped, bookmarks_added = 0, 0, 0
    for filename, bookmarks in books.items():
        book = db.get_book_by_filename(filename)
        if book is None:
            skipped += 1
            continue
        matched += 1
        existing = {(bm["page_number"], bm["label"] or "") for bm in db.get_bookmarks(book["id"])}
        for bm in bookmarks:
            key = (bm["page_number"], bm.get("label") or "")
            if key in existing:
                continue
            db.add_bookmark(book["id"], bm["page_number"], bm.get("label") or "")
            bookmarks_added += 1

    return {"matched": matched, "skipped": skipped, "bookmarks_added": bookmarks_added}
