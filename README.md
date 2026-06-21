# PostScan

Lokales macOS-Tool zur automatischen Analyse, Klassifikation und Archivierung von Eingangspost als PDF. Läuft vollständig offline – keine Cloud, kein Datenschutzrisiko.

---

## Funktionsweise (Hybrid-Pipeline)

```
PDF öffnen
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
    phi3:mini via Ollama (lokal, max. 810 Zeichen Eingabe)
    RAG-Kontext aus stammdaten.json gegen Halluzinationen
    keep_alive: 0 → Modell wird sofort aus RAM entladen
    Unbekannte Typen/Absender werden automatisch in stammdaten.json übernommen
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

- **Dreistufige Klassifikation:** TF-IDF → Fuzzy-Matching → LLM – LLM nur bei echtem Bedarf
- **Selbstlernend:** Neu erkannte Dokumenttypen und Absender werden automatisch in die Stammdaten übernommen
- **Warteschlange mit Cache:** Mehrere PDFs laden, zwischen ihnen wechseln – Analyseergebnisse bleiben bis zur Bestätigung gespeichert
- **KI-Einrichtungstab:** Grafischer Status-Check für Ollama und phi3:mini mit integrierter Installationsmöglichkeit
- **Flexible Datumseingabe:** Kurz-Syntax ohne Trennzeichen (z. B. `10526` → `10.05.26`); bei mehrdeutigen Eingaben (z. B. `11125`) werden beide Interpretationen als Dropdown angeboten
- **Einklappbare Panels:** Warteschlange, PDF-Viewer, KI-Kontext und KI-Vorschläge lassen sich einzeln ein-/ausblenden
- **macOS-Tags:** Finder-Tags werden beim Bestätigen automatisch gesetzt
- **Datenschutz:** Alle Verarbeitung lokal, keine Netzwerkverbindung außer zum lokalen Ollama-Dienst

---

## Systemvoraussetzungen

| Komponente | Version | Installation |
|---|---|---|
| Python | 3.10+ | `brew install python` |
| Ollama | aktuell | [ollama.com](https://ollama.com) |
| ocrmypdf | 16+ | `brew install ocrmypdf` |
| Tesseract | 5+ | `brew install tesseract` |
| Tesseract Deutsch | — | `brew install tesseract-lang` |
| pdftotext | — | `brew install poppler` |

> **Hinweis:** `tesseract-lang` installiert alle Sprachpakete (~1 GB). Für nur Deutsch reicht `brew install tesseract` + manuell `deu.traineddata` nach `/opt/homebrew/share/tessdata/` kopieren.

---

## Installation

### 1. Repository klonen

```bash
git clone https://github.com/politpatrick/PostScan.git
cd PostScan
```

### 2. Python-Umgebung einrichten

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Systempakete installieren

```bash
brew install ocrmypdf tesseract tesseract-lang poppler
```

### 4. Ollama & Modell laden

```bash
# Ollama installieren (falls noch nicht vorhanden)
brew install ollama

# Ollama-Dienst starten
ollama serve &

# Modell herunterladen (~2 GB)
ollama pull phi3:mini
```

> Alternativ: Im Tab **„KI-Einrichtung"** den Status prüfen und Ollama/phi3:mini direkt aus der App heraus einrichten.

### 5. App starten

```bash
python main.py
```

---

## Verwendung

1. **PDF öffnen** – Klick auf „PDF öffnen …" (öffnet standardmäßig `eingang/`) oder per Drag & Drop
2. **Warteschlange** – Mehrere Dateien gleichzeitig laden; Ergebnisse werden im Hintergrund vorberechnet und zwischengespeichert
3. **Felder prüfen** – Alle Felder sind editierbar; bei mehreren erkannten Datumsangaben Dropdown nutzen
4. **Datumskurzeingabe** – Datum ohne Trennzeichen eingeben, Tab/Enter normalisiert automatisch:
   - `10` → `10.MM.JJ` (aktueller Monat & Jahr)
   - `1026` → `10.02.26`
   - `10526` → `10.05.26`
   - `11125` → Dropdown: `01.11.25` oder `11.01.25`
5. **Bestätigen** – Startet im Hintergrund:
   - Stammdaten lernen (`stammdaten.json`)
   - XMP-Metadaten ins PDF schreiben
   - Datei am Originalort umbenennen

### Stammdaten-Tab

Unter **„Stammdaten"** können bekannte Kombinationen (Dokumenttyp / Absender / Personenbezug) eingesehen, bearbeitet und gelöscht werden. Neue Einträge entstehen automatisch beim Bestätigen.

### KI-Einrichtung-Tab

Zeigt den Status von Ollama-Installation, Ollama-Dienst und phi3:mini-Modell mit farbigen Indikatoren. Über „Einrichten" kann das Modell direkt aus der App geladen werden.

---

## Verzeichnisstruktur

```
PostScan/
├── main.py              # PyQt6 GUI (QThreads: AnalyzeWorker, ConfirmWorker)
├── pipeline.py          # Hybrid-Extraktion: OCR → Regex → TF-IDF → Fuzzy → LLM
├── database.py          # JSON-CRUD für stammdaten.json
├── requirements.txt     # Python-Abhängigkeiten
├── .gitignore           # eingang/, stammdaten.json ausgeschlossen
│
├── eingang/             # (gitignored) PDFs hier ablegen
└── stammdaten.json      # (gitignored) Lernende Datenbank
```

---

## Konfiguration

`stammdaten.json` wird beim ersten Start automatisch mit Beispieleinträgen angelegt und ist **gitignored** – bleibt lokal auf dem System.

Beispielinhalt:
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
| `ocrmypdf: command not found` | `brew install ocrmypdf` |
| `pdftotext: command not found` | `brew install poppler` |
| OCR-Ergebnis leer | `brew install tesseract tesseract-lang` |
| Ollama antwortet nicht | `ollama serve` in separatem Terminal starten |
| `phi3:mini` nicht gefunden | `ollama pull phi3:mini` oder KI-Einrichtung-Tab nutzen |
| PyQt6 Import-Fehler | `.venv` aktiv? `source .venv/bin/activate` |
| XMP-Fehler beim Schreiben | PDF schreibgeschützt oder in anderer App geöffnet |

---

## Technische Details

- **RAM-Optimierung:** `keep_alive: 0` im Ollama-Request entlädt das LLM-Modell sofort nach Verwendung
- **Fast-Lane:** Bei TF-IDF-Konfidenz > 85 % + erkanntem Datum wird weder Fuzzy noch LLM aufgerufen
- **Fuzzy-Lane:** `rapidfuzz.fuzz.partial_ratio` – robust gegen OCR-Fehler, Ligaturen und Umstellungen; Schwelle 80 %
- **LLM-Eingabe:** Auf 810 Zeichen begrenzt für schnelle Antwortzeit
- **Digitale PDFs:** via `pdftotext` extrahiert – kein OCR-Overhead
- **Gescannte PDFs:** `ocrmypdf --skip-text --pages 1-2` – nur erste 2 Seiten
- **TF-IDF:** Char-N-Gram (2–4) – sprachunabhängig, robust gegenüber Tippfehlern
- **Selbstlernen:** Nach LLM-Klassifikation werden unbekannte Typen/Absender direkt in `stammdaten.json` geschrieben, sodass künftige Dokumente via Fast-Lane oder Fuzzy erkannt werden
