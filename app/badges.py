"""Draws small status decorations onto a cover thumbnail: a colored circular
icon badge in the top-right corner shows reading status (a checkmark for
finished, a play-style triangle for reading, a bookmark ribbon for to-read),
a gold star badge in the bottom-right corner marks favorites, and a red
warning triangle in the bottom-left marks files that failed to render.

All of these are drawn as plain vector shapes (circles, polygons, stroked
paths) rather than text. That's deliberate: text has to be measured and
fitted against however tall the *specific* thumbnail happens to be, and
that height varies wildly with a page's aspect ratio -- a landscape or
two-page-spread source page can render barely a few dozen pixels tall,
which is exactly what caused status labels to clip in earlier versions of
this file. A vector icon has no font metrics to fight: its size is derived
from the thumbnail's WIDTH, which the generator keeps effectively constant
regardless of aspect ratio, so it never needs to shrink to fit and can
never clip.

The cached thumbnail file on disk is never modified -- we always decorate a
copy so status/favorite changes don't require re-rendering the PDF page.
"""
import math

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygon, QPolygonF

STATUS_COLORS = {
    "finished": QColor(34, 139, 60, 235),   # green
    "reading": QColor(33, 115, 235, 235),   # blue
    "to_read": QColor(124, 58, 237, 235),   # purple
}
FAVORITE_COLOR = QColor(255, 179, 0, 240)  # gold/amber
CORRUPTED_COLOR = QColor(220, 38, 38, 245)  # red
BADGE_MARGIN = 6


def decorate_thumbnail(pixmap: QPixmap, status: str, is_favorite: bool = False,
                        is_corrupted: bool = False) -> QPixmap:
    if status not in STATUS_COLORS and not is_favorite and not is_corrupted:
        return pixmap

    decorated = QPixmap(pixmap)
    painter = QPainter(decorated)
    painter.setRenderHint(QPainter.Antialiasing)
    w, h = decorated.width(), decorated.height()

    # Below this there's no sensible way to fit a margin-plus-circle at all
    # (this only happens at page aspect ratios far beyond any real book, but
    # it costs nothing to guard against outright).
    if h <= 2 * BADGE_MARGIN:
        painter.end()
        return decorated

    show_status = status in STATUS_COLORS
    d = _badge_diameter(w, h)
    gap = max(2, int(d * 0.15))

    if show_status and is_favorite and h < 2 * d + 2 * BADGE_MARGIN + gap:
        # Not enough vertical room for one badge at the top and one at the
        # bottom without them touching (or, on very short thumbnails,
        # landing on literally the same pixels). Put both along the top
        # instead, side by side -- width is always the dimension with room
        # to spare here.
        status_x = max(0, w - d - BADGE_MARGIN)
        status_y = BADGE_MARGIN
        fav_x = max(0, status_x - d - gap)
        fav_y = BADGE_MARGIN
    else:
        status_x = fav_x = max(0, w - d - BADGE_MARGIN)
        status_y = BADGE_MARGIN
        fav_y = max(0, h - d - BADGE_MARGIN)

    if show_status:
        painter.setBrush(QBrush(STATUS_COLORS[status]))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(status_x, status_y, d, d)
        _draw_status_icon(painter, status, status_x, status_y, d)

    if is_favorite:
        painter.setBrush(QBrush(FAVORITE_COLOR))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(fav_x, fav_y, d, d)
        _draw_star_icon(painter, fav_x, fav_y, d)

    if is_corrupted:
        # Corrupted files always render through the fixed-size placeholder
        # (see thumbnails.py), so there's no short-thumbnail case to guard
        # against here -- this one stays exactly as it always has.
        d = max(24, int(w * 0.24))
        margin = 6
        x = margin  # bottom-left, so it doesn't collide with the favorite star
        y = h - d - margin
        triangle = QPolygon([
            QPoint(x + d // 2, y),
            QPoint(x + d, y + d),
            QPoint(x, y + d),
        ])
        painter.setBrush(QBrush(CORRUPTED_COLOR))
        painter.setPen(QPen(QColor("white"), 1.5))
        painter.drawPolygon(triangle)
        _draw_exclamation_icon(painter, x, y, d)

    painter.end()
    return decorated


def _badge_diameter(w, h):
    """Diameter for a corner badge circle: a fraction of the thumbnail's
    WIDTH (which the thumbnail generator holds close to constant no matter
    how wide/short the source page is), clamped so it never exceeds what
    the actual HEIGHT can hold on a pathologically short thumbnail."""
    by_width = max(16, int(w * 0.16))
    by_height = max(8, h - 2 * BADGE_MARGIN)
    return min(by_width, by_height)


def _draw_status_icon(painter, status, x, y, d):
    """A small white pictogram inside the circle at (x, y, d, d): checkmark
    for finished, right-pointing triangle for reading, bookmark ribbon for
    to-read. Every coordinate is a fraction of d, so the icon always sits
    fully inside its circle regardless of how small d gets."""
    if status == "finished":
        pen = QPen(QColor("white"), max(1.5, d * 0.12), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(x + d * 0.27, y + d * 0.52)
        path.lineTo(x + d * 0.43, y + d * 0.68)
        path.lineTo(x + d * 0.75, y + d * 0.32)
        painter.drawPath(path)

    elif status == "reading":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("white")))
        triangle = QPolygonF([
            QPointF(x + d * 0.36, y + d * 0.24),
            QPointF(x + d * 0.36, y + d * 0.76),
            QPointF(x + d * 0.74, y + d * 0.5),
        ])
        painter.drawPolygon(triangle)

    elif status == "to_read":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("white")))
        ribbon = QPolygonF([
            QPointF(x + d * 0.32, y + d * 0.18),
            QPointF(x + d * 0.68, y + d * 0.18),
            QPointF(x + d * 0.68, y + d * 0.82),
            QPointF(x + d * 0.5, y + d * 0.64),
            QPointF(x + d * 0.32, y + d * 0.82),
        ])
        painter.drawPolygon(ribbon)


def _draw_star_icon(painter, x, y, d):
    """A simple 5-point white star, sized purely from d -- no font glyph."""
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("white")))
    cx, cy = x + d / 2, y + d / 2
    outer, inner = d * 0.42, d * 0.18
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / 5
        points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    painter.drawPolygon(QPolygonF(points))


def _draw_exclamation_icon(painter, x, y, d):
    """The corrupted-file warning mark, drawn as a stroke + dot instead of
    a text glyph (kept purely for consistency with the other icons here)."""
    pen = QPen(QColor("white"), max(1.5, d * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    cx = x + d / 2
    painter.drawLine(QPointF(cx, y + d * 0.32), QPointF(cx, y + d * 0.62))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("white")))
    r = max(1.2, d * 0.05)
    painter.drawEllipse(QPointF(cx, y + d * 0.74), r, r)
