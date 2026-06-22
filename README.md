# PostScan

Lokales Desktop-Tool (macOS & Windows) zur automatischen Analyse, Klassifikation und Archivierung von Eingangspost als PDF.

---

## Funktionsweise (Hybrid-Pipeline)

```
PDF öffnen / per Drag & Drop ablegen
    │
    ▼
[Step 1] OCR-Shortcut
    Digitales PDF? → pdftotext (schnell, kein OCR nötig)
    Gescanntes PDF? → ocrmypdf --skip-text --pages 1-2
    │
    ▼
[Step 2] Deterministische Extraktion
    Datum   → Regex (DD.MM.YYYY / YYYY-MM-DD / D. Monat YYYY → vDD.MM.YY)
    Typ/Abs → TF-IDF Kosinus-Ähnlichkeit gegen stammdaten.json
    │
    ▼
[Step 3] Fast-Lane-Check
    TF-IDF > 85 % UND Datum klar? → Ergebnis direkt, kein LLM
    │
    ▼
[Step 4] Fuzzy-Matching (rapidfuzz)
    partial_ratio gegen bekannte Typen & Absender
    Score ≥ 80 % UND Datum klar? → Ergebnis direkt, kein LLM
    │
    ▼
[Step 5] LLM-Fallback (nur bei niedriger Konfidenz)
    Ollama (lokal, offline) oder Google GenAI (Cloud)
    RAG-Kontext aus stammdaten.json gegen Halluzinationen
    Unbekannte Typen/Absender werden automatisch übernommen
    │
    ▼
[GUI] Felder prüfen & bestätigen
    a) stammdaten.json updaten (Real-Time Learning)
    b) XMP-Metadaten ins PDF schreiben (pikepdf)
    c) Datei am Originalort umbenennen
```

**Dateiname-Schema:** `[Dokumenttyp]_[Zusatz]_[Absender]_[vDD.MM.YY]_[Personenbezug].pdf`

Beispiel: `Rechnung_HUK-COBURG_v21.06.26_Kunze.pdf`

---

## Features

- **Dreistufige Klassifikation:** TF-IDF → Fuzzy-Matching → LLM — LLM nur bei echtem Bedarf
- **Zwei KI-Anbieter:** Ollama (lokal, offline) oder Google GenAI (Cloud) — umschaltbar im KI-Tab
- **Selbstlernend:** Neu erkannte Dokumenttypen und Absender werden automatisch in die Stammdaten übernommen
- **Warteschlange mit Cache:** Mehrere PDFs laden, zwischen ihnen wechseln — Analyseergebnisse bleiben bis zur Bestätigung gespeichert
- **Drag & Drop:** PDF direkt ins Fenster ziehen — mit visuellem Feedback
- **Leerzustand:** Informativer Startbildschirm wenn kein Dokument geladen ist
- **Flexible Datumseingabe:** Kurz-Syntax ohne Trennzeichen (z. B. `10526` → `10.05.26`); bei mehrdeutigen Eingaben werden beide Interpretationen als Dropdown angeboten
- **Tastaturkürzel:** `⌘O` Öffnen · `⌘↩` Archivieren · `⌘W` Dokument schließen · `⌘,` Einstellungen
- **Einklappbare Panels:** Warteschlange, PDF-Viewer, KI-Kontext und KI-Vorschläge einzeln ein-/ausblendbar
- **Apple HIG:** Vollständig nach Apple Human Interface Guidelines gestaltet — Dark Mode, Fokusringe, native Typografie, VoiceOver-Unterstützung
- **macOS-Tags:** Finder-Tags werden beim Bestätigen automatisch gesetzt
- **Datenschutz:** Alle Verarbeitung lokal; Netzwerkverbindung nur zu lokalem Ollama-Dienst oder Google GenAI (optional)

---

## Systemvoraussetzungen

### macOS

