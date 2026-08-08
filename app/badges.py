"""Draws the small reading-status decoration onto a cover thumbnail: a colored
banner across the top -- green "FINISHED", blue "READING". The cached
thumbnail file on disk is never modified -- we always decorate a copy so
status changes don't require re-rendering the PDF page.
"""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

BANNER_COLORS = {
    "finished": QColor(34, 139, 60, 235),   # green
    "reading": QColor(33, 115, 235, 235),   # blue
}
BANNER_TEXT = {
    "finished": "FINISHED",
    "reading": "READING",
}


def decorate_thumbnail(pixmap: QPixmap, status: str) -> QPixmap:
    if status not in BANNER_COLORS:
        return pixmap

    decorated = QPixmap(pixmap)
    painter = QPainter(decorated)
    painter.setRenderHint(QPainter.Antialiasing)
    w, h = decorated.width(), decorated.height()

    banner_h = max(20, int(h * 0.13))
    painter.fillRect(QRect(0, 0, w, banner_h), BANNER_COLORS[status])
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(max(8, int(banner_h * 0.5)))
    painter.setFont(font)
    painter.drawText(QRect(0, 0, w, banner_h), Qt.AlignCenter, BANNER_TEXT[status])

    painter.end()
    return decorated
