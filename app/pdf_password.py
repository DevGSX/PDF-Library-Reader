"""Handling for password-protected PDFs: a dialog to unlock one for the
current session, with an optional follow-up to permanently strip or change
its password on disk.
"""
import os
import tempfile

import pymupdf as fitz
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class PasswordUnlockDialog(QDialog):
    """Returns via password()/wants_remove()/wants_change()/new_password()
    after being exec()'d and accepted. Callers should verify the password is
    actually correct themselves (authenticate against the real document) --
    this dialog only collects the input."""

    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Password Protected")
        self.resize(380, 240)
        layout = QVBoxLayout(self)

        hint = QLabel(f"\u201c{filename}\u201d is password protected. Enter the password to open it.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_edit)

        self.remove_check = QCheckBox("Also remove the password from this file permanently")
        self.remove_check.toggled.connect(self._on_remove_toggled)
        layout.addWidget(self.remove_check)

        self.change_check = QCheckBox("Or change it to a new password instead")
        self.change_check.toggled.connect(self._on_change_toggled)
        layout.addWidget(self.change_check)

        self.new_password_edit = QLineEdit()
        self.new_password_edit.setEchoMode(QLineEdit.Password)
        self.new_password_edit.setPlaceholderText("New password")
        self.new_password_edit.hide()
        layout.addWidget(self.new_password_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        unlock_btn = QPushButton("Unlock")
        unlock_btn.setDefault(True)
        unlock_btn.clicked.connect(self.accept)
        btn_row.addWidget(unlock_btn)
        layout.addLayout(btn_row)

        self.password_edit.setFocus()

    def _on_remove_toggled(self, checked):
        if checked:
            self.change_check.setChecked(False)

    def _on_change_toggled(self, checked):
        if checked:
            self.remove_check.setChecked(False)
        self.new_password_edit.setVisible(checked)

    def password(self):
        return self.password_edit.text()

    def wants_remove(self):
        return self.remove_check.isChecked()

    def wants_change(self):
        return self.change_check.isChecked()

    def new_password(self):
        return self.new_password_edit.text()


def strip_or_change_password(filepath, current_password, new_password=None):
    """Re-save the PDF without its current password (new_password=None), or
    re-encrypted with a different one. Saves to a temp file in the same
    directory first, then atomically replaces the original, so a failure
    partway through never leaves a corrupted or half-written file behind.
    Returns (success: bool, error_message: str | None)."""
    doc = None
    tmp_path = None
    try:
        doc = fitz.open(filepath)
        if doc.needs_pass and not doc.authenticate(current_password):
            return False, "Incorrect password."

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(filepath) or ".")
        os.close(fd)
        if new_password:
            doc.save(
                tmp_path, encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=new_password, user_pw=new_password,
            )
        else:
            doc.save(tmp_path, encryption=fitz.PDF_ENCRYPT_NONE)
        doc.close()
        doc = None
        os.replace(tmp_path, filepath)
        tmp_path = None
        return True, None
    except Exception as exc:
        return False, str(exc)
    finally:
        if doc is not None:
            doc.close()
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
