#!/usr/bin/env python3
"""PDF Library Reader — entry point.

Run with: python3 main.py
(or use run.sh after running install.sh, which sets up a virtual environment)
"""
import sys

from PySide6.QtWidgets import QApplication

from app.database import Database
from app.library_window import LibraryWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Library Reader")
    db = Database()
    window = LibraryWindow(db)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
