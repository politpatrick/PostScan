import os
import re
import shutil
import sys

import pikepdf
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QMessageBox, QProgressBar, QFrame, QGridLayout, QStatusBar,
    QGroupBox,
)

import database
import pipeline

EINGANG_DIR = os.path.join(os.path.dirname(__file__), "eingang")
ARCHIV_DIR = os.path.join(os.path.dirname(__file__), "archiv")


def _select_on_focus(combo: QComboBox) -> None:
    """Select all text when the user clicks into an editable combobox."""
    le = combo.lineEdit()
    orig = le.focusInEvent
    def _on_focus(event):
        orig(event)
        QTimer.singleShot(0, le.selectAll)
    le.focusInEvent = _on_focus


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
            # a) Real-Time Learning — all lists independent
            database.add_dokumenttyp(self.typ)
            database.add_absender(self.ab)
            if self.per:
                database.add_person(self.per)
            database.add_kombination(self.typ, self.ab)

            # b) XMP metadata
            _write_xmp(self.pdf_path, self.typ, self.ab, self.dat, self.per)

            # c) Move & rename
            os.makedirs(ARCHIV_DIR, exist_ok=True)
            parts = [p for p in [self.typ, self.ab, self.dat, self.per] if p]
            new_name = "_".join(parts) + ".pdf"
            base, ext = os.path.splitext(new_name)
            dest = os.path.join(ARCHIV_DIR, new_name)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(ARCHIV_DIR, f"{base}_{counter}{ext}")
                counter += 1
            shutil.move(self.pdf_path, dest)
            self.finished.emit(dest)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# XMP helper (module-level, called from ConfirmWorker thread)
# ---------------------------------------------------------------------------

def _vdate_to_iso(vdate: str) -> str:
    m = re.match(r"v(\d{2})\.(\d{2})\.(\d{2})$", vdate)
    if m:
        d, mo, y = m.group(1), m.group(2), int(m.group(3))
        year = 2000 + y
        return f"{year:04d}-{mo}-{d}"
    return vdate


