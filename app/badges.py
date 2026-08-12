"""Draws the small status decorations onto a cover thumbnail: a colored
banner across the top -- green "FINISHED", blue "READING" -- and a gold star
badge in the bottom-right corner for favorites. The cached thumbnail file on
disk is never modified -- we always decorate a copy so status/favorite
changes don't require re-rendering the PDF page.
"""
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygon

BANNER_COLORS = {
    "finished": QColor(34, 139, 60, 235),   # green
    "reading": QColor(33, 115, 235, 235),   # blue
}
BANNER_TEXT = {
    "finished": "FINISHED",
    "reading": "READING",
}
FAVORITE_COLOR = QColor(255, 179, 0, 240)  # gold/amber
CORRUPTED_COLOR = QColor(220, 38, 38, 245)  # red


def decorate_thumbnail(pixmap: QPixmap, status: str, is_favorite: bool = False,
                        is_corrupted: bool = False) -> QPixmap:
    if status not in BANNER_COLORS and not is_favorite and not is_corrupted:
        return pixmap

    decorated = QPixmap(pixmap)
    painter = QPainter(decorated)
    painter.setRenderHint(QPainter.Antialiasing)
    w, h = decorated.width(), decorated.height()

    if status in BANNER_COLORS:
        banner_h = max(20, int(h * 0.13))
        painter.fillRect(QRect(0, 0, w, banner_h), BANNER_COLORS[status])
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(8, int(banner_h * 0.5)))
        painter.setFont(font)
        painter.drawText(QRect(0, 0, w, banner_h), Qt.AlignCenter, BANNER_TEXT[status])

    if is_favorite:
        d = max(20, int(w * 0.2))
        margin = 6
        x = w - d - margin
        y = h - d - margin
        painter.setBrush(QBrush(FAVORITE_COLOR))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(x, y, d, d)
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(8, int(d * 0.55)))
        painter.setFont(font)
        painter.drawText(QRect(x, y, d, d), Qt.AlignCenter, "\u2605")

    if is_corrupted:
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
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(8, int(d * 0.42)))
        painter.setFont(font)
        painter.drawText(QRect(x, y + int(d * 0.18), d, d), Qt.AlignHCenter | Qt.AlignTop, "!")

    painter.end()
    return decorated
