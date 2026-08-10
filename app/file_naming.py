"""Keeps each book's filename in sync with its Title/Author/Series/Genre/
Language metadata, so the information travels with the file itself (e.g.
when copying the whole library folder to another device) instead of only
living in the database.

Genre and Language can each hold more than one value, separated by '_'
(e.g. "English_Bulgarian", "Science Fiction_Fantasy") -- both '-' (the
field separator below) and '_' are perfectly ordinary characters on every
filesystem, so neither needs any special handling to show up correctly in
an actual filename.
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


def build_filename(title, author, series, genre, language, ext):
    """'Title - Author - Series - Genre - Language.pdf' -- empty parts are
    dropped, e.g. a book with nothing but a title just becomes 'Title.pdf'.
    A book with more than one genre or language renders as such directly,
    e.g. "English_Bulgarian" or "Science Fiction_Fantasy"."""
    parts = [
        p for p in (
            _sanitize(title), _sanitize(author), _sanitize(series),
            _sanitize(genre), _sanitize(language),
        ) if p
    ]
    name = " - ".join(parts) if parts else "Untitled"
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH].rstrip()
    return f"{name}{ext}"


def parse_filename(filename):
    """Inverse of build_filename(): given a filename (with or without its
    extension) split on ' - ' into title/author/series/genre/language. Title
    always ends up populated (falling back to the whole filename, or
    'Untitled' if even that is empty); the rest default to '' when not
    present. Extra segments beyond five are ignored.

    This only round-trips exactly for filenames this app generated -- if a
    field was left blank when the file was named, later fields shift up by
    one slot, since a plain 'A - B - C' has no way to record *which* field
    was skipped. Title itself is never ambiguous: it's always the first
    segment when present, since the app never lets Title be saved blank.
    """
    name = os.path.splitext(filename)[0]
    parts = [p.strip() for p in name.split(" - ")]
    parts = [p for p in parts if p]
    if not parts:
        return {"title": "Untitled", "author": "", "series": "", "genre": "", "language": ""}
    keys = ["title", "author", "series", "genre", "language"]
    result = {k: "" for k in keys}
    for key, value in zip(keys, parts):
        result[key] = value
    return result


def _unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({counter}){ext}")
        counter += 1
    return candidate


def sync_filename(db, book_id):
    """Rename the book's file on disk to match its current metadata, if it
    doesn't already match. Returns (renamed: bool, info: str | None) -- info
    is the new path on success, or an error message on failure."""
    book = db.get_book(book_id)
    if not book:
        return False, None

    old_path = book["filepath"]
    if not os.path.exists(old_path):
        return False, "The file could not be found on disk."

    directory = os.path.dirname(old_path)
    ext = os.path.splitext(old_path)[1]
    desired_name = build_filename(
        book["title"], book["author"], book["series"], book["genre"], book["language"], ext
    )
    desired_path = os.path.join(directory, desired_name)

    if os.path.abspath(desired_path) == os.path.abspath(old_path):
        return False, None  # already matches -- nothing to do

    target_path = _unique_path(directory, desired_name)
    try:
        os.rename(old_path, target_path)
    except OSError as exc:
        return False, str(exc)

    try:
        db.update_filepath(book_id, target_path)
    except Exception as exc:
        # The file moved but the database write failed -- try to undo the
        # rename so the file and the database don't end up out of sync.
        try:
            os.rename(target_path, old_path)
        except OSError:
            pass  # best effort; if this also fails, the DB still points at old_path
        return False, f"Renamed the file but couldn't update the library database: {exc}"

    return True, target_path
