"""Keeps each book's filename in sync with its Title/Author/Series metadata,
so the information travels with the file itself (e.g. when copying the whole
library folder to another device) instead of only living in the database.
"""
import os
import re

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_NAME_LENGTH = 180  # keep well under typical filesystem filename limits


def _sanitize(text):
    text = (text or "").strip()
    text = _ILLEGAL_CHARS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_filename(title, author, series, ext):
    """'Title * Author * Series.pdf' -- empty parts are dropped, e.g. a book
    with no author/series just becomes 'Title.pdf'."""
    parts = [p for p in (_sanitize(title), _sanitize(author), _sanitize(series)) if p]
    name = " * ".join(parts) if parts else "Untitled"
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH].rstrip()
    return f"{name}{ext}"


def _unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({counter}){ext}")
        counter += 1
    return candidate


def sync_filename(db, book_id):
    """Rename the book's file on disk to match its current Title/Author/Series,
    if it doesn't already match. Returns (renamed: bool, info: str | None) --
    info is the new path on success, or an error message on failure."""
    book = db.get_book(book_id)
    if not book:
        return False, None

    old_path = book["filepath"]
    if not os.path.exists(old_path):
        return False, "The file could not be found on disk."

    directory = os.path.dirname(old_path)
    ext = os.path.splitext(old_path)[1]
    desired_name = build_filename(book["title"], book["author"], book["series"], ext)
    desired_path = os.path.join(directory, desired_name)

    if os.path.abspath(desired_path) == os.path.abspath(old_path):
        return False, None  # already matches -- nothing to do

    target_path = _unique_path(directory, desired_name)
    try:
        os.rename(old_path, target_path)
    except OSError as exc:
        return False, str(exc)

    db.update_filepath(book_id, target_path)
    return True, target_path
