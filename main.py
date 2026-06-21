import os
import shutil
import sys

import pikepdf
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QMessageBox, QProgressBar, QFrame, QGridLayout, QStatusBar,
)

import database
import pipeline

EINGANG_DIR = os.path.join(os.path.dirname(__file__), "eingang")
ARCHIV_DIR = os.path.join(os.path.dirname(__file__), "archiv")


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class AnalyzeWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self):
        try:
            self.finished.emit(pipeline.analyze(self.pdf_path))
        except Exception as e:
            self.error.emit(str(e))


class ConfirmWorker(QThread):
    finished = pyqtSignal(str)   # new file path in archiv/
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str, typ: str, ab: str, dat: str, per: str):
        super().__init__()
        self.pdf_path = pdf_path
        self.typ = typ
        self.ab = ab
        self.dat = dat
        self.per = per

    def run(self):
        try:
            # a) Real-Time Learning
            database.add_or_update({
                "dokumenttyp": self.typ,
                "absender": self.ab,
                "personenbezug": self.per,
            })

            # b) XMP metadata
            _write_xmp(self.pdf_path, self.typ, self.ab, self.dat, self.per)

            # c) Move & rename
            os.makedirs(ARCHIV_DIR, exist_ok=True)
            parts = [p for p in [self.typ, self.ab, self.dat, self.per] if p]
            new_name = "_".join(parts) + ".pdf"
            dest = os.path.join(ARCHIV_DIR, new_name)
            if os.path.exists(dest):
                base, ext = os.path.splitext(new_name)
                dest = os.path.join(ARCHIV_DIR, f"{base}_1{ext}")
            shutil.move(self.pdf_path, dest)
            self.finished.emit(dest)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# XMP helper (module-level, called from ConfirmWorker thread)
# ---------------------------------------------------------------------------