| Komponente | Version | Installation |
|---|---|---|
| Python | 3.12+ | `brew install python` |
| Tesseract | 5+ | `brew install tesseract tesseract-lang` |
| Ghostscript | — | `brew install ghostscript` |
| pdftotext | — | `brew install poppler` |
| Ollama *(optional)* | aktuell | [ollama.com](https://ollama.com) |

### Windows

| Komponente | Version | Quelle |
|---|---|---|
| Python | 3.12+ | [python.org](https://python.org/downloads) |
| Tesseract | 5+ | [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) — Sprache „German" auswählen |
| Ghostscript | — | [ghostscript.com](https://www.ghostscript.com/releases/gsdnld.html) |
| pdftotext | — | [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases) |
| Ollama *(optional)* | aktuell | [ollama.com](https://ollama.com) |

> **Tesseract-Sprachpaket (macOS):** `tesseract-lang` installiert alle Sprachen (~1 GB). Für nur Deutsch reicht `brew install tesseract` + manuell `deu.traineddata` nach `/opt/homebrew/share/tessdata/` kopieren.

---

## Installation

### macOS (Skript-Variante)

```bash
git clone https://github.com/politpatrick/PostScan.git
cd PostScan
bash setup-macos.sh          # einmalig: Abhängigkeiten + venv
open "PostScan starten.command"
```

### Windows (Skript-Variante)

```
git clone https://github.com/politpatrick/PostScan.git
cd PostScan
setup-windows.bat            # einmalig: Abhängigkeiten + venv
start-windows.bat
```

### Manuell (beide Plattformen)

```bash
git clone https://github.com/politpatrick/PostScan.git
cd PostScan
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### KI-Anbieter einrichten

**Ollama (lokal, offline):**
```bash
brew install ollama           # macOS
ollama serve &
ollama pull phi3:mini
```
> Alternativ: Im Tab **„KI-Einrichtung"** den Status prüfen und phi3:mini direkt aus der App laden.

**Google GenAI (Cloud):**
Im Tab **„KI-Einrichtung"** auf „Google GenAI" umschalten und einen API-Schlüssel von [aistudio.google.com](https://aistudio.google.com) eintragen.

---

## Verwendung

1. **PDF öffnen** — Klick auf „PDF öffnen …" oder PDF ins Fenster ziehen (`⌘O`)
2. **Warteschlange** — Mehrere Dateien gleichzeitig laden; Ergebnisse werden im Hintergrund vorberechnet
3. **Felder prüfen** — Alle Felder sind editierbar; bei mehreren erkannten Datumsangaben Dropdown nutzen
4. **Datumskurzeingabe** — Datum ohne Trennzeichen eingeben, Tab/Enter normalisiert automatisch:
   - `10` → `10.MM.JJ` (aktueller Monat & Jahr)
   - `1026` → `10.02.26`
   - `10526` → `10.05.26`
   - `11125` → Dropdown: `01.11.25` oder `11.01.25`
5. **Bestätigen** — `⌘↩` oder Klick auf „Bestätigen & Archivieren":
   - Stammdaten lernen (`stammdaten.json`)
   - XMP-Metadaten ins PDF schreiben
   - Datei am Originalort umbenennen

### Stammdaten-Tab

Bekannte Kombinationen (Dokumenttyp / Absender / Personenbezug) einsehen, bearbeiten und löschen. Neue Einträge entstehen automatisch beim Bestätigen.

### KI-Einrichtung-Tab

Zeigt den Status von Ollama / Google GenAI mit farbigen Indikatoren. Ollama-Modell kann direkt aus der App heruntergeladen werden.

---

## Verzeichnisstruktur

```
PostScan/
├── main.py              # PyQt6 GUI (QThreads: AnalyzeWorker, ConfirmWorker)
├── pipeline.py          # Hybrid-Extraktion: OCR → Regex → TF-IDF → Fuzzy → LLM
├── database.py          # JSON-CRUD für stammdaten.json
├── config.py            # Einstellungen (Provider, API-Key, Modell)
├── requirements.txt     # Python-Abhängigkeiten
│
├── macos/               # macOS-Build (PyInstaller + DMG)
├── windows/             # Windows-Build (PyInstaller + Inno Setup)
│
├── eingang/             # (gitignored) PDFs hier ablegen
└── stammdaten.json      # (gitignored) Lernende Datenbank
```

---

## Konfiguration

`stammdaten.json` wird beim ersten Start automatisch mit Beispieleinträgen angelegt und ist **gitignored**.

```json
[
  {"dokumenttyp": "Rechnung", "absender": "HUK-COBURG", "personenbezug": "Kunze"},
  {"dokumenttyp": "Bescheid", "absender": "Finanzamt",  "personenbezug": "Kunze"}
]
```

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| `pdftotext: command not found` | `brew install poppler` (macOS) oder Poppler-Windows installieren |
| OCR-Ergebnis leer | `brew install tesseract tesseract-lang` |
| Ollama antwortet nicht | `ollama serve` in separatem Terminal starten |
| `phi3:mini` nicht gefunden | `ollama pull phi3:mini` oder KI-Einrichtung-Tab nutzen |
| Google GenAI Fehler | API-Schlüssel im KI-Tab prüfen |
| PyQt6 Import-Fehler | `.venv` aktiv? `source .venv/bin/activate` |
| XMP-Fehler beim Schreiben | PDF schreibgeschützt oder in anderer App geöffnet |

---

## Technische Details

- **RAM-Optimierung:** `keep_alive: 0` im Ollama-Request entlädt das LLM-Modell sofort nach Verwendung
- **Fast-Lane:** Bei TF-IDF-Konfidenz > 85 % + erkanntem Datum wird weder Fuzzy noch LLM aufgerufen
- **Fuzzy-Lane:** `rapidfuzz.fuzz.partial_ratio` — robust gegen OCR-Fehler; Schwelle 80 %
- **LLM-Eingabe:** Auf 810 Zeichen begrenzt für schnelle Antwortzeit
- **Digitale PDFs:** via `pdftotext` extrahiert — kein OCR-Overhead
- **Gescannte PDFs:** `ocrmypdf --skip-text --pages 1-2` — nur erste 2 Seiten
- **TF-IDF:** Char-N-Gram (2–4) — sprachunabhängig, robust gegenüber Tippfehlern
- **Selbstlernen:** Nach LLM-Klassifikation werden unbekannte Typen/Absender direkt in `stammdaten.json` geschrieben
- **UI:** Apple Human Interface Guidelines — `palette()`-Farben, Dark Mode, `QSettings`-Persistenz, VoiceOver
