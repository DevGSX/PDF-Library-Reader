"""Thumbnail generation and disk caching for the library's image-preview view."""
import pymupdf as fitz
from PySide6.QtGui import QColor, QPixmap

from .database import get_data_dir

THUMB_SIZE = (140, 190)  # roughly paperback-cover proportions, in pixels


def _thumb_dir():
    d = get_data_dir() / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbnail_path(book_id):
    return _thumb_dir() / f"{book_id}.png"


def ensure_thumbnail(book_id, filepath):
    """Return a QPixmap thumbnail of the book's first page.

    Generated once and cached to disk; later calls just load the cached file.
    """
    path = thumbnail_path(book_id)
    if path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix

    try:
        doc = fitz.open(filepath)
        page = doc[0]
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError("degenerate page size")
        scale = min(THUMB_SIZE[0] / rect.width, THUMB_SIZE[1] / rect.height)
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix)
        pix.save(str(path))
        doc.close()
        qpix = QPixmap(str(path))
        return qpix if not qpix.isNull() else _placeholder()
    except Exception:
        return _placeholder()


def _placeholder():
    pix = QPixmap(*THUMB_SIZE)
    pix.fill(QColor(225, 225, 225))
    return pix


def delete_thumbnail(book_id):
    path = thumbnail_path(book_id)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