def _write_xmp(pdf_path: str, typ: str, ab: str, dat: str, per: str) -> None:
    tmp_path = pdf_path + ".tmp.pdf"
    try:
        with pikepdf.open(pdf_path) as pdf:
            with pdf.open_metadata() as meta:
                meta["dc:description"] = f"{typ} von {ab}"
                meta["dc:subject"] = [x for x in [typ, ab, per] if x]
                if dat:
                    meta["xmp:CreateDate"] = _vdate_to_iso(dat)
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
    status_message = pyqtSignal(str)

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

        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            _select_on_focus(cb)

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

        self.status_message.emit("Analysiere Dokument …")
        self._analyze_worker = AnalyzeWorker(path)
        self._analyze_worker.finished.connect(self._on_analysis_done)
        self._analyze_worker.error.connect(self._on_analysis_error)
        self._analyze_worker.start()

    def _clear_fields(self):
        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.clear()
        self.lbl_preview.setText("—")

    def _populate_combos(self):
        self.cb_typ.addItems([""] + database.load_dokumenttypen())
        self.cb_absender.addItems([""] + database.load_absender())
        self.cb_person.addItems([""] + database.get_persons())

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
        self.status_message.emit("Analyse abgeschlossen – Felder prüfen und bestätigen")

    def _on_analysis_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.status_message.emit("Analyse fehlgeschlagen")
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

        self.status_message.emit("Schreibe Metadaten & archiviere …")
        self._confirm_worker = ConfirmWorker(self.pdf_path, typ, ab, dat, per)
        self._confirm_worker.finished.connect(self._on_confirm_done)
        self._confirm_worker.error.connect(self._on_confirm_error)
        self._confirm_worker.start()

    def _on_confirm_done(self, dest: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        new_name = os.path.basename(dest)
        self.status_message.emit(f"Archiviert: {new_name}")
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
        self.status_message.emit("Archivierung fehlgeschlagen")
        QMessageBox.critical(self, "Fehler", f"Archivierung fehlgeschlagen:\n{msg}")


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------

def _make_single_table(header: str) -> QTableWidget:
    t = QTableWidget(0, 1)
    t.setHorizontalHeaderLabels([header])
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return t


def _table_values(table: QTableWidget, col: int = 0) -> list[str]:
    result = []
    for row in range(table.rowCount()):
        v = (table.item(row, col) or QTableWidgetItem("")).text().strip()
        if v:
            result.append(v)
    return result


def _fill_single(table: QTableWidget, items: list[str]) -> None:
    table.setRowCount(len(items))
    for row, v in enumerate(items):
        table.setItem(row, 0, QTableWidgetItem(v))


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Top row: Dokumenttypen | Absender | Personen ──────────────────
        top = QHBoxLayout()

        self.tbl_typen = _make_single_table("Dokumenttyp")
        grp_t = self._grp("Dokumenttypen", self.tbl_typen,
                          self._add_typ, self._del_typ, self._save_typen)
        top.addWidget(grp_t)

        self.tbl_abs = _make_single_table("Absender")
        grp_a = self._grp("Absender", self.tbl_abs,
                          self._add_abs, self._del_abs, self._save_abs)
        top.addWidget(grp_a)

        self.tbl_pers = _make_single_table("Nachname")
        grp_p = self._grp("Personen", self.tbl_pers,
                          self._add_pers, self._del_pers, self._save_pers)
        top.addWidget(grp_p)
        root.addLayout(top)

        # ── Bottom: KI-Kontext (Kombinationen) ────────────────────────────
        grp_k = QGroupBox("KI-Kontext – historische Kombinationen")
        vk = QVBoxLayout(grp_k)

        self.tbl_kombi = QTableWidget(0, 2)
        self.tbl_kombi.setHorizontalHeaderLabels(["Dokumenttyp", "Absender"])
        self.tbl_kombi.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_kombi.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        vk.addWidget(self.tbl_kombi)

        bar_k = QHBoxLayout()
        btn_k_add = QPushButton("Hinzufügen")
        btn_k_del = QPushButton("Löschen")
        btn_k_save = QPushButton("Speichern")
        btn_k_add.clicked.connect(self._add_kombi)
        btn_k_del.clicked.connect(self._del_kombi)
        btn_k_save.clicked.connect(self._save_kombi)
        bar_k.addWidget(btn_k_add)
        bar_k.addWidget(btn_k_del)
        bar_k.addWidget(btn_k_save)
        vk.addLayout(bar_k)
        root.addWidget(grp_k)

    @staticmethod
    def _grp(title: str, table: QTableWidget, fn_add, fn_del, fn_save) -> QGroupBox:
        grp = QGroupBox(title)
        v = QVBoxLayout(grp)
        v.addWidget(table)
        bar = QHBoxLayout()
        for label, fn in [("＋", fn_add), ("－", fn_del), ("✓ Speichern", fn_save)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            bar.addWidget(b)
        v.addLayout(bar)
        return grp

    def refresh(self):
        _fill_single(self.tbl_typen, database.load_dokumenttypen())
        _fill_single(self.tbl_abs,   database.load_absender())
        _fill_single(self.tbl_pers,  database.get_persons())

        kombi = database.load()
        self.tbl_kombi.setRowCount(len(kombi))
        for row, e in enumerate(kombi):
            self.tbl_kombi.setItem(row, 0, QTableWidgetItem(e.get("dokumenttyp", "")))
            self.tbl_kombi.setItem(row, 1, QTableWidgetItem(e.get("absender", "")))

    # Dokumenttypen
    def _add_typ(self):
        r = self.tbl_typen.rowCount(); self.tbl_typen.insertRow(r)
        self.tbl_typen.setItem(r, 0, QTableWidgetItem(""))
    def _del_typ(self):
        for r in sorted({i.row() for i in self.tbl_typen.selectedIndexes()}, reverse=True):
            self.tbl_typen.removeRow(r)
    def _save_typen(self):
        database.save_dokumenttypen(sorted(_table_values(self.tbl_typen)))
        QMessageBox.information(self, "Gespeichert", "Dokumenttypen gespeichert.")

    # Absender
    def _add_abs(self):
        r = self.tbl_abs.rowCount(); self.tbl_abs.insertRow(r)
        self.tbl_abs.setItem(r, 0, QTableWidgetItem(""))
    def _del_abs(self):
        for r in sorted({i.row() for i in self.tbl_abs.selectedIndexes()}, reverse=True):
            self.tbl_abs.removeRow(r)
    def _save_abs(self):
        database.save_absender(sorted(_table_values(self.tbl_abs)))
        QMessageBox.information(self, "Gespeichert", "Absender gespeichert.")

    # Personen
    def _add_pers(self):
        r = self.tbl_pers.rowCount(); self.tbl_pers.insertRow(r)
        self.tbl_pers.setItem(r, 0, QTableWidgetItem(""))
    def _del_pers(self):
        for r in sorted({i.row() for i in self.tbl_pers.selectedIndexes()}, reverse=True):
            self.tbl_pers.removeRow(r)
    def _save_pers(self):
        database.save_persons(sorted(_table_values(self.tbl_pers)))
        QMessageBox.information(self, "Gespeichert", "Personen gespeichert.")

    # KI-Kombinationen
    def _add_kombi(self):
        r = self.tbl_kombi.rowCount(); self.tbl_kombi.insertRow(r)
        self.tbl_kombi.setItem(r, 0, QTableWidgetItem(""))
        self.tbl_kombi.setItem(r, 1, QTableWidgetItem(""))
    def _del_kombi(self):
        for r in sorted({i.row() for i in self.tbl_kombi.selectedIndexes()}, reverse=True):
            self.tbl_kombi.removeRow(r)
    def _save_kombi(self):
        entries = []
        for r in range(self.tbl_kombi.rowCount()):
            entries.append({
                "dokumenttyp": (self.tbl_kombi.item(r, 0) or QTableWidgetItem("")).text().strip(),
                "absender":    (self.tbl_kombi.item(r, 1) or QTableWidgetItem("")).text().strip(),
            })
        database.save(entries)
        QMessageBox.information(self, "Gespeichert", "KI-Kontext gespeichert.")


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

        self.main_tab.settings_refresh_requested.connect(self.settings_tab.refresh)

        tabs.addTab(self.main_tab, "Dokument")
        tabs.addTab(self.settings_tab, "Stammdaten")
        self.setCentralWidget(tabs)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage("PostScan bereit")
        self.setStatusBar(self._status_bar)
        self.main_tab.status_message.connect(self._status_bar.showMessage)


def main():
    database.ensure_defaults()
    os.makedirs(EINGANG_DIR, exist_ok=True)
    os.makedirs(ARCHIV_DIR, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName("PostScan")

    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
