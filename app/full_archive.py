"""Full backup archive: a ZIP containing the actual PDF files plus a
manifest of everything that isn't already encoded in their filenames --
categories, bookmarks, reading status, favorite, annotation, and reading
progress. The natural way to move (or back up) an entire library, not just
its categorization.
"""
import json
import os
import zipfile
from datetime import datetime

import pymupdf as fitz

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
BOOKS_DIR = "books"


def build_manifest(db, book_ids=None):
    """Returns (manifest_dict, {filename: source_filepath})."""
    if book_ids is None:
        book_ids = [b["id"] for b in db.get_books()]

    books_out = {}
    categories_seen = {}
    filepaths = {}
    for book_id in book_ids:
        book = db.get_book(book_id)
        if not book:
            continue
        filename = os.path.basename(book["filepath"])
        cats = db.get_categories_for_book(book_id)
        bookmarks = db.get_bookmarks(book_id)
        books_out[filename] = {
            "categories": [c["name"] for c in cats],
            "bookmarks": [
                {"page_number": bm["page_number"], "label": bm["label"] or ""} for bm in bookmarks
            ],
            "status": book["status"] or "unread",
            "is_favorite": bool(book["is_favorite"]),
            "annotation": book["annotation"] or "",
            "last_page": book["last_page"] or 0,
        }
        for c in cats:
            categories_seen[c["name"]] = bool(c["is_favorite"])
        filepaths[filename] = book["filepath"]

    manifest = {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "books": books_out,
        "categories": {name: {"favorite": fav} for name, fav in categories_seen.items()},
    }
    return manifest, filepaths


def write_archive(zip_path, manifest, filepaths):
    """Writes manifest.json plus every PDF (under books/) into the zip.
    Returns a list of filenames that were skipped because their source file
    no longer existed on disk at export time."""
    skipped = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        for filename, source_path in filepaths.items():
            if not os.path.exists(source_path):
                skipped.append(filename)
                continue
            zf.write(source_path, arcname=f"{BOOKS_DIR}/{filename}")
    return skipped


def read_manifest(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        return json.loads(zf.read(MANIFEST_NAME))


def _unique_dest_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({counter}){ext}")
        counter += 1
    return candidate


def apply_archive(db, zip_path, destination_dir):
    """Extracts any PDF not already in the library (matched by filename)
    into destination_dir and adds it, then applies categories, bookmarks,
    status, favorite, and annotation to every matched book -- whether newly
    added or already present. Returns a summary dict."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME))
        books = manifest.get("books", {})
        categories = manifest.get("categories", {})

        name_to_cat_id = {}
        categories_created = 0
        for name, meta in categories.items():
            existing = db.get_category_by_name(name)
            cat = db.create_category(name)
            if cat is None:
                continue
            if existing is None:
                categories_created += 1
            if meta.get("favorite") and not cat["is_favorite"]:
                db.toggle_category_favorite(cat["id"])
            name_to_cat_id[name] = cat["id"]

        matched, added, skipped, bookmarks_added = 0, 0, 0, 0
        for filename, meta in books.items():
            book = db.get_book_by_filename(filename)
            if book is None:
                archive_entry = f"{BOOKS_DIR}/{filename}"
                if archive_entry not in zf.namelist():
                    skipped += 1
                    continue
                target_path = _unique_dest_path(destination_dir, filename)
                with zf.open(archive_entry) as src, open(target_path, "wb") as dst:
                    dst.write(src.read())
                page_count = 0
                try:
                    doc = fitz.open(target_path)
                    page_count = doc.page_count
                    doc.close()
                except Exception:
                    pass
                title = os.path.splitext(filename)[0].split(" - ")[0].strip() or "Untitled"
                book = db.add_book(target_path, title, page_count)
                added += 1

            matched += 1

            for cat_name in meta.get("categories", []):
                cat_id = name_to_cat_id.get(cat_name)
                if cat_id is None:
                    cat = db.create_category(cat_name)
                    if cat is None:
                        continue
                    cat_id = cat["id"]
                    name_to_cat_id[cat_name] = cat_id
                db.add_books_to_category(cat_id, [book["id"]])

            existing_bookmarks = {
                (bm["page_number"], bm["label"] or "") for bm in db.get_bookmarks(book["id"])
            }
            for bm in meta.get("bookmarks", []):
                key = (bm["page_number"], bm.get("label") or "")
                if key in existing_bookmarks:
                    continue
                db.add_bookmark(book["id"], bm["page_number"], bm.get("label") or "")
                bookmarks_added += 1

            if meta.get("status"):
                db.set_status(book["id"], meta["status"])
            if meta.get("is_favorite") and not book["is_favorite"]:
                db.toggle_favorite(book["id"])
            if meta.get("annotation"):
                db.update_metadata(book["id"], annotation=meta["annotation"])
            if meta.get("last_page"):
                db.update_progress(book["id"], meta["last_page"])

    return {
        "matched": matched, "added": added, "skipped": skipped,
        "categories_created": categories_created, "bookmarks_added": bookmarks_added,
    }
