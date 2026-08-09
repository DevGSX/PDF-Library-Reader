"""SQLite-backed storage for the PDF library: books, bookmarks and app settings."""
import os
import sqlite3
from pathlib import Path
from datetime import datetime


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
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.conn.commit()
        self._migrate_books_table()

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
            "status": "TEXT DEFAULT 'unread'",  # 'unread' | 'reading' | 'finished'
        }
        for col, decl in new_columns.items():
            if col not in existing_cols:
                self.conn.execute(f"ALTER TABLE books ADD COLUMN {col} {decl}")
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

    def get_book(self, book_id):
        cur = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        return cur.fetchone()

    def get_books(self, favorites_only=False, search=None, sort_by="title", descending=False, status=None):
        """Return library entries as plain dicts, each carrying a live file_size.
        `status`, if given, restricts to one of 'unread' | 'reading' | 'finished'."""
        query = "SELECT * FROM books"
        clauses, params = [], []
        if favorites_only:
            clauses.append("is_favorite = 1")
        if status:
            clauses.append("status = ?")
            params.append(status)
        if search:
            clauses.append("(title LIKE ? OR author LIKE ? OR series LIKE ? OR genre LIKE ?)")
            params.extend([f"%{search}%"] * 4)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        cur = self.conn.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            try:
                r["file_size"] = os.path.getsize(r["filepath"])
            except OSError:
                r["file_size"] = -1  # file missing / moved

        key_map = {
            "title": lambda r: r["title"].lower(),
            "recent": lambda r: r["last_opened"] or "",
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

    def search_suggestions(self, query, limit=5):
        """Categorized quick-search results for the live preview dropdown:
        matching titles, plus distinct matching authors/series/genres with book counts."""
        empty = {"titles": [], "authors": [], "series": [], "genres": []}
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

        return {"titles": titles, "authors": authors, "series": series, "genres": genres}

    def set_status(self, book_id, status):
        if status not in ("unread", "reading", "finished"):
            return
        self.conn.execute("UPDATE books SET status = ? WHERE id = ?", (status, book_id))
        self.conn.commit()

    def mark_as_reading_if_new(self, book_id):
        """Called when a book is opened: promote it from 'unread' to 'reading'.
        Never downgrades an already-'reading' or 'finished' book."""
        book = self.get_book(book_id)
        if book and (book["status"] or "unread") == "unread":
            self.set_status(book_id, "reading")

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
