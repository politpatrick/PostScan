import os
import re
import shutil
import sys
from datetime import date as _today_date

import pikepdf
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QMessageBox, QProgressBar, QFrame, QGridLayout, QStatusBar,
    QGroupBox, QTextEdit, QSplitter, QLineEdit, QCompleter,
)

import database
import pipeline

EINGANG_DIR = os.path.join(os.path.dirname(__file__), "eingang")


_MONTH_NAMES = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
    "jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12,
}


def _normalize_date(text: str) -> str:
    """Normalize various date inputs to DD.MM.YY. Returns original on failure."""
    text = text.strip().rstrip(".")
    if not text:
        return text
    if re.match(r'^\d{2}\.\d{2}\.\d{2}$', text):
        return text

    current_yy = _today_date.today().year % 100
    d = m = y = None

    # Split on all common separators including hyphen
    parts = [p.strip(".") for p in re.split(r'[\s.,/\-]+', text) if p.strip(".")]

    if len(parts) >= 2:
        # ISO order: YYYY-MM-DD — first part is a 4-digit year
        if len(parts[0]) == 4 and parts[0].isdigit() and 1900 <= int(parts[0]) <= 2100:
            try:
                y = int(parts[0]) % 100
                m = int(parts[1])
                d = int(parts[2]) if len(parts) >= 3 else 1
            except (ValueError, IndexError):
                pass
        else:
            try:
                d = int(parts[0])
                # Month: number or German name (full or abbreviated)
                m_raw = parts[1].lower()
                if m_raw in _MONTH_NAMES:
                    m = _MONTH_NAMES[m_raw]
                else:
                    m = int(parts[1])
                y = int(parts[2]) % 100 if len(parts) >= 3 else current_yy
            except (ValueError, IndexError):
                pass

    # Pure digit string
    if d is None:
        digits = re.sub(r'\D', '', text)
        today = _today_date.today()
        cur_m, cur_yy = today.month, today.year % 100

        if len(digits) == 2:                  # DD → current month + year
            d, m, y = int(digits), cur_m, cur_yy
        elif len(digits) == 3:                # DDM or DMM → current year
            d1, m1 = int(digits[0:2]), int(digits[2])
            d2, m2 = int(digits[0]),   int(digits[1:3])
            if 1 <= d1 <= 31 and 1 <= m1 <= 12:
                d, m, y = d1, m1, cur_yy
            elif 1 <= d2 <= 31 and 1 <= m2 <= 12:
                d, m, y = d2, m2, cur_yy
        elif len(digits) == 4:
            # Priority: DDMM (2+2) → DMYY (1+1+2) → MMDD (2+2)
            d1, m1 = int(digits[0:2]), int(digits[2:4])   # DDMM
            d2, m2, y2 = int(digits[0]), int(digits[1]), int(digits[2:4])  # DMYY
            d3, m3 = int(digits[2:4]), int(digits[0:2])   # MMDD
            if 1 <= d1 <= 31 and 1 <= m1 <= 12:
                d, m, y = d1, m1, cur_yy
            elif 1 <= d2 <= 31 and 1 <= m2 <= 12:
                d, m, y = d2, m2, y2
            elif 1 <= d3 <= 31 and 1 <= m3 <= 12:
                d, m, y = d3, m3, cur_yy
        elif len(digits) == 6:
            d, m, y = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
        elif len(digits) == 8:
            first4 = int(digits[0:4])
            if 1900 <= first4 <= 2100:        # YYYYMMDD
                y, m, d = first4 % 100, int(digits[4:6]), int(digits[6:8])
            else:                              # DDMMYYYY
                d, m, y = int(digits[0:2]), int(digits[2:4]), int(digits[6:8])

    if d is not None and m is not None and y is not None:
        if 1 <= d <= 31 and 1 <= m <= 12 and 0 <= y <= 99:
            return f"{d:02d}.{m:02d}.{y:02d}"

    return text
ARCHIV_DIR = os.path.join(os.path.dirname(__file__), "archiv")


