"""Export/import book category memberships (and per-category favorite
status) as a portable JSON file, matched by filename rather than full path
-- lets you carry your categories along when moving books to another
device, or back them up independently of the library database itself.

Deliberately explicit (Export.../Import... actions) rather than an
auto-written sidecar file: if two devices both silently wrote a manifest
into a shared/synced folder, one could clobber the other's categories
without warning. An explicit export/import step means it only ever happens
when you actually choose to do it.
"""
import json
import os
from datetime import datetime

FORMAT_VERSION = 1


def build_export_data(db, book_ids=None):
    """Build the exportable dict. If book_ids is given, only include those
    books' category memberships; otherwise include every book that belongs
    to at least one category."""
    if book_ids is None:
        book_ids = [b["id"] for b in db.get_books()]

    books_out = {}
    categories_seen = {}  # name -> is_favorite
    for book_id in book_ids:
        book = db.get_book(book_id)
        if not book:
            continue
        cats = db.get_categories_for_book(book_id)
        if not cats:
            continue
        filename = os.path.basename(book["filepath"])
        books_out[filename] = {"categories": [c["name"] for c in cats]}
        for c in cats:
            categories_seen[c["name"]] = bool(c["is_favorite"])

    return {
        "kind": "categories",
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "books": books_out,
        "categories": {name: {"favorite": fav} for name, fav in categories_seen.items()},
    }


def write_export_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_export_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_import_data(db, data):
    """Apply an imported dict to the database: create any categories that
    don't already exist (with their favorite status), and add each matched
    book (found by filename) to its listed categories. Books not found in
    the current library are skipped, not errors -- e.g. importing a
    manifest that covers more books than are present on this device.
    Returns a summary dict: matched, skipped, categories_created."""
    categories = data.get("categories", {})
    books = data.get("books", {})

    name_to_id = {}
    created = 0
    for name, meta in categories.items():
        existing = db.get_category_by_name(name)
        cat = db.create_category(name)  # a no-op (returns the existing row) if it's already there
        if cat is None:
            continue
        if existing is None:
            created += 1
        if meta.get("favorite") and not cat["is_favorite"]:
            db.toggle_category_favorite(cat["id"])
        name_to_id[name] = cat["id"]

    matched, skipped = 0, 0
    for filename, meta in books.items():
        book = db.get_book_by_filename(filename)
        if book is None:
            skipped += 1
            continue
        matched += 1
        for cat_name in meta.get("categories", []):
            cat_id = name_to_id.get(cat_name)
            if cat_id is None:
                cat = db.create_category(cat_name)
                if cat is None:
                    continue
                cat_id = cat["id"]
                name_to_id[cat_name] = cat_id
            db.add_books_to_category(cat_id, [book["id"]])

    return {"matched": matched, "skipped": skipped, "categories_created": created}
