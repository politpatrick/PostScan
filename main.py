import os
import re
import shutil
import subprocess
import sys
from datetime import date as _today_date

import requests

import pikepdf

_MACOS = sys.platform == "darwin"
if _MACOS:
    import plistlib
    import xattr
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QStringListModel, QUrl
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem, QColor
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QMessageBox, QProgressBar, QFrame, QGridLayout, QStatusBar,
    QGroupBox, QTextEdit, QSplitter, QLineEdit, QCompleter,
    QListWidget, QListWidgetItem, QRadioButton, QButtonGroup,
    QDialog, QDialogButtonBox,
)

import config as app_config
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

        if len(digits) == 1:                  # D → current month + year
            d, m, y = int(digits), cur_m, cur_yy
        elif len(digits) == 2:                # DD → current month + year
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
        elif len(digits) == 5:
            d1, m1, y1 = int(digits[0]),   int(digits[1:3]), int(digits[3:5])  # DMMYY
            d2, m2, y2 = int(digits[0:2]), int(digits[2]),   int(digits[3:5])  # DDMYY
            dmmyy_ok = 1 <= d1 <= 31 and 1 <= m1 <= 12
            ddmyy_ok = 1 <= d2 <= 31 and 1 <= m2 <= 12
            # DDMYY wins when unambiguous:
            # - d2 > 12: first two digits can't be a month
            # - digits[1]=='0': DMMYY would need a leading zero in month (e.g. "05"),
            #   which the user never types without separators
            if ddmyy_ok and (d2 > 12 or digits[1] == '0'):
                d, m, y = d2, m2, y2
            elif dmmyy_ok:
                d, m, y = d1, m1, y1
            elif ddmyy_ok:
                d, m, y = d2, m2, y2
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


def _normalize_date_options(text: str) -> list[str]:
    """Returns all valid interpretations of a date input, primary first.
    For unambiguous input returns a 1-item list. For genuinely ambiguous
    5-digit inputs (e.g. '11125' = 01.11.25 or 11.01.25) returns both."""
    digits = re.sub(r'\D', '', text.strip().rstrip("."))
    if len(digits) == 5:
        d1, m1, y1 = int(digits[0]),   int(digits[1:3]), int(digits[3:5])
        d2, m2, y2 = int(digits[0:2]), int(digits[2]),   int(digits[3:5])
        dmmyy_ok = 1 <= d1 <= 31 and 1 <= m1 <= 12
        ddmyy_ok = 1 <= d2 <= 31 and 1 <= m2 <= 12
        if dmmyy_ok and ddmyy_ok and d2 <= 12 and digits[1] != '0':
            opt_a = f"{d1:02d}.{m1:02d}.{y1:02d}"  # DMMYY
            opt_b = f"{d2:02d}.{m2:02d}.{y2:02d}"  # DDMYY
            if opt_a != opt_b:
                return [opt_a, opt_b]
    primary = _normalize_date(text)
    return [primary] if primary else [text]



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
            name = a["name"]
            abk  = a.get("abk", "").strip()
            syns = [s.strip() for s in a.get("synonyme", []) if s.strip()]
            if abk and syns:
                display = f"{name} ({abk}: {', '.join(syns)})"
            elif abk:
                display = f"{name} ({abk})"
            elif syns:
                display = f"{name} ({', '.join(syns)})"
            else:
                display = name
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
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self):
        try:
            self.result_ready.emit(pipeline.analyze(self.pdf_path))
        except Exception as e:
            self.error.emit(str(e))


class ConfirmWorker(QThread):
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str, typ: str, ab: str, dat: str, per: str, zusatz: str = "", prefix: str = ""):
        super().__init__()
        self.pdf_path = pdf_path
        self.typ = typ
        self.ab = ab
        self.dat = dat
        self.per = per
        self.zusatz = zusatz
        self.prefix = prefix

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
            _write_xmp(self.pdf_path, self.typ, self.ab, dat_v, self.per, self.zusatz)

            # c) Rename in-place (keep file at its original location)
            typ_display = database.get_dokumenttyp_display(self.typ)
            ab_display  = database.get_absender_display(self.ab)
            if self.prefix == "an":
                ordered = [self.prefix, ab_display, typ_display, self.zusatz, dat_v, self.per]
            else:
                ordered = [self.prefix, typ_display, self.zusatz, ab_display, dat_v, self.per]
            parts = [p.replace(" ", "_") for p in ordered if p]
            new_name = "_".join(parts) + ".pdf"
            base, ext = os.path.splitext(new_name)
            orig_dir = os.path.dirname(self.pdf_path)
            dest = os.path.join(orig_dir, new_name)
            counter = 1
            while os.path.exists(dest) and dest != self.pdf_path:
                dest = os.path.join(orig_dir, f"{base}_{counter}{ext}")
                counter += 1
            if dest != self.pdf_path:
                os.rename(self.pdf_path, dest)
            tags = [t for t in [self.typ, self.ab, self.per] if t]
            if tags:
                _set_file_tags(dest, tags)
            self.result_ready.emit(dest)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Ollama workers
# ---------------------------------------------------------------------------

class OllamaCheckWorker(QThread):
    result = pyqtSignal(dict)

    def __init__(self, model: str = ""):
        super().__init__()
        self.model = model or app_config.get_ollama_model()

    def run(self):
        installed = shutil.which("ollama") is not None
        running = False
        model_ok = False
        if installed:
            try:
                resp = requests.get("http://localhost:11434/api/tags", timeout=3)
                if resp.ok:
                    running = True
                    models = resp.json().get("models", [])
                    model_ok = any(
                        self.model in m.get("name", "") for m in models
                    )
            except Exception:
                pass
        self.result.emit({"installed": installed, "running": running, "model": model_ok})


class OllamaPullWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool)

    def __init__(self, model: str = ""):
        super().__init__()
        self.model = model or app_config.get_ollama_model()

    def run(self):
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", self.model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            out, _ = proc.communicate()
            for line in out.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    self.progress.emit(line)
            self.done.emit(proc.returncode == 0)
        except Exception as e:
            self.progress.emit(f"Fehler: {e}")
            self.done.emit(False)


class GoogleTestWorker(QThread):
    result = pyqtSignal(bool, str)   # (success, message)

    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    def run(self):
        try:
            from google import genai
            from google.genai import types as genai_types
            client = genai.Client(api_key=self.api_key)
            client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents="Antworte mit: OK",
                config=genai_types.GenerateContentConfig(max_output_tokens=10),
            )
            self.result.emit(True, "Verbindung erfolgreich – API-Schlüssel ist gültig.")
        except ImportError:
            self.result.emit(False, "Paket nicht installiert: pip install google-genai")
        except Exception as e:
            self.result.emit(False, f"Fehler: {e}")


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


