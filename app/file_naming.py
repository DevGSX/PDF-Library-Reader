"""Keeps each book's filename in sync with its Title/Author/Series/Genre/
Language metadata, so the information travels with the file itself (e.g.
when copying the whole library folder to another device) instead of only
living in the database.

Genre and Language can each hold more than one value, separated by '_'
(e.g. "English_Bulgarian", "Science Fiction_Fantasy") -- both '-' (the
field separator below) and '_' are perfectly ordinary characters on every
filesystem, so neither needs any special handling to show up correctly in
an actual filename.

A book's position within its Series (its "Book #" -- 1, 2, 2.5 for a
novella between two entries, etc.) rides along inside the Series slot
itself, as "Drawing#1", "Drawing#2" -- rather than adding a sixth
position to what's otherwise a fixed five-field naming scheme. See
combine_series_and_number() / split_series_and_number() below.
"""
import os
import re

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SERIES_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
MAX_NAME_LENGTH = 180  # keep well under typical filesystem filename limits


def _sanitize(text):
    text = (text or "").strip()
    text = _ILLEGAL_CHARS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_series_number(value):
    """None/blank -> ''. A whole number displays without a trailing ".0"
    (2, not 2.0); a genuine fraction (e.g. 2.5, for a novella between two
    entries) keeps its decimal. Shared by the filename encoding below and
    by the UI (Book Details' field, the bulk Set Series dialog, and the
    list/grid display), so all three agree on exactly the same text for
    the same number."""
    if value is None or value == "":
        return ""
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def combine_series_and_number(series, series_number):
    """'Drawing' + 1 -> 'Drawing#1' -- this exact string is what lands in
    the filename's Series slot (see build_filename). No number set, or no
    series at all, just returns `series` unchanged."""
    series = series or ""
    number_text = format_series_number(series_number)
    return f"{series}#{number_text}" if series and number_text else series


def split_series_and_number(series_field):
    """Inverse of combine_series_and_number(): 'Drawing#1' -> ('Drawing', 1.0);
    plain 'Drawing' -> ('Drawing', None). If the text after the last '#'
    isn't a plain number, the whole string is treated as the series name
    with no number, so a series that happens to contain a '#' for some
    other reason isn't silently mangled."""
    series_field = series_field or ""
    if "#" in series_field:
        name, _, number_text = series_field.rpartition("#")
        if name and _SERIES_NUMBER_RE.match(number_text):
            return name, float(number_text)
    return series_field, None


def build_filename(title, author, series, genre, language, ext, series_number=None):
    """'Title - Author - Series - Genre - Language.pdf'. Each field keeps
    its own fixed position -- a field left blank shows up as an empty gap
    between two dashes (e.g. "Title -  - Series -  - English.pdf") rather
    than being skipped, so parse_filename() can always tell which field is
    which no matter which ones are filled in. Trailing blank fields are
    trimmed instead of leaving dangling dashes, so a book with nothing but
    a title still just becomes 'Title.pdf'. A book with more than one
    genre or language renders as such directly, e.g. "English_Bulgarian"
    or "Science Fiction_Fantasy". A series_number (Book #), if given,
    rides inside the Series slot itself as "Series#N" -- see
    combine_series_and_number()."""
    series_field = combine_series_and_number(_sanitize(series), series_number)
    fields = [
        _sanitize(title), _sanitize(author), series_field,
        _sanitize(genre), _sanitize(language),
    ]
    while len(fields) > 1 and not fields[-1]:
        fields.pop()
    name = " - ".join(fields) if any(fields) else "Untitled"
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH].rstrip()
    return f"{name}{ext}"


def parse_filename(filename):
    """Inverse of build_filename(): given a filename (with or without its
    extension) split on ' - ' into title/author/series/genre/language, by
    fixed position -- an empty segment between two dashes (e.g.
    "A -  - C") means that field was blank, not skipped, so later fields
    never shift out of their slot. Title always ends up populated (falling
    back to the whole filename, or 'Untitled' if even that is empty); the
    rest default to '' when not present. Extra segments beyond five are
    ignored. The Series slot is further split into a plain 'series' name
    and a separate 'series_number' (float, or None if not present) -- see
    split_series_and_number().

    This only round-trips exactly for filenames this app generated. A
    filename dropped in from outside that happens to contain ' - ' will
    still be split positionally the same way -- there's no way to tell
    those apart from a genuine blank gap.
    """
    name = os.path.splitext(filename)[0].strip()
    if not name:
        return {
            "title": "Untitled", "author": "", "series": "",
            "series_number": None, "genre": "", "language": "",
        }
    parts = [p.strip() for p in name.split(" - ")]
    keys = ["title", "author", "series", "genre", "language"]
    result = {k: "" for k in keys}
    for key, value in zip(keys, parts):
        result[key] = value
    if not result["title"]:
        result["title"] = name
    result["series"], result["series_number"] = split_series_and_number(result["series"])
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
        book["title"], book["author"], book["series"], book["genre"], book["language"], ext,
        series_number=book["series_number"],
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
