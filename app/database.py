"""SQLite-backed storage for the PDF library: books, bookmarks and app settings."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime


def _split_multi_value(raw_value):
    """Split a '_'-joined multi-value field ('Science Fiction_Fantasy',
    'English_Bulgarian') into its individual, whitespace-trimmed tokens."""
    return {t.strip() for t in (raw_value or "").split("_") if t.strip()}


def get_data_dir() -> Path:
    """Where the library database lives (created on first run)."""
    data_dir = Path.home() / ".local" / "share" / "pdf-library-reader"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class Database:
    def __init__(self, db_path=None):
        self.db_path = str(db_path) if db_path else str(get_data_dir() / "library.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                added_date TEXT NOT NULL,
                last_opened TEXT,
                last_page INTEGER DEFAULT 0,
                page_count INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                label TEXT,
                created_date TEXT NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                label TEXT,
                color TEXT NOT NULL,
                text TEXT,
                rects TEXT NOT NULL,
                style TEXT DEFAULT 'fill',
                created_date TEXT NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL COLLATE NOCASE,
                is_favorite INTEGER DEFAULT 0,
                created_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS book_categories (
                book_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                PRIMARY KEY (book_id, category_id),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
            );
            """
        )
        self.conn.commit()
        self._migrate_books_table()
        self._migrate_highlights_table()

    def _migrate_books_table(self):
        """Add columns introduced after the initial release, for people upgrading
        from an older copy of the app whose database predates them."""
        cur = self.conn.execute("PRAGMA table_info(books)")
        existing_cols = {row[1] for row in cur.fetchall()}
        new_columns = {
            "author": "TEXT DEFAULT ''",
            "series": "TEXT DEFAULT ''",
            "annotation": "TEXT DEFAULT ''",
            "language": "TEXT DEFAULT ''",
            "genre": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'unread'",  # 'unread' | 'to_read' | 'reading' | 'finished'
        }
        for col, decl in new_columns.items():
            if col not in existing_cols:
                self.conn.execute(f"ALTER TABLE books ADD COLUMN {col} {decl}")
        self.conn.commit()

    def _migrate_highlights_table(self):
        """Same idea as _migrate_books_table, for highlights created
        before the "style" column (fill / underline / strikethrough)
        existed -- every highlight from before that point is treated as
        a plain fill, which is exactly what it visually was."""
        cur = self.conn.execute("PRAGMA table_info(highlights)")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "style" not in existing_cols:
            self.conn.execute("ALTER TABLE highlights ADD COLUMN style TEXT DEFAULT 'fill'")
        self.conn.commit()

    # ---------------- Books ----------------
    def add_book(self, filepath, title, page_count):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO books (filepath, title, added_date, page_count) "
            "VALUES (?, ?, ?, ?)",
            (filepath, title, now, page_count),
        )
        self.conn.commit()
        return self.get_book_by_path(filepath)

    def get_book_by_path(self, filepath):
        cur = self.conn.execute("SELECT * FROM books WHERE filepath = ?", (filepath,))
        return cur.fetchone()

    def get_book_by_filename(self, filename):
        """Find a book by its file's basename rather than full path -- used
        to match an imported category manifest against the current library,
        since absolute paths won't line up across devices."""
        cur = self.conn.execute("SELECT * FROM books")
        for row in cur.fetchall():
            if os.path.basename(row["filepath"]) == filename:
                return dict(row)
        return None

    def get_book(self, book_id):
        cur = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        return cur.fetchone()

    def get_books(self, favorites_only=False, search=None, sort_by="title", descending=False,
                  status=None, category_id=None, genres=None, languages=None):
        """Return library entries as plain dicts, each carrying a live file_size.
        `status`, if given, restricts to one of 'unread' | 'to_read' | 'reading' | 'finished'.
        `category_id`, if given, restricts to books belonging to that category.
        `genres`, if given, restricts to books whose (possibly multi-value,
        "Science Fiction_Fantasy"-style) genre field CONTAINS any of the
        listed values, matched as a whole token -- not a raw substring, so
        filtering by "Fiction" won't also match "Science Fiction". `languages`
        works the same way for the (also possibly multi-value,
        "English_Bulgarian"-style) language field -- either way, a
        multi-value book matches if it has ANY of the values you're
        filtering by, not all of them."""
        query = "SELECT books.* FROM books"
        clauses, params = [], []
        if category_id is not None:
            query += " JOIN book_categories ON book_categories.book_id = books.id"
            clauses.append("book_categories.category_id = ?")
            params.append(category_id)
        if favorites_only:
            clauses.append("is_favorite = 1")
        if status:
            clauses.append("status = ?")
            params.append(status)
        if search:
            clauses.append("(title LIKE ? OR author LIKE ? OR series LIKE ? OR genre LIKE ? OR language LIKE ?)")
            params.extend([f"%{search}%"] * 5)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        cur = self.conn.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]

        # Genre/Language filtering happens here in Python, not as a SQL LIKE
        # clause -- a naive '%value%' substring check would incorrectly match
        # "Fiction" against "Science Fiction". Splitting on '_' and checking
        # for an exact token match avoids that false positive entirely (and
        # sidesteps '_' also being SQL LIKE's own single-character wildcard).
        if genres:
            genre_set = set(genres)
            rows = [r for r in rows if genre_set & _split_multi_value(r["genre"])]
        if languages:
            language_set = set(languages)
            rows = [r for r in rows if language_set & _split_multi_value(r["language"])]

        for r in rows:
            try:
                r["file_size"] = os.path.getsize(r["filepath"])
            except OSError:
                r["file_size"] = -1  # file missing / moved

        key_map = {
            "title": lambda r: r["title"].lower(),
            "recent": lambda r: r["last_opened"] or "",
            "added": lambda r: r["added_date"] or "",
            "size": lambda r: r["file_size"],
        }
        rows.sort(key=key_map.get(sort_by, key_map["title"]), reverse=descending)
        return rows

    def remove_book(self, book_id):
        self.conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self.conn.commit()

    def toggle_favorite(self, book_id):
        self.conn.execute(
            "UPDATE books SET is_favorite = 1 - is_favorite WHERE id = ?", (book_id,)
        )
        self.conn.commit()

    def update_progress(self, book_id, page):
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE books SET last_page = ?, last_opened = ? WHERE id = ?",
            (page, now, book_id),
        )
        self.conn.commit()

    def update_metadata(self, book_id, title=None, author=None, series=None,
                         language=None, genre=None, annotation=None):
        """Update any subset of the editable metadata fields (None = leave unchanged)."""
        fields, params = [], []
        for column, value in (
            ("title", title), ("author", author), ("series", series),
            ("language", language), ("genre", genre), ("annotation", annotation),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                params.append(value)
        if not fields:
            return
        params.append(book_id)
        self.conn.execute(f"UPDATE books SET {', '.join(fields)} WHERE id = ?", params)
        self.conn.commit()

    def update_filepath(self, book_id, new_filepath):
        self.conn.execute("UPDATE books SET filepath = ? WHERE id = ?", (new_filepath, book_id))
        self.conn.commit()

    def get_distinct_genres(self):
        """Individual genre tokens in use, splitting any multi-value
        ('Science Fiction_Fantasy') entries into their separate parts, so
        each genre is offered as its own filterable option."""
        cur = self.conn.execute(
            "SELECT DISTINCT genre FROM books WHERE genre IS NOT NULL AND genre != ''"
        )
        tokens = set()
        for r in cur.fetchall():
            tokens |= _split_multi_value(r["genre"])
        return sorted(tokens, key=str.lower)

    def get_distinct_languages(self):
        """Individual language tokens in use, splitting any multi-value
        ('English_Bulgarian') entries into their separate parts, so each
        language is offered as its own filterable option."""
        cur = self.conn.execute(
            "SELECT DISTINCT language FROM books WHERE language IS NOT NULL AND language != ''"
        )
        tokens = set()
        for r in cur.fetchall():
            tokens |= _split_multi_value(r["language"])
        return sorted(tokens, key=str.lower)

    def bulk_set_series(self, book_ids, value):
        book_ids = list(book_ids)
        if not book_ids:
            return
        self.conn.executemany(
            "UPDATE books SET series = ? WHERE id = ?", [(value, bid) for bid in book_ids]
        )
        self.conn.commit()

    def bulk_set_genre(self, book_ids, value):
        book_ids = list(book_ids)
        if not book_ids:
            return
        self.conn.executemany(
            "UPDATE books SET genre = ? WHERE id = ?", [(value, bid) for bid in book_ids]
        )
        self.conn.commit()

    def bulk_set_language(self, book_ids, value):
        book_ids = list(book_ids)
        if not book_ids:
            return
        self.conn.executemany(
            "UPDATE books SET language = ? WHERE id = ?", [(value, bid) for bid in book_ids]
        )
        self.conn.commit()

    def bulk_set_status(self, book_ids, status):
        book_ids = list(book_ids)
        if not book_ids or status not in ("unread", "to_read", "reading", "finished"):
            return
        self.conn.executemany(
            "UPDATE books SET status = ? WHERE id = ?", [(status, bid) for bid in book_ids]
        )
        self.conn.commit()

    def search_suggestions(self, query, limit=5):
        """Categorized quick-search results for the live preview dropdown:
        matching titles, plus distinct matching authors/series/genres/languages
        with book counts."""
        empty = {"titles": [], "authors": [], "series": [], "genres": [], "languages": []}
        query = (query or "").strip()
        if not query:
            return empty
        like = f"%{query}%"

        cur = self.conn.execute(
            "SELECT id, title FROM books WHERE title LIKE ? "
            "ORDER BY title COLLATE NOCASE LIMIT ?",
            (like, limit),
        )
        titles = [dict(r) for r in cur.fetchall()]

        cur = self.conn.execute(
            "SELECT author AS name, COUNT(*) AS count FROM books "
            "WHERE author IS NOT NULL AND author != '' AND author LIKE ? "
            "GROUP BY author COLLATE NOCASE ORDER BY author COLLATE NOCASE LIMIT ?",
            (like, limit),
        )
        authors = [dict(r) for r in cur.fetchall()]

        cur = self.conn.execute(
            "SELECT series AS name, COUNT(*) AS count FROM books "
            "WHERE series IS NOT NULL AND series != '' AND series LIKE ? "
            "GROUP BY series COLLATE NOCASE ORDER BY series COLLATE NOCASE LIMIT ?",
            (like, limit),
        )
        series = [dict(r) for r in cur.fetchall()]

        cur = self.conn.execute(
            "SELECT genre AS name, COUNT(*) AS count FROM books "
            "WHERE genre IS NOT NULL AND genre != '' AND genre LIKE ? "
            "GROUP BY genre COLLATE NOCASE ORDER BY genre COLLATE NOCASE LIMIT ?",
            (like, limit),
        )
        genres = [dict(r) for r in cur.fetchall()]

        cur = self.conn.execute(
            "SELECT language AS name, COUNT(*) AS count FROM books "
            "WHERE language IS NOT NULL AND language != '' AND language LIKE ? "
            "GROUP BY language COLLATE NOCASE ORDER BY language COLLATE NOCASE LIMIT ?",
            (like, limit),
        )
        languages = [dict(r) for r in cur.fetchall()]

        return {"titles": titles, "authors": authors, "series": series, "genres": genres, "languages": languages}

    def set_status(self, book_id, status):
        if status not in ("unread", "to_read", "reading", "finished"):
            return
        self.conn.execute("UPDATE books SET status = ? WHERE id = ?", (status, book_id))
        self.conn.commit()

    def mark_as_reading_if_new(self, book_id):
        """Called when a book is opened: promote it to 'reading' from either
        'unread' or 'to_read'. Never downgrades an already-'reading' or
        'finished' book."""
        book = self.get_book(book_id)
        if book and (book["status"] or "unread") in ("unread", "to_read"):
            self.set_status(book_id, "reading")

    # ---------------- Categories ----------------
    def create_category(self, name):
        """Create a category (a no-op if the name already exists, case-insensitively).
        Returns the category row either way."""
        name = (name or "").strip()
        if not name:
            return None
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO categories (name, created_date) VALUES (?, ?)",
            (name, now),
        )
        self.conn.commit()
        return self.get_category_by_name(name)

    def get_category_by_name(self, name):
        cur = self.conn.execute(
            "SELECT * FROM categories WHERE name = ? COLLATE NOCASE", (name,)
        )
        return cur.fetchone()

    def get_category(self, category_id):
        cur = self.conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
        return cur.fetchone()

    def get_categories(self):
        """All categories as plain dicts with a live book_count, favorites first
        then alphabetical (case-insensitive)."""
        cur = self.conn.execute(
            """
            SELECT categories.*, COUNT(book_categories.book_id) AS book_count
            FROM categories
            LEFT JOIN book_categories ON book_categories.category_id = categories.id
            GROUP BY categories.id
            ORDER BY categories.is_favorite DESC, categories.name COLLATE NOCASE ASC
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def rename_category(self, category_id, new_name):
        new_name = (new_name or "").strip()
        if not new_name:
            return False
        try:
            self.conn.execute(
                "UPDATE categories SET name = ? WHERE id = ?", (new_name, category_id)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # another category already has this name

    def delete_category(self, category_id):
        self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.conn.commit()

    def toggle_category_favorite(self, category_id):
        self.conn.execute(
            "UPDATE categories SET is_favorite = 1 - is_favorite WHERE id = ?", (category_id,)
        )
        self.conn.commit()

    def add_books_to_category(self, category_id, book_ids):
        """Bulk-add books to a category; duplicates are silently ignored."""
        book_ids = list(book_ids)
        if not book_ids:
            return 0
        self.conn.executemany(
            "INSERT OR IGNORE INTO book_categories (book_id, category_id) VALUES (?, ?)",
            [(bid, category_id) for bid in book_ids],
        )
        self.conn.commit()
        return len(book_ids)

    def remove_book_from_category(self, category_id, book_id):
        self.conn.execute(
            "DELETE FROM book_categories WHERE category_id = ? AND book_id = ?",
            (category_id, book_id),
        )
        self.conn.commit()

    def get_book_ids_by_author(self, author):
        cur = self.conn.execute(
            "SELECT id FROM books WHERE author = ? COLLATE NOCASE", (author,)
        )
        return [r["id"] for r in cur.fetchall()]

    def get_book_ids_by_series(self, series):
        cur = self.conn.execute(
            "SELECT id FROM books WHERE series = ? COLLATE NOCASE", (series,)
        )
        return [r["id"] for r in cur.fetchall()]

    def get_categories_for_book(self, book_id):
        cur = self.conn.execute(
            """
            SELECT categories.* FROM categories
            JOIN book_categories ON book_categories.category_id = categories.id
            WHERE book_categories.book_id = ?
            ORDER BY categories.name COLLATE NOCASE
            """,
            (book_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ---------------- Bookmarks ----------------
    def add_bookmark(self, book_id, page_number, label=""):
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            "INSERT INTO bookmarks (book_id, page_number, label, created_date) "
            "VALUES (?, ?, ?, ?)",
            (book_id, page_number, label, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_bookmarks(self, book_id):
        cur = self.conn.execute(
            "SELECT * FROM bookmarks WHERE book_id = ? ORDER BY page_number ASC",
            (book_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def delete_bookmark(self, bookmark_id):
        self.conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        self.conn.commit()

    # ---------------- Highlights ----------------
    def add_highlight(self, book_id, page_number, color, rects, text="", label="", style="fill"):
        """rects: a JSON-serializable list of [x0, y0, x1, y1] in the
        page's own PDF-point coordinate space (zoom-independent, so a
        saved highlight redraws correctly at any zoom level later).
        style: "fill" (a translucent highlighter-style block, the
        default), "underline", or "strikethrough"."""
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            "INSERT INTO highlights (book_id, page_number, label, color, text, rects, style, created_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (book_id, page_number, label, color, text, json.dumps(rects), style, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_highlights(self, book_id):
        cur = self.conn.execute(
            "SELECT * FROM highlights WHERE book_id = ? ORDER BY page_number ASC, id ASC",
            (book_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["rects"] = json.loads(r["rects"])
        return rows

    def get_highlights_for_page(self, book_id, page_number):
        cur = self.conn.execute(
            "SELECT * FROM highlights WHERE book_id = ? AND page_number = ? ORDER BY id ASC",
            (book_id, page_number),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["rects"] = json.loads(r["rects"])
        return rows

    def update_highlight_color(self, highlight_id, color):
        self.conn.execute("UPDATE highlights SET color = ? WHERE id = ?", (color, highlight_id))
        self.conn.commit()

    def update_highlight_label(self, highlight_id, label):
        self.conn.execute("UPDATE highlights SET label = ? WHERE id = ?", (label, highlight_id))
        self.conn.commit()

    def update_highlight_style(self, highlight_id, style):
        self.conn.execute("UPDATE highlights SET style = ? WHERE id = ?", (style, highlight_id))
        self.conn.commit()

    def delete_highlight(self, highlight_id):
        self.conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
        self.conn.commit()

    # ---------------- Settings ----------------
    def get_setting(self, key, default=None):
        cur = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.conn.commit()