def _write_xmp(pdf_path: str, typ: str, ab: str, dat: str, per: str, zusatz: str = "") -> None:
    tmp_path = pdf_path + ".tmp.pdf"
    try:
        with pikepdf.open(pdf_path) as pdf:
            with pdf.open_metadata() as meta:
                for key in ["dc:title", "dc:creator", "dc:subject", "dc:date",
                            "dc:description", "dc:publisher", "pdf:Keywords", "xmp:CreateDate"]:
                    try:
                        del meta[key]
                    except KeyError:
                        pass
                meta["dc:title"] = typ
                meta["dc:creator"] = [ab] if ab else []
                if per:
                    meta["dc:subject"] = [per]
                    meta["dc:publisher"] = [per]
                if zusatz:
                    meta["dc:description"] = zusatz
                meta["pdf:Keywords"] = ", ".join(x for x in [typ, ab, per] if x)
                if dat:
                    iso = _vdate_to_iso(dat)
                    meta["dc:date"] = [iso]
                    meta["xmp:CreateDate"] = iso
            pdf.save(tmp_path)
        os.replace(tmp_path, pdf_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _set_macos_tags(path: str, tags: list[str]) -> None:
    if not _MACOS:
        return
    plist_bytes = plistlib.dumps(tags, fmt=plistlib.FMT_BINARY)
    xattr.setxattr(path, "com.apple.metadata:_kMDItemUserTags", plist_bytes)


def _set_windows_tags(path: str, tags: list[str]) -> None:
    if sys.platform != "win32":
        return
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        store = propsys.SHGetPropertyStoreFromParsingName(
            os.path.abspath(path), None, 2  # GPS_READWRITE
        )
        pv = propsys.PROPVARIANTType(tags, pythoncom.VT_VECTOR | pythoncom.VT_BSTR)
        store.SetValue(pscon.PKEY_Keywords, pv)
        store.Commit()
    except Exception as e:
        print(f"[Windows Tags] Fehler: {e}", flush=True)


def _set_file_tags(path: str, tags: list[str]) -> None:
    _set_macos_tags(path, tags)
    _set_windows_tags(path, tags)


# ---------------------------------------------------------------------------
# Inline-Edit Dialog for Abkürzung / Synonyme
# ---------------------------------------------------------------------------

class _EditStammdatenDialog(QDialog):
    def __init__(self, kind: str, name: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.name = name
        self.setWindowTitle(f"{'Dokumenttyp' if kind == 'typ' else 'Absender'} bearbeiten")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QGridLayout()

        form.addWidget(QLabel("Name:"), 0, 0)
        lbl_name = QLabel(name)
        lbl_name.setStyleSheet("font-weight: bold;")
        form.addWidget(lbl_name, 0, 1)

        form.addWidget(QLabel("Abkürzung:"), 1, 0)
        self.le_abk = QLineEdit()
        form.addWidget(self.le_abk, 1, 1)

        form.addWidget(QLabel("Synonyme:"), 2, 0)
        self.le_syn = QLineEdit()
        self.le_syn.setPlaceholderText("kommagetrennt, z.B. AOK, AOK Bayern")
        form.addWidget(self.le_syn, 2, 1)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._load(kind, name)

    def _load(self, kind: str, name: str):
        if kind == "typ":
            items = database.load_dokumenttypen()
        else:
            items = database.load_absender()
        for item in items:
            if item["name"] == name:
                self.le_abk.setText(item.get("abk", ""))
                self.le_syn.setText(", ".join(item.get("synonyme", [])))
                return

    def save(self):
        abk  = self.le_abk.text().strip()
        syns = [s.strip() for s in self.le_syn.text().split(",") if s.strip()]
        if self.kind == "typ":
            items = database.load_dokumenttypen()
            for item in items:
                if item["name"] == self.name:
                    item["abk"] = abk
                    item["synonyme"] = syns
            database.save_dokumenttypen(items)
        else:
            items = database.load_absender()
            for item in items:
                if item["name"] == self.name:
                    item["abk"] = abk
                    item["synonyme"] = syns
            database.save_absender(items)


# ---------------------------------------------------------------------------
# Drop zone widget
# ---------------------------------------------------------------------------

class DropZone(QFrame):
    files_dropped = pyqtSignal(list)

    _STYLE_IDLE = (
        "DropZone { border: 2px dashed #aaa; border-radius: 8px; "
        "background: #f7f7f7; }"
    )
    _STYLE_HOVER = (
        "DropZone { border: 2px dashed #007aff; border-radius: 8px; "
        "background: #e8f0ff; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(self._STYLE_IDLE)
        lbl = QLabel("PDFs hier ablegen")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        font = lbl.font()
        font.setPointSize(11)
        lbl.setFont(font)
        lay = QVBoxLayout(self)
        lay.addWidget(lbl)

    def _pdfs(self, event) -> list[str]:
        return [
            u.toLocalFile() for u in event.mimeData().urls()
            if u.toLocalFile().lower().endswith(".pdf")
        ]

    def dragEnterEvent(self, event):
        if self._pdfs(event):
            self.setStyleSheet(self._STYLE_HOVER)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._STYLE_IDLE)

    def dropEvent(self, event):
        self.setStyleSheet(self._STYLE_IDLE)
        pdfs = self._pdfs(event)
        if pdfs:
            self.files_dropped.emit(pdfs)
            event.acceptProposedAction()


# ---------------------------------------------------------------------------
# Main document tab
# ---------------------------------------------------------------------------

class MainTab(QWidget):
    settings_refresh_requested = pyqtSignal()
    status_message = pyqtSignal(str)
    confirmed = pyqtSignal(str)   # emits original pdf_path before clearing
    result_ready = pyqtSignal(str, dict)  # emits (pdf_path, result) after analysis
    pdf_opened = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_path: str = ""
        self._analyze_worker: AnalyzeWorker | None = None
        self._confirm_worker: ConfirmWorker | None = None
        self._prefix: str = ""
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
        self.le_zusatz = _SelectAllLineEdit()

        self._typ_completer = _NameAbkCompleter(self.cb_typ)
        self.cb_typ.lineEdit().setCompleter(self._typ_completer)

        self._absender_completer = _NameAbkCompleter(self.cb_absender)
        self.cb_absender.lineEdit().setCompleter(self._absender_completer)

        self._person_completer = QCompleter(self.cb_person)
        self._person_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._person_completer.setModelSorting(QCompleter.ModelSorting.CaseInsensitivelySortedModel)
        self._person_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._person_completer.activated.connect(
            lambda text: self.cb_person.lineEdit().setText(text)
        )
        self.cb_person.lineEdit().setCompleter(self._person_completer)

        def _edit_btn(kind: str) -> QPushButton:
            b = QPushButton("✏")
            b.setFixedWidth(28)
            b.setToolTip(f"{kind} bearbeiten (Abkürzung / Synonyme)")
            b.clicked.connect(lambda: self._open_edit_dialog(kind))
            return b

        self._btn_edit_typ = _edit_btn("typ")
        self._btn_edit_ab  = _edit_btn("absender")

        for row, (lbl, widget, extra) in enumerate([
            ("Dokumenttyp:",        self.cb_typ,      self._btn_edit_typ),
            ("Zusatzinformationen:", self.le_zusatz,   None),
            ("Absender:",           self.cb_absender,  self._btn_edit_ab),
            ("Dokumentdatum:",      self.cb_datum,     None),
            ("Personenbezug:",      self.cb_person,    None),
        ]):
            grid.addWidget(QLabel(lbl), row, 0)
            if extra:
                row_w = QWidget()
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 0, 0, 0)
                row_l.addWidget(widget)
                row_l.addWidget(extra)
                grid.addWidget(row_w, row, 1)
            else:
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
        self.le_zusatz.textChanged.connect(self._update_preview)

        self.cb_datum.lineEdit().editingFinished.connect(self._auto_format_datum)
        self.cb_datum.lineEdit().returnPressed.connect(self._auto_format_datum)

        # Prefix toggle buttons
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Präfix:"))
        self._prefix_btns: dict[str, QPushButton] = {}
        for label in ("RE", "E-Mail", "an"):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(64)
            btn.clicked.connect(lambda checked, l=label: self._toggle_prefix(l))
            prefix_layout.addWidget(btn)
            self._prefix_btns[label] = btn
        prefix_layout.addStretch()
        top_layout.addLayout(prefix_layout)

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
        self.pdf_opened.emit(path)

        self.status_message.emit("Analysiere Dokument …")
        self._analyze_worker = AnalyzeWorker(path)
        self._analyze_worker.result_ready.connect(self._on_analysis_done)
        self._analyze_worker.error.connect(self._on_analysis_error)
        self._analyze_worker.finished.connect(self._analyze_worker.deleteLater)
        self._analyze_worker.start()

    def load_from_result(self, path: str, result: dict):
        self.pdf_path = path
        self.lbl_file.setText(os.path.basename(path))
        self.lbl_source.setText("")
        self.btn_open.setEnabled(True)
        self.progress.setVisible(False)
        self._clear_fields()
        self.pdf_opened.emit(path)
        self._on_analysis_done(result)

    def _clear_fields(self):
        for cb in (self.cb_typ, self.cb_absender, self.cb_datum, self.cb_person):
            cb.clear()
        self.le_zusatz.clear()
        self.lbl_preview.setText("—")
        self.txt_ocr.clear()
        if self._prefix:
            self._prefix_btns[self._prefix].setChecked(False)
            self._prefix = ""

    def _populate_combos(self):
        persons = database.get_persons()
        self.cb_person.addItems([""] + persons)
        self._person_completer.setModel(QStringListModel(persons))

        typen = database.load_dokumenttypen()
        self.cb_typ.addItems([""] + [t["name"] for t in typen])
        self._typ_completer.set_items(typen)
        self.cb_typ.lineEdit().setCompleter(self._typ_completer)

        absender = database.load_absender()
        self.cb_absender.addItems([""] + [a["name"] for a in absender])
        self._absender_completer.set_items(absender)
        self.cb_absender.lineEdit().setCompleter(self._absender_completer)

    def _on_analysis_done(self, result: dict):
        self.result_ready.emit(self.pdf_path, result)
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self._populate_combos()

        source = result.get("source", "")
        conf = result.get("confidence", 0.0)
        if source == "tfidf":
            src_text = f"Fast-Lane (TF-IDF) · Konfidenz: {conf:.0%}"
        elif source == "fuzzy":
            src_text = f"Fuzzy-Lane · Konfidenz: {conf:.0%}"
        else:
            src_text = f"LLM-Fallback ({app_config.get_ollama_model()}) · TF-IDF: {conf:.0%}"
        neu_parts = []
        if result.get("vorschlag_typ"):
            neu_parts.append(f"Typ: {result.get('dokumenttyp', '')}")
        if result.get("vorschlag_ab"):
            neu_parts.append(f"Absender: {result.get('absender', '')}")
        if neu_parts:
            src_text += f"  |  neu erkannt: {', '.join(neu_parts)}"
        self.lbl_source.setText(src_text)

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

        sep = "─" * 60
        debug_lines = []

        # ── 1. OCR ────────────────────────────────────────────────────
        ocr_text = result.get("ocr_text", "")
        debug_lines += [sep, "[ 1 ] OCR-TEXT", sep, ocr_text, ""]

        # ── 2. Datumserkennung ────────────────────────────────────────
        candidates = result.get("dokumentdatum_candidates", [])
        debug_lines += [
            sep, "[ 2 ] DATUMSERKENNUNG", sep,
            f"Kandidaten: {', '.join(candidates) if candidates else '(keine)'}",
            ""
        ]

        # ── 3. TF-IDF ────────────────────────────────────────────────
        debug_lines += [sep, "[ 3 ] TF-IDF KLASSIFIKATION", sep]
        for i, t in enumerate(result.get("tfidf_top", []), 1):
            marker = "►" if i == 1 else " "
            debug_lines.append(
                f"  {marker} #{i}  {t['score']:.1%}  {t['corpus']!r}  →  {t['typ']} / {t['ab']}"
            )
        tfidf_conf = result.get("confidence", 0) if result.get("source") == "tfidf" else 0
        debug_lines += [
            "",
            f"  Konfidenz: {tfidf_conf:.1%}  |  Schwellwert: {pipeline.TFIDF_THRESHOLD:.0%}  |  "
            f"TF-IDF-Lane: {'JA' if result.get('source') == 'tfidf' else 'NEIN'}",
            ""
        ]

        # ── 3b. Fuzzy-Matching ───────────────────────────────────────
        fuzzy = result.get("fuzzy", {})
        debug_lines += [sep, "[ 3b ] FUZZY-MATCHING", sep]
        if fuzzy:
            fz_lane = result.get("source") == "fuzzy"
            debug_lines += [
                f"  Typ     : {fuzzy.get('typ', '')}  ({fuzzy.get('typ_score', 0):.0%})"
                f"  via '{fuzzy.get('typ_match', '')}'",
                f"  Absender: {fuzzy.get('ab', '')}  ({fuzzy.get('ab_score', 0):.0%})"
                f"  via '{fuzzy.get('ab_match', '')}'",
                f"  Gesamt  : {fuzzy.get('score', 0):.0%}  |  Schwellwert: {pipeline.FUZZY_THRESHOLD:.0%}  |  "
                f"Fuzzy-Lane: {'JA → LLM übersprungen' if fz_lane else 'NEIN'}",
                ""
            ]
        else:
            debug_lines += ["  (keine)", ""]

        # ── 4. RAG-Kontext ────────────────────────────────────────────
        rag = result.get("rag_context", "")
        debug_lines += [sep, "[ 4 ] RAG-KONTEXT (an LLM gesendet)", sep, rag or "(keine)", ""]

        # ── 5. LLM-Prompt ─────────────────────────────────────────────
        llm_prompt = result.get("llm_prompt", "")
        debug_lines += [sep, "[ 5 ] LLM-PROMPT", sep, llm_prompt or "(keine)", ""]

        # ── 6. LLM-Rohantwort ─────────────────────────────────────────
        llm_raw = result.get("llm_raw", "")
        debug_lines += [sep, "[ 6 ] LLM-ROHANTWORT", sep, llm_raw.strip() if llm_raw else "(keine)", ""]

        # ── 7. LLM-Parsed JSON ────────────────────────────────────────
        import json as _json
        llm_parsed = result.get("llm_parsed", {})
        debug_lines += [sep, "[ 7 ] LLM-PARSED JSON", sep,
                        _json.dumps(llm_parsed, ensure_ascii=False, indent=2) if llm_parsed else "(keine)", ""]

        # ── 8. Endergebnis ────────────────────────────────────────────
        debug_lines += [
            sep, "[ 8 ] ENDERGEBNIS", sep,
            f"  Dokumenttyp : {result.get('dokumenttyp', '')}",
            f"  Absender    : {result.get('absender', '')}",
            f"  Datum       : {result.get('dokumentdatum', '')}",
            f"  Person      : {result.get('personenbezug', '')}",
            f"  Quelle      : {result.get('source', '').upper()}",
        ]

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
        options = _normalize_date_options(raw)
        if len(options) > 1:
            # Ambiguous input: show both interpretations in dropdown, keep existing OCR items below
            existing = [self.cb_datum.itemText(i) for i in range(self.cb_datum.count())
                        if self.cb_datum.itemText(i) not in options]
            self.cb_datum.blockSignals(True)
            self.cb_datum.clear()
            self.cb_datum.addItems(options + existing)
            self.cb_datum.setCurrentIndex(0)
            self.cb_datum.blockSignals(False)
            self._update_preview()
        elif options and options[0] != raw:
            self.cb_datum.setCurrentText(options[0])

    def _open_edit_dialog(self, kind: str):
        name = (self.cb_typ if kind == "typ" else self.cb_absender).currentText().strip()
        if not name:
            QMessageBox.information(self, "Kein Eintrag", "Bitte zuerst einen Eintrag auswählen.")
            return
        dlg = _EditStammdatenDialog(kind, name, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.save()
            self._populate_combos()
            self._update_preview()

    def _toggle_prefix(self, label: str):
        if self._prefix == label:
            self._prefix = ""
            self._prefix_btns[label].setChecked(False)
        else:
            if self._prefix:
                self._prefix_btns[self._prefix].setChecked(False)
            self._prefix = label
            self._prefix_btns[label].setChecked(True)
        self._update_preview()

    def _build_parts(self) -> list[str]:
        typ    = database.get_dokumenttyp_display(self.cb_typ.currentText().strip())
        zusatz = self.le_zusatz.text().strip()
        ab     = database.get_absender_display(self.cb_absender.currentText().strip())
        dat    = self.cb_datum.currentText().strip()
        dat    = f"v{dat}" if dat and not dat.startswith("v") else dat
        per    = self.cb_person.currentText().strip()
        if self._prefix == "an":
            ordered = [self._prefix, ab, typ, zusatz, dat, per]
        else:
            ordered = [self._prefix, typ, zusatz, ab, dat, per]
        return [p.replace(" ", "_") for p in ordered if p]

    def _update_preview(self):
        parts = self._build_parts()
        self.lbl_preview.setText("_".join(parts) + ".pdf" if parts else "—")

    def _confirm(self):
        if not self.pdf_path:
            return
        typ    = self.cb_typ.currentText().strip()
        zusatz = self.le_zusatz.text().strip()
        ab     = self.cb_absender.currentText().strip()
        dat    = self.cb_datum.currentText().strip()
        per    = self.cb_person.currentText().strip()

        if not typ or not ab:
            QMessageBox.warning(self, "Fehlende Felder", "Bitte Dokumenttyp und Absender angeben.")
            return

        dat = _normalize_date(dat)
        self.cb_datum.setCurrentText(dat)

        self.btn_confirm.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.progress.setVisible(True)

        self.status_message.emit("Schreibe Metadaten & archiviere …")
        self._confirm_worker = ConfirmWorker(self.pdf_path, typ, ab, dat, per, zusatz, self._prefix)
        self._confirm_worker.result_ready.connect(self._on_confirm_done)
        self._confirm_worker.error.connect(self._on_confirm_error)
        self._confirm_worker.finished.connect(self._confirm_worker.deleteLater)
        self._confirm_worker.start()

    def _on_confirm_done(self, dest: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        new_name = os.path.basename(dest)
        self.status_message.emit(f"Archiviert: {new_name}")
        QMessageBox.information(self, "Archiviert", f"Gespeichert als:\n{new_name}")
        orig_path = self.pdf_path
        self.pdf_path = ""
        self.lbl_file.setText("Kein Dokument geladen")
        self.lbl_source.setText("")
        self._clear_fields()
        self.settings_refresh_requested.emit()
        self.confirmed.emit(orig_path)

    def _on_confirm_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.btn_confirm.setEnabled(True)
        self.status_message.emit("Archivierung fehlgeschlagen")
        QMessageBox.critical(self, "Fehler", f"Archivierung fehlgeschlagen:\n{msg}")

    def reset(self):
        """Unload current document without archiving."""
        for worker in (self._analyze_worker, self._confirm_worker):
            if worker and worker.isRunning():
                try:
                    worker.result_ready.disconnect()
                    worker.error.disconnect()
                except Exception:
                    pass
        self._analyze_worker = None
        self._confirm_worker = None
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.btn_confirm.setEnabled(False)
        self.pdf_path = ""
        self.lbl_file.setText("Kein Dokument geladen")
        self.lbl_source.setText("")
        self._clear_fields()


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------

def _make_single_table(header: str) -> QTableWidget:
    t = QTableWidget(0, 1)
    t.setHorizontalHeaderLabels([header])
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return t


def _table_values(table: QTableWidget, col: int = 0, selected_only: bool = False) -> list[str]:
    result = []
    selected_rows = {i.row() for i in table.selectedIndexes()} if selected_only else None
    for row in range(table.rowCount()):
        if selected_rows is not None and row not in selected_rows:
            continue
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

        # ── Dokumenttypen + Absender (vertikal) | Personen ───────────────
        self.tbl_typen = QTableWidget(0, 3)
        self.tbl_typen.setHorizontalHeaderLabels(["Name", "Abk.", "Synonyme (kommagetrennt)"])
        self.tbl_typen.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_typen.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_typen.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_typen.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        grp_t = self._grp("Dokumenttypen", self.tbl_typen,
                          self._add_typ, self._del_typ, self._save_typen)

        self.tbl_abs = QTableWidget(0, 3)
        self.tbl_abs.setHorizontalHeaderLabels(["Name", "Abk.", "Synonyme (kommagetrennt)"])
        self.tbl_abs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_abs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_abs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_abs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        grp_a = self._grp("Absender", self.tbl_abs,
                          self._add_abs, self._del_abs, self._save_abs)

        left_col = QVBoxLayout()
        left_col.addWidget(grp_t)
        left_col.addWidget(grp_a)

        self.tbl_pers = _make_single_table("Nachname")
        grp_p = self._grp("Personen", self.tbl_pers,
                          self._add_pers, self._del_pers, self._save_pers)
        grp_p.setMaximumWidth(200)

        top = QHBoxLayout()
        top.addLayout(left_col)
        top.addWidget(grp_p)
        root.addLayout(top)

        # ── Bottom: KI-Kontext (Kombinationen, einklappbar) ───────────────
        _TOGGLE_STYLE = (
            "QPushButton { text-align: left; padding: 4px 8px; "
            "background: #f0f0f0; border: 1px solid #bbb; border-radius: 3px; }"
        )
        self._btn_toggle_kombi = QPushButton("▶   KI-Kontext – historische Kombinationen")
        self._btn_toggle_kombi.setCheckable(True)
        self._btn_toggle_kombi.setChecked(False)
        self._btn_toggle_kombi.setStyleSheet(_TOGGLE_STYLE)
        self._btn_toggle_kombi.clicked.connect(self._toggle_kombi)
        root.addWidget(self._btn_toggle_kombi)

        self._kombi_content = QWidget()
        vk = QVBoxLayout(self._kombi_content)
        vk.setContentsMargins(0, 4, 0, 0)

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
        self._kombi_content.setVisible(False)
        root.addWidget(self._kombi_content)

        # ── Vorschläge (einklappbar) ──────────────────────────────────
        self._btn_toggle_vorschlaege = QPushButton("▶   KI-Vorschläge – neu erkannte Einträge")
        self._btn_toggle_vorschlaege.setCheckable(True)
        self._btn_toggle_vorschlaege.setChecked(False)
        self._btn_toggle_vorschlaege.setStyleSheet(_TOGGLE_STYLE)
        self._btn_toggle_vorschlaege.clicked.connect(self._toggle_vorschlaege)
        root.addWidget(self._btn_toggle_vorschlaege)

        self._vorschlaege_content = QWidget()
        vv = QVBoxLayout(self._vorschlaege_content)
        vv.setContentsMargins(0, 4, 0, 0)

        vv.addWidget(QLabel("Dokumenttypen:"))
        self.tbl_vtyp = _make_single_table("Name")
        vv.addWidget(self.tbl_vtyp)

        vv.addWidget(QLabel("Absender:"))
        self.tbl_vabs = _make_single_table("Name")
        vv.addWidget(self.tbl_vabs)

        bar_v = QHBoxLayout()
        btn_v_acc = QPushButton("Übernehmen")
        btn_v_rej = QPushButton("Ablehnen")
        btn_v_acc.clicked.connect(self._accept_vorschlag)
        btn_v_rej.clicked.connect(self._reject_vorschlag)
        bar_v.addWidget(btn_v_acc)
        bar_v.addWidget(btn_v_rej)
        vv.addLayout(bar_v)
        self._vorschlaege_content.setVisible(False)
        root.addWidget(self._vorschlaege_content)

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
        v = database.load_vorschlaege()
        _fill_single(self.tbl_vtyp, v.get("dokumenttypen", []))
        _fill_single(self.tbl_vabs, v.get("absender", []))
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

    # Vorschläge
    def _accept_vorschlag(self):
        for name in _table_values(self.tbl_vtyp, selected_only=True):
            database.promote_vorschlag_dokumenttyp(name)
        for name in _table_values(self.tbl_vabs, selected_only=True):
            database.promote_vorschlag_absender(name)
        self.refresh()
        QMessageBox.information(self, "Übernommen", "Auswahl in Stammdaten übernommen.")

    def _reject_vorschlag(self):
        for name in _table_values(self.tbl_vtyp, selected_only=True):
            database.remove_vorschlag("dokumenttypen", name)
        for name in _table_values(self.tbl_vabs, selected_only=True):
            database.remove_vorschlag("absender", name)
        self.refresh()

    def _toggle_kombi(self):
        visible = self._btn_toggle_kombi.isChecked()
        self._kombi_content.setVisible(visible)
        arrow = "▼" if visible else "▶"
        self._btn_toggle_kombi.setText(f"{arrow}   KI-Kontext – historische Kombinationen")

    def _toggle_vorschlaege(self):
        visible = self._btn_toggle_vorschlaege.isChecked()
        self._vorschlaege_content.setVisible(visible)
        arrow = "▼" if visible else "▶"
        self._btn_toggle_vorschlaege.setText(f"{arrow}   KI-Vorschläge – neu erkannte Einträge")

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
# KI status tab
# ---------------------------------------------------------------------------

class KIStatusTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._check_worker: OllamaCheckWorker | None = None
        self._pull_worker: OllamaPullWorker | None = None
        self._test_worker: GoogleTestWorker | None = None
        self._status: dict = {}
        self._build_ui()
        QTimer.singleShot(800, self._check)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Provider selection ──────────────────────────────────────────────
        grp_sel = QGroupBox("KI-Anbieter")
        sel_layout = QHBoxLayout(grp_sel)
        self._radio_ollama = QRadioButton("Ollama  (lokal, offline)")
        self._radio_google = QRadioButton("Google GenAI  (Cloud)")
        self._provider_group = QButtonGroup(self)
        self._provider_group.addButton(self._radio_ollama, 0)
        self._provider_group.addButton(self._radio_google, 1)
        sel_layout.addWidget(self._radio_ollama)
        sel_layout.addWidget(self._radio_google)
        sel_layout.addStretch()
        btn_save_provider = QPushButton("Speichern")
        btn_save_provider.clicked.connect(self._save_provider)
        sel_layout.addWidget(btn_save_provider)
        root.addWidget(grp_sel)

        # Restore saved selection
        if app_config.get_provider() == "google":
            self._radio_google.setChecked(True)
        else:
            self._radio_ollama.setChecked(True)

        # ── Ollama section ──────────────────────────────────────────────────
        self._grp_ollama = QGroupBox("Ollama – Einrichtung")
        v = QVBoxLayout(self._grp_ollama)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Modell:"))
        self._cb_ollama_model = QComboBox()
        for m in app_config.OLLAMA_MODELS:
            self._cb_ollama_model.addItem(m)
        saved_model = app_config.get_ollama_model()
        idx = self._cb_ollama_model.findText(saved_model)
        self._cb_ollama_model.setCurrentIndex(idx if idx >= 0 else 0)
        model_row.addWidget(self._cb_ollama_model)
        btn_save_model = QPushButton("Speichern")
        btn_save_model.clicked.connect(self._save_ollama_model)
        model_row.addWidget(btn_save_model)
        v.addLayout(model_row)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self._lbl_installed = QLabel("—")
        self._lbl_running = QLabel("—")
        self._lbl_model = QLabel("—")
        self._lbl_model_name = QLabel("Ollama installiert:")
        for row, (lbl_widget, status_lbl) in enumerate([
            (QLabel("Ollama installiert:"), self._lbl_installed),
            (QLabel("Ollama läuft:"), self._lbl_running),
            (self._lbl_model_name, self._lbl_model),
        ]):
            grid.addWidget(lbl_widget, row, 0)
            grid.addWidget(status_lbl, row, 1)
        self._update_model_label()
        v.addLayout(grid)

        bar = QHBoxLayout()
        self._btn_check = QPushButton("Prüfen")
        self._btn_check.clicked.connect(self._check)
        self._btn_fix = QPushButton("Einrichten")
        self._btn_fix.clicked.connect(self._fix)
        self._btn_fix.setEnabled(False)
        bar.addWidget(self._btn_check)
        bar.addWidget(self._btn_fix)
        bar.addStretch()
        v.addLayout(bar)
        root.addWidget(self._grp_ollama)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # ── Google GenAI section ────────────────────────────────────────────
        self._grp_google = QGroupBox("Google GenAI – API-Schlüssel")
        gv = QVBoxLayout(self._grp_google)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API-Schlüssel:"))
        self._le_apikey = QLineEdit()
        self._le_apikey.setPlaceholderText("AIza…")
        self._le_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self._le_apikey.setText(app_config.get_google_api_key())
        key_row.addWidget(self._le_apikey)
        btn_show = QPushButton("Anzeigen")
        btn_show.setCheckable(True)
        btn_show.toggled.connect(
            lambda on: self._le_apikey.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        key_row.addWidget(btn_show)
        gv.addLayout(key_row)

        g_bar = QHBoxLayout()
        btn_save_key = QPushButton("Schlüssel speichern")
        btn_save_key.clicked.connect(self._save_google_key)
        self._btn_test_google = QPushButton("Verbindung testen")
        self._btn_test_google.clicked.connect(self._test_google)
        self._lbl_google_status = QLabel("")
        g_bar.addWidget(btn_save_key)
        g_bar.addWidget(self._btn_test_google)
        g_bar.addWidget(self._lbl_google_status)
        g_bar.addStretch()
        gv.addLayout(g_bar)
        root.addWidget(self._grp_google)

        # ── Shared log ──────────────────────────────────────────────────────
        self._txt = QTextEdit()
        self._txt.setReadOnly(True)
        self._txt.setMaximumHeight(140)
        root.addWidget(self._txt)
        root.addStretch()

    # ── Provider save ───────────────────────────────────────────────────────

    def _save_provider(self):
        provider = "google" if self._radio_google.isChecked() else "ollama"
        cfg = app_config.load()
        cfg["llm_provider"] = provider
        app_config.save(cfg)
        model = app_config.get_ollama_model()
        name = "Google GenAI" if provider == "google" else "Ollama"
        self._txt.setPlainText(f"KI-Anbieter gespeichert: {name}")

    def _save_ollama_model(self):
        model = self._cb_ollama_model.currentText()
        cfg = app_config.load()
        cfg["ollama_model"] = model
        app_config.save(cfg)
        self._update_model_label()
        self._txt.setPlainText(f"Ollama-Modell gespeichert: {model}")

    def _update_model_label(self):
        model = self._cb_ollama_model.currentText() if hasattr(self, '_cb_ollama_model') else app_config.get_ollama_model()
        self._lbl_model_name.setText(f"{model} verfügbar:")

    # ── Ollama ──────────────────────────────────────────────────────────────

    def _set_status(self, label: QLabel, state):
        if state is None:
            label.setText("⋯  Prüfe …")
            label.setStyleSheet("color: #888;")
        elif state:
            label.setText("✓  OK")
            label.setStyleSheet("color: green; font-weight: bold;")
        else:
            label.setText("✗  Fehlt")
            label.setStyleSheet("color: red; font-weight: bold;")

    def _check(self):
        self._btn_check.setEnabled(False)
        self._btn_fix.setEnabled(False)
        for lbl in (self._lbl_installed, self._lbl_running, self._lbl_model):
            self._set_status(lbl, None)
        model = self._cb_ollama_model.currentText()
        self._update_model_label()
        self._check_worker = OllamaCheckWorker(model)
        self._check_worker.result.connect(self._on_check_done)
        self._check_worker.finished.connect(self._check_worker.deleteLater)
        self._check_worker.start()

    def _on_check_done(self, status: dict):
        self._status = status
        self._set_status(self._lbl_installed, status["installed"])
        self._set_status(self._lbl_running, status["running"])
        self._set_status(self._lbl_model, status["model"])
        self._btn_check.setEnabled(True)
        all_ok = all(status.values())
        self._btn_fix.setEnabled(not all_ok)
        if all_ok:
            model = self._cb_ollama_model.currentText()
            self._txt.setPlainText(f"Alles bereit. {model} ist verfügbar und kann für die Klassifikation genutzt werden.")
        else:
            issues = []
            if not status["installed"]:
                issues.append("Ollama ist nicht installiert.")
                issues.append("→ Klicken Sie auf 'Einrichten' für Installationshinweise.")
            elif not status["running"]:
                issues.append("Ollama ist installiert, aber nicht gestartet.")
                issues.append("→ Klicken Sie auf 'Einrichten' um den Server zu starten.")
            if status.get("installed") and status.get("running") and not status["model"]:
                model = self._cb_ollama_model.currentText()
                issues.append(f"{model} ist nicht heruntergeladen.")
                issues.append("→ Klicken Sie auf 'Einrichten' um das Modell zu laden.")
            self._txt.setPlainText("\n".join(issues))

    def _fix(self):
        if not self._status.get("installed"):
            QMessageBox.information(
                self, "Ollama installieren",
                "Ollama ist nicht installiert.\n\n"
                "Installation über Homebrew (Terminal):\n"
                "    brew install ollama\n\n"
                "Oder Download von: https://ollama.ai",
            )
            return

        if not self._status.get("running"):
            self._txt.clear()
            self._txt.append("Starte Ollama-Server …")
            try:
                _popen_flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_popen_flags,
                )
                self._txt.append("Warte auf Serverstart …")
            except Exception as e:
                self._txt.append(f"Fehler: {e}")
            QTimer.singleShot(2500, self._check)
            return

        if not self._status.get("model"):
            self._pull_model()

    def _pull_model(self):
        model = self._cb_ollama_model.currentText()
        self._btn_fix.setEnabled(False)
        self._btn_check.setEnabled(False)
        self._progress.setVisible(True)
        self._txt.clear()
        self._txt.append(f"Lade {model} herunter …")
        self._pull_worker = OllamaPullWorker(model)
        self._pull_worker.progress.connect(lambda line: self._txt.append(line))
        self._pull_worker.done.connect(self._on_pull_done)
        self._pull_worker.start()

    def _on_pull_done(self, success: bool):
        self._progress.setVisible(False)
        self._btn_check.setEnabled(True)
        if success:
            model = self._cb_ollama_model.currentText()
            self._txt.append(f"\n{model} erfolgreich installiert!")
            self._check()
        else:
            self._txt.append("\nDownload fehlgeschlagen – bitte erneut versuchen.")
            self._btn_fix.setEnabled(True)

    # ── Google GenAI ────────────────────────────────────────────────────────

    def _save_google_key(self):
        key = self._le_apikey.text().strip()
        cfg = app_config.load()
        cfg["google_api_key"] = key
        app_config.save(cfg)
        self._lbl_google_status.setText("Gespeichert.")
        self._lbl_google_status.setStyleSheet("color: green;")

    def _test_google(self):
        key = self._le_apikey.text().strip()
        if not key:
            self._lbl_google_status.setText("Kein API-Schlüssel eingegeben.")
            self._lbl_google_status.setStyleSheet("color: red;")
            return
        self._btn_test_google.setEnabled(False)
        self._lbl_google_status.setText("Teste …")
        self._lbl_google_status.setStyleSheet("color: #888;")
        self._test_worker = GoogleTestWorker(key)
        self._test_worker.result.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, success: bool, msg: str):
        self._btn_test_google.setEnabled(True)
        self._lbl_google_status.setText("✓ OK" if success else "✗ Fehler")
        self._lbl_google_status.setStyleSheet(
            "color: green; font-weight: bold;" if success else "color: red; font-weight: bold;"
        )
        self._txt.setPlainText(msg)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

_MAX_PRE_WORKERS = 1


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PostScan")
        self.resize(1200, 620)

        # Queue state
        self._queue: list[str] = []
        self._cache: dict[str, dict] = {}
        self._pre_workers: dict[str, AnalyzeWorker] = {}

        # Tabs (centre)
        self._tabs = QTabWidget()
        self._tabs.setMinimumWidth(280)
        self.main_tab = MainTab()
        self.settings_tab = SettingsTab()
        self.ki_tab = KIStatusTab()
        self.main_tab.settings_refresh_requested.connect(self.settings_tab.refresh)
        self._tabs.addTab(self.main_tab, "Dokument")
        self._tabs.addTab(self.settings_tab, "Stammdaten")
        self._tabs.addTab(self.ki_tab, "KI-Einrichtung")

        # Toggle buttons as corner widgets on the tab bar
        self._queue_last_size = 180
        self._pdf_last_size = 600

        self._btn_toggle_queue = QPushButton("☰")
        self._btn_toggle_queue.setCheckable(True)
        self._btn_toggle_queue.setChecked(True)
        self._btn_toggle_queue.setFixedHeight(24)
        self._btn_toggle_queue.setToolTip("Warteschlange ein-/ausblenden")
        self._btn_toggle_queue.clicked.connect(self._toggle_queue)
        self._tabs.setCornerWidget(self._btn_toggle_queue, Qt.Corner.TopLeftCorner)

        self._btn_toggle_pdf = QPushButton("PDF")
        self._btn_toggle_pdf.setCheckable(True)
        self._btn_toggle_pdf.setChecked(True)
        self._btn_toggle_pdf.setFixedHeight(24)
        self._btn_toggle_pdf.setToolTip("PDF-Ansicht ein-/ausblenden")
        self._btn_toggle_pdf.clicked.connect(self._toggle_pdf)
        self._tabs.setCornerWidget(self._btn_toggle_pdf, Qt.Corner.TopRightCorner)

        # ── Left panel: drop zone + queue ──────────────────────────────
        self._queue_panel = QWidget()
        self._queue_panel.setMinimumWidth(160)
        self._queue_panel.setMaximumWidth(220)
        qp_layout = QVBoxLayout(self._queue_panel)
        qp_layout.setContentsMargins(4, 4, 4, 4)
        qp_layout.setSpacing(6)

        self._drop_zone = DropZone()
        self._drop_zone.files_dropped.connect(self._enqueue)
        qp_layout.addWidget(self._drop_zone)

        self._lbl_queue = QLabel("Warteschlange")
        font_q = self._lbl_queue.font()
        font_q.setPointSize(10)
        self._lbl_queue.setFont(font_q)
        qp_layout.addWidget(self._lbl_queue)

        self._lst_queue = QListWidget()
        self._lst_queue.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._lst_queue.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._lst_queue.itemClicked.connect(self._on_queue_item_clicked)
        qp_layout.addWidget(self._lst_queue, stretch=1)

        self._btn_clear = QPushButton("Leeren")
        self._btn_clear.clicked.connect(self._clear_queue)
        qp_layout.addWidget(self._btn_clear)

        # ── Right panel: PDF viewer ─────────────────────────────────────
        self._pdf_doc = QPdfDocument(self)
        self._pdf_view = QPdfView(self)
        self._pdf_view.setDocument(self._pdf_doc)
        self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
        self._pdf_view.setMinimumWidth(300)

        # ── Three-panel horizontal splitter ─────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._queue_panel)
        self._splitter.addWidget(self._tabs)
        self._splitter.addWidget(self._pdf_view)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 2)
        self._splitter.setSizes([180, 420, 600])
        self.setCentralWidget(self._splitter)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage("PostScan bereit – PDFs in der Warteschlange ablegen")
        self.setStatusBar(self._status_bar)
        self.main_tab.status_message.connect(self._status_bar.showMessage)
        self.main_tab.confirmed.connect(self._on_confirmed)
        self.main_tab.result_ready.connect(self._on_result_ready)
        self.main_tab.pdf_opened.connect(self._show_pdf)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._clamp_pdf_width)

    def changeEvent(self, event):
        super().changeEvent(event)
        QTimer.singleShot(0, self._clamp_pdf_width)

    def _clamp_pdf_width(self):
        if not self._pdf_view.isVisible():
            return
        total = self._splitter.width()
        if total > 0:
            self._pdf_view.setMaximumWidth(int(total * 0.4))

    def _toggle_queue(self):
        if self._queue_panel.isVisible():
            self._queue_last_size = self._splitter.sizes()[0]
            self._queue_panel.setVisible(False)
        else:
            self._queue_panel.setVisible(True)
            sizes = self._splitter.sizes()
            sizes[0] = self._queue_last_size or 180
            self._splitter.setSizes(sizes)

    def _toggle_pdf(self):
        if self._pdf_view.isVisible():
            self._pdf_last_size = self._splitter.sizes()[2]
            self._pdf_view.setVisible(False)
        else:
            self._pdf_view.setMaximumWidth(16777215)
            self._pdf_view.setVisible(True)
            sizes = self._splitter.sizes()
            sizes[2] = self._pdf_last_size or 600
            self._splitter.setSizes(sizes)
            QTimer.singleShot(0, self._clamp_pdf_width)

    def _on_result_ready(self, path: str, result: dict):
        if path:
            self._cache[path] = result

    def _show_pdf(self, path: str):
        self._pdf_doc.close()
        if path:
            self._pdf_doc.load(path)

    def _on_confirmed(self, orig_path: str):
        self._cache.pop(orig_path, None)
        self._pdf_doc.close()
        self._load_next()

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _enqueue(self, paths: list[str]):
        for path in paths:
            if path not in self._queue and path != self.main_tab.pdf_path:
                self._queue.append(path)
        self._refresh_queue_list()
        if not self.main_tab.pdf_path:
            self._load_next()
        else:
            self._start_preprocessing()

    def _load_next(self):
        if not self._queue:
            self._refresh_queue_list()
            return
        path = self._queue.pop(0)
        # Detach pre-worker for this path (it will finish but result is ignored)
        if path in self._pre_workers:
            w = self._pre_workers.pop(path)
            try:
                w.result_ready.disconnect()
                w.error.disconnect()
            except Exception:
                pass
        self._refresh_queue_list()
        if path in self._cache:
            self.main_tab.load_from_result(path, self._cache[path])
            self._status_bar.showMessage(
                f"Geladen aus Cache: {os.path.basename(path)} – Felder prüfen und bestätigen"
            )
        else:
            self.main_tab.load_pdf(path)
        self._start_preprocessing()

    def _start_preprocessing(self):
        for path in self._queue:
            if len(self._pre_workers) >= _MAX_PRE_WORKERS:
                break
            if path not in self._pre_workers and path not in self._cache:
                worker = AnalyzeWorker(path)
                worker.result_ready.connect(lambda res, p=path: self._on_pre_done(p, res))
                worker.error.connect(lambda _err, p=path: self._pre_workers.pop(p, None))
                worker.finished.connect(worker.deleteLater)
                self._pre_workers[path] = worker
                worker.start()
        self._refresh_queue_list()

    def _on_pre_done(self, path: str, result: dict):
        self._pre_workers.pop(path, None)
        if path in self._queue:
            self._cache[path] = result
        self._start_preprocessing()
        self._refresh_queue_list()

    def _clear_queue(self):
        for w in self._pre_workers.values():
            try:
                w.result_ready.disconnect()
                w.error.disconnect()
            except Exception:
                pass
        self._pre_workers.clear()
        self._cache.clear()
        self._queue.clear()
        self.main_tab.reset()
        self._pdf_doc.close()
        self._status_bar.showMessage("Warteschlange geleert")
        self._refresh_queue_list()

    def _refresh_queue_list(self):
        self._lst_queue.clear()
        current = self.main_tab.pdf_path

        if current:
            item = QListWidgetItem(f"▶  {os.path.basename(current)}")
            item.setForeground(QColor("#007aff"))
            item.setData(Qt.ItemDataRole.UserRole, current)
            item.setToolTip(current)
            self._lst_queue.addItem(item)

        for path in self._queue:
            name = os.path.basename(path)
            if path in self._cache:
                text = f"✓  {name}"
                color = QColor("#2e7d32")
            elif path in self._pre_workers:
                text = f"⋯  {name}"
                color = QColor("#888")
            else:
                text = f"    {name}"
                color = QColor("#333")
            item = QListWidgetItem(text)
            item.setForeground(color)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._lst_queue.addItem(item)

        count = len(self._queue) + (1 if current else 0)
        self._lbl_queue.setText(f"Warteschlange ({count})" if count else "Warteschlange")

    def _on_queue_item_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path or path == self.main_tab.pdf_path:
            return
        self._switch_to(path)

    def _switch_to(self, path: str):
        current = self.main_tab.pdf_path
        if path in self._queue:
            self._queue.remove(path)
        if current and current not in self._queue:
            self._queue.insert(0, current)
        if path in self._cache:
            self.main_tab.load_from_result(path, self._cache[path])
            self._status_bar.showMessage(
                f"Geladen aus Cache: {os.path.basename(path)} – Felder prüfen und bestätigen"
            )
        else:
            self.main_tab.load_pdf(path)
        self._start_preprocessing()
        self._refresh_queue_list()


def main():
    database.ensure_defaults()
    os.makedirs(EINGANG_DIR, exist_ok=True)

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