def _write_xmp(pdf_path: str, typ: str, ab: str, dat: str, per: str) -> None:
    tmp_path = pdf_path + ".tmp.pdf"
    try:
        with pikepdf.open(pdf_path) as pdf:
            with pdf.open_metadata() as meta:
                meta["dc:description"] = f"{typ} von {ab}"
                meta["dc:subject"] = [x for x in [typ, ab, per] if x]
                if dat:
                    meta["xmp:CreateDate"] = dat
            pdf.save(tmp_path)
        os.replace(tmp_path, pdf_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Main document tab
# ---------------------------------------------------------------------------

class MainTab(QWidget):
    settings_refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_path: str = ""
        self._analyze_worker: AnalyzeWorker | None = None
        self._confirm_worker: ConfirmWorker | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # File open row
        top = QHBoxLayout()
        self.btn_open = QPushButton("PDF öffnen …")
        self.btn_open.clicked.connect(self._open_pdf)
        self.lbl_file = QLabel("Kein Dokument geladen")
        self.lbl_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_file)
        root.addLayout(top)

        # Progress bar (indeterminate while analyzing)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # Source/confidence info
        self.lbl_source = QLabel("")
        self.lbl_source.setAlignment(Qt.AlignmentFlag.AlignRight)
        font = self.lbl_source.font()
        font.setPointSize(9)
        self.lbl_source.setFont(font)
        root.addWidget(self.lbl_source)

        # Extraction fields
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        def _combo() -> QComboBox:
            c = QComboBox()
            c.setEditable(True)
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return c

        self.cb_typ = _combo()
        self.cb_absender = _combo()
        self.cb_datum = _combo()
        self.cb_person = _combo()

        for row, (lbl, widget) in enumerate([
            ("Dokumenttyp:", self.cb_typ),
            ("Absender:", self.cb_absender),
            ("Dokumentdatum:", self.cb_datum),
            ("Personenbezug:", self.cb_person),
        ]):
            grid.addWidget(QLabel(lbl), row, 0)
            grid.addWidget(widget, row, 1)

        root.addLayout(grid)

        # Filename preview
        self.lbl_preview = QLabel("—")
        self.lbl_preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setWordWrap(True)
        font2 = self.lbl_preview.font()
        font2.setPointSize(11)
        self.lbl_preview.setFont(font2)
        root.addWidget(self.lbl_preview)

        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.currentTextChanged.connect(self._update_preview)

        # Confirm button
        self.btn_confirm = QPushButton("Bestätigen & Archivieren")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._confirm)
        root.addWidget(self.btn_confirm)

    # ------------------------------------------------------------------

    def _open_pdf(self):
        os.makedirs(EINGANG_DIR, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF öffnen", EINGANG_DIR, "PDF-Dateien (*.pdf)"
        )
        if not path:
            return
        self.pdf_path = path
        self.lbl_file.setText(os.path.basename(path))
        self.lbl_source.setText("")
        self.btn_confirm.setEnabled(False)
        self.btn_open.setEnabled(False)
        self._clear_fields()
        self.progress.setVisible(True)

        self._analyze_worker = AnalyzeWorker(path)
        self._analyze_worker.finished.connect(self._on_analysis_done)
        self._analyze_worker.error.connect(self._on_analysis_error)
        self._analyze_worker.start()

    def _clear_fields(self):
        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.clear()
        self.lbl_preview.setText("—")

    def _populate_combos(self):
        self.cb_typ.addItems([""] + database.get_unique_values("dokumenttyp"))
        self.cb_absender.addItems([""] + database.get_unique_values("absender"))
        self.cb_person.addItems([""] + database.get_unique_values("personenbezug"))

    def _on_analysis_done(self, result: dict):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self._populate_combos()

        source = result.get("source", "")
        conf = result.get("confidence", 0.0)
        if source == "tfidf":
            self.lbl_source.setText(f"Fast-Lane (TF-IDF) · Konfidenz: {conf:.0%}")
        else:
            self.lbl_source.setText(f"LLM-Fallback (phi3:mini) · TF-IDF: {conf:.0%}")

        def _set(combo: QComboBox, value: str):
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setCurrentText(value)

        _set(self.cb_typ, result.get("dokumenttyp", ""))
        _set(self.cb_absender, result.get("absender", ""))
        _set(self.cb_person, result.get("personenbezug", ""))

        candidates = result.get("dokumentdatum_candidates", [])
        self.cb_datum.clear()
        if candidates:
            self.cb_datum.addItems(candidates)
            primary = result.get("dokumentdatum", "")
            idx = self.cb_datum.findText(primary)
            self.cb_datum.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.cb_datum.setCurrentText(result.get("dokumentdatum", ""))

        self.btn_confirm.setEnabled(True)
        self._update_preview()

    def _on_analysis_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        QMessageBox.critical(self, "Fehler", f"Analyse fehlgeschlagen:\n{msg}")

    def _update_preview(self):
        parts = [
            cb.currentText().strip()
            for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person)
        ]
        non_empty = [p for p in parts if p]
        self.lbl_preview.setText("_".join(non_empty) + ".pdf" if non_empty else "—")

    def _confirm(self):
        if not self.pdf_path:
            return
        typ = self.cb_typ.currentText().strip()
        ab = self.cb_absender.currentText().strip()
        dat = self.cb_datum.currentText().strip()
        per = self.cb_person.currentText().strip()

        if not typ or not ab:
            QMessageBox.warning(self, "Fehlende Felder", "Bitte Dokumenttyp und Absender angeben.")
            return

        self.btn_confirm.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.progress.setVisible(True)

        self._confirm_worker = ConfirmWorker(self.pdf_path, typ, ab, dat, per)
        self._confirm_worker.finished.connect(self._on_confirm_done)
        self._confirm_worker.error.connect(self._on_confirm_error)
        self._confirm_worker.start()

    def _on_confirm_done(self, dest: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        new_name = os.path.basename(dest)
        QMessageBox.information(self, "Archiviert", f"Gespeichert als:\n{new_name}")
        self.pdf_path = ""
        self.lbl_file.setText("Kein Dokument geladen")
        self.lbl_source.setText("")
        self._clear_fields()
        self.settings_refresh_requested.emit()

    def _on_confirm_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.btn_confirm.setEnabled(True)
        QMessageBox.critical(self, "Fehler", f"Archivierung fehlgeschlagen:\n{msg}")


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------

class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Dokumenttyp", "Absender", "Personenbezug"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_bar = QHBoxLayout()
        btn_add = QPushButton("Eintrag hinzufügen")
        btn_del = QPushButton("Markierte löschen")
        btn_save = QPushButton("Änderungen speichern")
        btn_add.clicked.connect(self._add_row)
        btn_del.clicked.connect(self._delete_selected)
        btn_save.clicked.connect(self._save)
        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(btn_del)
        btn_bar.addWidget(btn_save)
        layout.addLayout(btn_bar)

    def refresh(self):
        entries = database.load()
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            for col, key in enumerate(["dokumenttyp", "absender", "personenbezug"]):
                self.table.setItem(row, col, QTableWidgetItem(e.get(key, "")))

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col in range(3):
            self.table.setItem(row, col, QTableWidgetItem(""))

    def _delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def _save(self):
        entries = []
        for row in range(self.table.rowCount()):
            entries.append({
                "dokumenttyp": (self.table.item(row, 0) or QTableWidgetItem("")).text().strip(),
                "absender": (self.table.item(row, 1) or QTableWidgetItem("")).text().strip(),
                "personenbezug": (self.table.item(row, 2) or QTableWidgetItem("")).text().strip(),
            })
        database.save(entries)
        QMessageBox.information(self, "Gespeichert", "Stammdaten gespeichert.")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PostScan")
        self.resize(720, 520)

        tabs = QTabWidget()
        self.main_tab = MainTab()
        self.settings_tab = SettingsTab()

        # Wire settings refresh signal via direct reference (no fragile findChild)
        self.main_tab.settings_refresh_requested.connect(self.settings_tab.refresh)

        tabs.addTab(self.main_tab, "Dokument")
        tabs.addTab(self.settings_tab, "Stammdaten")
        self.setCentralWidget(tabs)

        status = QStatusBar()
        status.showMessage("PostScan bereit")
        self.setStatusBar(status)


def main():
    database.ensure_defaults()
    os.makedirs(EINGANG_DIR, exist_ok=True)
    os.makedirs(ARCHIV_DIR, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName("PostScan")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