class _NameAbkCompleter(QCompleter):
    """Completer for name+abbreviation lists. Matches on name OR abk, inserts name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src = QStandardItemModel(self)
        self.setModel(self._src)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterMode(Qt.MatchFlag.MatchContains)

    def set_items(self, items):
        self._src.clear()
        for a in items:
            name    = a["name"]
            abk     = a.get("abk", "").strip()
            syns    = [s.strip() for s in a.get("synonyme", []) if s.strip()]
            aliases = ([abk] if abk else []) + syns
            display = f"{name} ({', '.join(aliases)})" if aliases else name
            item = QStandardItem(display)
            item.setData(name, Qt.ItemDataRole.UserRole)
            self._src.appendRow(item)

    def pathFromIndex(self, index):
        return index.data(Qt.ItemDataRole.UserRole) or ""

    def splitPath(self, path):
        return [path]


class _SelectAllLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._first_click = False

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._first_click = True

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._first_click:
            self._first_click = False
            self.selectAll()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._first_click = False


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

            # b) XMP metadata (dat without v-prefix → add it back here)
            dat_v = f"v{self.dat}" if self.dat and not self.dat.startswith("v") else self.dat
            _write_xmp(self.pdf_path, self.typ, self.ab, dat_v, self.per)

            # c) Move & rename (use abbreviation for typ/absender if set)
            os.makedirs(ARCHIV_DIR, exist_ok=True)
            typ_display = database.get_dokumenttyp_display(self.typ)
            ab_display  = database.get_absender_display(self.ab)
            parts = [p for p in [typ_display, ab_display, dat_v, self.per] if p]
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

        # Splitter: fields (top) + OCR text (bottom, collapsible)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Top widget: fields + preview + confirm ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # Source/confidence info
        self.lbl_source = QLabel("")
        self.lbl_source.setAlignment(Qt.AlignmentFlag.AlignRight)
        font = self.lbl_source.font()
        font.setPointSize(9)
        self.lbl_source.setFont(font)
        top_layout.addWidget(self.lbl_source)

        # Extraction fields
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        def _combo() -> QComboBox:
            c = QComboBox()
            c.setEditable(True)
            c.setLineEdit(_SelectAllLineEdit())
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return c

        self.cb_typ = _combo()
        self.cb_absender = _combo()
        self.cb_datum = _combo()
        self.cb_person = _combo()

        self._typ_completer = _NameAbkCompleter(self.cb_typ)
        self.cb_typ.lineEdit().setCompleter(self._typ_completer)

        self._absender_completer = _NameAbkCompleter(self.cb_absender)
        self.cb_absender.lineEdit().setCompleter(self._absender_completer)

        for row, (lbl, widget) in enumerate([
            ("Dokumenttyp:", self.cb_typ),
            ("Absender:", self.cb_absender),
            ("Dokumentdatum:", self.cb_datum),
            ("Personenbezug:", self.cb_person),
        ]):
            grid.addWidget(QLabel(lbl), row, 0)
            grid.addWidget(widget, row, 1)

        top_layout.addLayout(grid)

        # Filename preview
        self.lbl_preview = QLabel("—")
        self.lbl_preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setWordWrap(True)
        font2 = self.lbl_preview.font()
        font2.setPointSize(11)
        self.lbl_preview.setFont(font2)
        top_layout.addWidget(self.lbl_preview)

        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.currentTextChanged.connect(self._update_preview)

        self.cb_datum.lineEdit().editingFinished.connect(self._auto_format_datum)
        self.cb_datum.lineEdit().returnPressed.connect(self._auto_format_datum)

        # Confirm button
        self.btn_confirm = QPushButton("Bestätigen & Archivieren")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._confirm)
        top_layout.addWidget(self.btn_confirm)

        splitter.addWidget(top_widget)

        # --- Bottom widget: OCR raw text ---
        ocr_group = QGroupBox("Debug – Extrahierter Text & Klassifikation")
        ocr_layout = QVBoxLayout(ocr_group)
        self.txt_ocr = QTextEdit()
        self.txt_ocr.setReadOnly(True)
        self.txt_ocr.setPlaceholderText("Nach der Analyse wird hier der erkannte Rohtext angezeigt …")
        font3 = self.txt_ocr.font()
        font3.setPointSize(10)
        self.txt_ocr.setFont(font3)
        ocr_layout.addWidget(self.txt_ocr)
        splitter.addWidget(ocr_group)

        splitter.setSizes([320, 200])
        root.addWidget(splitter)

    # ------------------------------------------------------------------

    def _open_pdf(self):
        os.makedirs(EINGANG_DIR, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF öffnen", EINGANG_DIR, "PDF-Dateien (*.pdf)"
        )
        if not path:
            return
        self.load_pdf(path)

    def load_pdf(self, path: str):
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
        self.txt_ocr.clear()

    def _populate_combos(self):
        self.cb_person.addItems([""] + database.get_persons())

        typen = database.load_dokumenttypen()
        self.cb_typ.addItems([""] + [t["name"] for t in typen])
        self._typ_completer.set_items(typen)
        self.cb_typ.lineEdit().setCompleter(self._typ_completer)

        absender = database.load_absender()
        self.cb_absender.addItems([""] + [a["name"] for a in absender])
        self._absender_completer.set_items(absender)
        self.cb_absender.lineEdit().setCompleter(self._absender_completer)

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

        def _strip_v(d):
            return d[1:] if d.startswith("v") else d

        candidates = result.get("dokumentdatum_candidates", [])
        self.cb_datum.clear()
        if candidates:
            self.cb_datum.addItems([_strip_v(c) for c in candidates])
            self.cb_datum.setCurrentIndex(0)
        else:
            self.cb_datum.setCurrentText(_strip_v(result.get("dokumentdatum", "")))

        debug_lines = []
        tfidf_match = result.get("tfidf_match", "")
        if tfidf_match:
            debug_lines.append(f"[TF-IDF] Bester Treffer: \"{tfidf_match}\" - Konfidenz: {result.get('confidence', 0):.0%}")
        llm_raw = result.get("llm_raw", "")
        if llm_raw:
            debug_lines.append(f"[LLM] Rohantwort: {llm_raw.strip()}")
        if debug_lines:
            debug_lines.append("")
        debug_lines.append(result.get("ocr_text", ""))
        self.txt_ocr.setPlainText("\n".join(debug_lines))
        self.btn_confirm.setEnabled(True)
        self._update_preview()
        self.status_message.emit("Analyse abgeschlossen – Felder prüfen und bestätigen")

    def _on_analysis_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.status_message.emit("Analyse fehlgeschlagen")
        QMessageBox.critical(self, "Fehler", f"Analyse fehlgeschlagen:\n{msg}")

    def _auto_format_datum(self):
        raw = self.cb_datum.currentText()
        normalized = _normalize_date(raw)
        if normalized != raw:
            self.cb_datum.setCurrentText(normalized)

    def _update_preview(self):
        typ  = database.get_dokumenttyp_display(self.cb_typ.currentText().strip())
        ab   = database.get_absender_display(self.cb_absender.currentText().strip())
        dat  = self.cb_datum.currentText().strip()
        dat  = f"v{dat}" if dat and not dat.startswith("v") else dat
        per  = self.cb_person.currentText().strip()
        parts = [p for p in [typ, ab, dat, per] if p]
        self.lbl_preview.setText("_".join(parts) + ".pdf" if parts else "—")

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

        dat = _normalize_date(dat)
        self.cb_datum.setCurrentText(dat)

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

        self.tbl_typen = QTableWidget(0, 3)
        self.tbl_typen.setHorizontalHeaderLabels(["Name", "Abk.", "Synonyme (kommagetrennt)"])
        self.tbl_typen.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_typen.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_typen.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_typen.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        grp_t = self._grp("Dokumenttypen", self.tbl_typen,
                          self._add_typ, self._del_typ, self._save_typen)
        top.addWidget(grp_t)

        self.tbl_abs = QTableWidget(0, 3)
        self.tbl_abs.setHorizontalHeaderLabels(["Name", "Abk.", "Synonyme (kommagetrennt)"])
        self.tbl_abs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_abs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_abs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_abs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
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
        _fill_single(self.tbl_pers, database.get_persons())

        typen = database.load_dokumenttypen()
        self.tbl_typen.setRowCount(len(typen))
        for row, t in enumerate(typen):
            self.tbl_typen.setItem(row, 0, QTableWidgetItem(t.get("name", "")))
            self.tbl_typen.setItem(row, 1, QTableWidgetItem(t.get("abk", "")))
            self.tbl_typen.setItem(row, 2, QTableWidgetItem(", ".join(t.get("synonyme", []))))

        absender = database.load_absender()
        self.tbl_abs.setRowCount(len(absender))
        for row, a in enumerate(absender):
            self.tbl_abs.setItem(row, 0, QTableWidgetItem(a.get("name", "")))
            self.tbl_abs.setItem(row, 1, QTableWidgetItem(a.get("abk", "")))
            self.tbl_abs.setItem(row, 2, QTableWidgetItem(", ".join(a.get("synonyme", []))))

        kombi = database.load()
        self.tbl_kombi.setRowCount(len(kombi))
        for row, e in enumerate(kombi):
            self.tbl_kombi.setItem(row, 0, QTableWidgetItem(e.get("dokumenttyp", "")))
            self.tbl_kombi.setItem(row, 1, QTableWidgetItem(e.get("absender", "")))

    # Dokumenttypen
    def _add_typ(self):
        r = self.tbl_typen.rowCount(); self.tbl_typen.insertRow(r)
        self.tbl_typen.setItem(r, 0, QTableWidgetItem(""))
        self.tbl_typen.setItem(r, 1, QTableWidgetItem(""))
        self.tbl_typen.setItem(r, 2, QTableWidgetItem(""))
    def _del_typ(self):
        for r in sorted({i.row() for i in self.tbl_typen.selectedIndexes()}, reverse=True):
            self.tbl_typen.removeRow(r)
    def _save_typen(self):
        entries = []
        for r in range(self.tbl_typen.rowCount()):
            name = (self.tbl_typen.item(r, 0) or QTableWidgetItem("")).text().strip()
            abk  = (self.tbl_typen.item(r, 1) or QTableWidgetItem("")).text().strip()
            syns = (self.tbl_typen.item(r, 2) or QTableWidgetItem("")).text().strip()
            if name:
                synonyme = [s.strip() for s in syns.split(",") if s.strip()]
                entries.append({"name": name, "abk": abk, "synonyme": synonyme})
        database.save_dokumenttypen(sorted(entries, key=lambda t: t["name"]))
        QMessageBox.information(self, "Gespeichert", "Dokumenttypen gespeichert.")

    # Absender
    def _add_abs(self):
        r = self.tbl_abs.rowCount(); self.tbl_abs.insertRow(r)
        self.tbl_abs.setItem(r, 0, QTableWidgetItem(""))
        self.tbl_abs.setItem(r, 1, QTableWidgetItem(""))
        self.tbl_abs.setItem(r, 2, QTableWidgetItem(""))
    def _del_abs(self):
        for r in sorted({i.row() for i in self.tbl_abs.selectedIndexes()}, reverse=True):
            self.tbl_abs.removeRow(r)
    def _save_abs(self):
        entries = []
        for r in range(self.tbl_abs.rowCount()):
            name = (self.tbl_abs.item(r, 0) or QTableWidgetItem("")).text().strip()
            abk  = (self.tbl_abs.item(r, 1) or QTableWidgetItem("")).text().strip()
            syns = (self.tbl_abs.item(r, 2) or QTableWidgetItem("")).text().strip()
            if name:
                synonyme = [s.strip() for s in syns.split(",") if s.strip()]
                entries.append({"name": name, "abk": abk, "synonyme": synonyme})
        database.save_absender(sorted(entries, key=lambda a: a["name"]))
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
        self.setAcceptDrops(True)

        tabs = QTabWidget()
        self.main_tab = MainTab()
        self.settings_tab = SettingsTab()

        self.main_tab.settings_refresh_requested.connect(self.settings_tab.refresh)

        tabs.addTab(self.main_tab, "Dokument")
        tabs.addTab(self.settings_tab, "Stammdaten")
        self.setCentralWidget(tabs)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage("PostScan bereit – PDF hier ablegen oder \"PDF öffnen\" klicken")
        self.setStatusBar(self._status_bar)
        self.main_tab.status_message.connect(self._status_bar.showMessage)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith(".pdf") for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.main_tab.load_pdf(path)
                break


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
        # macOS: set dock icon via AppKit
        try:
            from AppKit import NSApplication, NSImage
            ns_image = NSImage.alloc().initByReferencingFile_(icon_path)
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
        except Exception:
            pass

    window = MainWindow()
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
