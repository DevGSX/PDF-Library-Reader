"""Duplicate-book detection: an identical file (by content hash) is the
strongest signal; a matching Title+Author is a weaker, free-to-check
fallback that also catches the same book re-imported under a different
filename, or from a different source, before it's ever been hashed.

Kept Qt-free and pure-function, same as text_selection.py / highlights_
notes.py -- the grouping logic here can be unit-tested directly against
plain dicts, without a running GUI. The actual hashing touches the
filesystem, so it's a separate function the caller (library_window.py)
drives itself -- at import time for a single new file, or in a bulk scan
with its own progress/cancel handling for the rest of the library.
"""
import hashlib

HASH_CHUNK_SIZE = 1024 * 1024  # 1 MB per read -- keeps memory flat on huge PDFs


def compute_file_hash(filepath):
    """SHA-256 of a file's exact contents, or None if it can't be read
    (missing, permissions, etc.) -- callers should treat None as "unknown",
    not as a value that matches other unknowns."""
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _metadata_key(book):
    title = (book.get("title") or "").strip().lower()
    author = (book.get("author") or "").strip().lower()
    return (title, author)


def find_duplicate_groups(books):
    """Group `books` (dicts with at least 'id', 'title', 'author', and
    'file_hash') into likely-duplicate clusters.

    Returns a list of {"match_type": "hash" | "metadata", "book_ids": [...]}
    -- "hash" groups (byte-identical files) are reported first, since
    that's the strongest possible signal. A book already placed in a
    "hash" group is never *also* reported in a weaker "metadata" group, so
    the same pair of books never shows up twice for two different reasons.

    A blank file_hash (not yet computed -- see compute_file_hash) never
    matches anything, including another blank one; only a genuine,
    non-empty hash collision counts. Likewise, a book with no title at all
    is skipped for metadata matching -- two blank titles matching each
    other isn't a meaningful signal.
    """
    groups = []
    claimed = set()

    by_hash = {}
    for b in books:
        file_hash = b.get("file_hash")
        if file_hash:
            by_hash.setdefault(file_hash, []).append(b["id"])
    for book_ids in by_hash.values():
        if len(book_ids) > 1:
            groups.append({"match_type": "hash", "book_ids": sorted(book_ids)})
            claimed.update(book_ids)

    by_meta = {}
    for b in books:
        if b["id"] in claimed:
            continue
        key = _metadata_key(b)
        if not key[0]:
            continue  # no title -- not a meaningful match signal
        by_meta.setdefault(key, []).append(b["id"])
    for book_ids in by_meta.values():
        if len(book_ids) > 1:
            groups.append({"match_type": "metadata", "book_ids": sorted(book_ids)})

    return groups
