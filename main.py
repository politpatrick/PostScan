import os
import shutil
import sys

import pikepdf
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QMessageBox, QProgressBar, QFrame, QGridLayout,
)

import database
import pipeline

ARCHIV_DIR = os.path.join(os.path.dirname(__file__), "archiv")


class AnalyzeWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self):
        try:
            result = pipeline.analyze(self.pdf_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_path: str = ""
        self.date_candidates: list[str] = []
        self._worker: AnalyzeWorker | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Drop / open area
        top = QHBoxLayout()
        self.btn_open = QPushButton("PDF öffnen …")
        self.btn_open.clicked.connect(self._open_pdf)
        self.lbl_file = QLabel("Kein Dokument geladen")
        self.lbl_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_file)
        root.addLayout(top)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # Fields
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        def _make_combo(editable=True):
            c = QComboBox()
            c.setEditable(editable)
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return c

        self.cb_typ = _make_combo()
        self.cb_absender = _make_combo()
        self.cb_datum = _make_combo()
        self.cb_person = _make_combo()

        fields = [
            ("Dokumenttyp:", self.cb_typ),
            ("Absender:", self.cb_absender),
            ("Dokumentdatum:", self.cb_datum),
            ("Personenbezug:", self.cb_person),
        ]
        for row, (lbl, widget) in enumerate(fields):
            grid.addWidget(QLabel(lbl), row, 0)
            grid.addWidget(widget, row, 1)

        root.addLayout(grid)

        # Preview label
        self.lbl_preview = QLabel()
        self.lbl_preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setWordWrap(True)
        font = self.lbl_preview.font()
        font.setPointSize(11)
        self.lbl_preview.setFont(font)
        root.addWidget(self.lbl_preview)

        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.currentTextChanged.connect(self._update_preview)

        # Confirm
        self.btn_confirm = QPushButton("Bestätigen & Archivieren")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._confirm)
        root.addWidget(self.btn_confirm)

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF öffnen", "", "PDF-Dateien (*.pdf)")
        if not path:
            return
        self.pdf_path = path
        self.lbl_file.setText(os.path.basename(path))
        self.btn_confirm.setEnabled(False)
        self._clear_fields()
        self.progress.setVisible(True)
        self._worker = AnalyzeWorker(path)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _clear_fields(self):
        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.clear()
        self.lbl_preview.setText("")

    def _populate_combos(self):
        self.cb_typ.addItems([""] + database.get_unique_values("dokumenttyp"))
        self.cb_absender.addItems([""] + database.get_unique_values("absender"))
        self.cb_person.addItems([""] + database.get_unique_values("personenbezug"))

    def _on_analysis_done(self, result: dict):
        self.progress.setVisible(False)
        self.date_candidates = result.get("dokumentdatum_candidates", [])
        self._populate_combos()

        def _set(combo, value):
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setCurrentText(value)

        _set(self.cb_typ, result.get("dokumenttyp", ""))
        _set(self.cb_absender, result.get("absender", ""))
        _set(self.cb_person, result.get("personenbezug", ""))

        self.cb_datum.clear()
        if self.date_candidates:
            self.cb_datum.addItems(self.date_candidates)
            self.cb_datum.setCurrentIndex(0)
        else:
            self.cb_datum.setCurrentText(result.get("dokumentdatum", ""))

        self.btn_confirm.setEnabled(True)
        self._update_preview()

    def _on_analysis_error(self, msg: str):
        self.progress.setVisible(False)
        QMessageBox.critical(self, "Fehler", f"Analyse fehlgeschlagen:\n{msg}")

    def _update_preview(self):
        typ = self.cb_typ.currentText().strip()
        ab = self.cb_absender.currentText().strip()
        dat = self.cb_datum.currentText().strip()
        per = self.cb_person.currentText().strip()
        parts = [p for p in [typ, ab, dat, per] if p]
        name = "_".join(parts) + ".pdf" if parts else ""
        self.lbl_preview.setText(name or "—")

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

        database.add_or_update({
            "dokumenttyp": typ,
            "absender": ab,
            "personenbezug": per,
        })

        parts = [p for p in [typ, ab, dat, per] if p]
        new_name = "_".join(parts) + ".pdf"

        try:
            _write_xmp(self.pdf_path, typ, ab, dat, per)
        except Exception as e:
            QMessageBox.warning(self, "XMP-Warnung", f"Metadaten konnten nicht geschrieben werden:\n{e}")

        os.makedirs(ARCHIV_DIR, exist_ok=True)
        dest = os.path.join(ARCHIV_DIR, new_name)
        if os.path.exists(dest):
            base, ext = os.path.splitext(new_name)
            dest = os.path.join(ARCHIV_DIR, f"{base}_1{ext}")
        shutil.move(self.pdf_path, dest)

        QMessageBox.information(self, "Archiviert", f"Gespeichert als:\n{new_name}")
        self.pdf_path = ""
        self.lbl_file.setText("Kein Dokument geladen")
        self._clear_fields()
        self.btn_confirm.setEnabled(False)
        self.window().findChild(SettingsTab).refresh()  # type: ignore[union-attr]


def _write_xmp(pdf_path: str, typ: str, ab: str, dat: str, per: str):
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        with pdf.open_metadata() as meta:
            meta["dc:description"] = f"{typ} von {ab}"
            meta["dc:subject"] = [typ, ab, per] if per else [typ, ab]
            meta["xmp:CreateDate"] = dat
        pdf.save(pdf_path)


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
        self.btn_add = QPushButton("Eintrag hinzufügen")
        self.btn_del = QPushButton("Markierte löschen")
        self.btn_save = QPushButton("Änderungen speichern")
        self.btn_add.clicked.connect(self._add_row)
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_save.clicked.connect(self._save)
        btn_bar.addWidget(self.btn_add)
        btn_bar.addWidget(self.btn_del)
        btn_bar.addWidget(self.btn_save)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PostScan")
        self.resize(700, 480)
        tabs = QTabWidget()
        self.main_tab = MainTab()
        self.settings_tab = SettingsTab()
        tabs.addTab(self.main_tab, "Dokument")
        tabs.addTab(self.settings_tab, "Stammdaten")
        self.setCentralWidget(tabs)


def main():
    database.ensure_defaults()
    app = QApplication(sys.argv)
    app.setApplicationName("PostScan")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
