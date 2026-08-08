"""Light and dark stylesheets (Qt QSS) shared by every window in the app."""

LIGHT_THEME = """
QMainWindow, QWidget {
    background-color: #f5f5f5;
    color: #202020;
}
QToolBar {
    background-color: #e8e8e8;
    border: none;
    spacing: 6px;
    padding: 4px;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #c9c9c9;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #eaeaea; }
QPushButton:pressed { background-color: #dadada; }
QPushButton:checked { background-color: #cfe4ff; border-color: #6ba6ff; }
QLineEdit, QComboBox, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #c9c9c9;
    border-radius: 4px;
    padding: 4px;
}
QListWidget {
    background-color: #ffffff;
    border: 1px solid #dcdcdc;
}
QTextBrowser {
    background-color: #ffffff;
    color: #1a1a1a;
    border: none;
    padding: 24px;
}
QScrollArea { border: none; }
QLabel#pageLabel { background-color: #ffffff; }
QDockWidget { color: #202020; }
QDockWidget::title { background: #e8e8e8; padding: 4px; }
QStatusBar { background-color: #e8e8e8; }
"""

DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
}
QToolBar {
    background-color: #2a2a2a;
    border: none;
    spacing: 6px;
    padding: 4px;
}
QPushButton {
    background-color: #333333;
    color: #e0e0e0;
    border: 1px solid #454545;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #3d3d3d; }
QPushButton:pressed { background-color: #4a4a4a; }
QPushButton:checked { background-color: #2f5378; border-color: #4d8fd6; }
QLineEdit, QComboBox, QSpinBox {
    background-color: #2a2a2a;
    color: #e0e0e0;
    border: 1px solid #454545;
    border-radius: 4px;
    padding: 4px;
}
QListWidget {
    background-color: #232323;
    border: 1px solid #3a3a3a;
}
QTextBrowser {
    background-color: #1a1a1a;
    color: #d8d8d8;
    border: none;
    padding: 24px;
}
QScrollArea { border: none; }
QLabel#pageLabel { background-color: #1a1a1a; }
QDockWidget { color: #e0e0e0; }
QDockWidget::title { background: #2a2a2a; padding: 4px; }
QStatusBar { background-color: #2a2a2a; }
"""
