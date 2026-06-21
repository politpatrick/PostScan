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
    TF-IDF > 85% UND Datum klar? → Ergebnis direkt, kein LLM
    │
    ▼
[Step 4] LLM-Fallback (nur bei niedriger Konfidenz)
    phi3:mini via Ollama (lokal)
    RAG-Kontext aus stammdaten.json gegen Halluzinationen
    keep_alive: 0 → Modell wird sofort aus RAM entladen
    │
    ▼
[GUI] Felder prüfen & bestätigen
    a) stammdaten.json updaten (Real-Time Learning)
    b) XMP-Metadaten ins PDF schreiben (pikepdf)
    c) Datei umbenennen & in archiv/ verschieben
```

**Dateiname-Schema:** `[Dokumenttyp]_[Absender]_[vDD.MM.YY]_[Personenbezug].pdf`

Beispiel: `Rechnung_HUK-COBURG_v21.06.26_Kunze.pdf`

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

> **Hinweis:** `tesseract-lang` installiert alle Sprachpakete (~1 GB). Für nur Deutsch: `brew install tesseract` reicht, das Paket enthält `eng`. Deutsches Sprachpaket separat: `brew install tesseract-lang` oder manuell `deu.traineddata` nach `/opt/homebrew/share/tessdata/` kopieren.

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

# Modell herunterladen (~2 GB, lädt automatisch in RAM)
ollama pull phi3:mini
```

### 5. App starten

```bash
python main.py
```

---

## Verwendung

1. **PDF öffnen** – Klick auf „PDF öffnen …" (öffnet standardmäßig `eingang/`)
2. **Analyse** – Läuft automatisch im Hintergrund (QThread, GUI bleibt reaktiv)
3. **Felder prüfen** – Alle Felder sind editierbar; bei mehreren Datumsangaben Dropdown nutzen
4. **Konfidenz-Anzeige** – Zeigt ob Fast-Lane (TF-IDF) oder LLM-Fallback genutzt wurde
5. **Bestätigen** – Startet im Hintergrund:
   - Stammdaten lernen (stammdaten.json)
   - XMP-Metadaten ins PDF schreiben
   - Datei umbenennen & in `archiv/` ablegen

### Stammdaten-Tab

Unter **„Stammdaten"** können bekannte Kombinationen (Dokumenttyp / Absender / Personenbezug) eingesehen, bearbeitet und gelöscht werden. Neue Einträge entstehen automatisch beim Bestätigen.

---

## Verzeichnisstruktur

```
PostScan/
├── main.py              # PyQt6 GUI (QThreads: AnalyzeWorker, ConfirmWorker)
├── pipeline.py          # Hybrid-Extraktion: OCR → Regex → TF-IDF → LLM
├── database.py          # JSON-CRUD für stammdaten.json
├── requirements.txt     # Python-Abhängigkeiten
├── .gitignore           # eingang/, archiv/, stammdaten.json ausgeschlossen
│
├── eingang/             # (gitignored) PDFs hier ablegen
├── archiv/              # (gitignored) Archivierte Dokumente
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
| `phi3:mini` nicht gefunden | `ollama pull phi3:mini` |
| PyQt6 Import-Fehler | `.venv` aktiv? `source .venv/bin/activate` |
| XMP-Fehler beim Schreiben | PDF schreibgeschützt oder geöffnet → schließen |

---

## GitHub Sync

```bash
# Änderungen committen und pushen
git add main.py pipeline.py database.py requirements.txt
git commit -m "Update"
git push origin main
```

> `stammdaten.json`, `eingang/` und `archiv/` sind **bewusst gitignored** – sie enthalten persönliche Daten und sollen nicht ins Repository.

---

## Technische Details

- **RAM-Optimierung:** `keep_alive: 0` im Ollama-Request entlädt das LLM-Modell sofort nach Verwendung aus dem RAM
- **Fast-Lane:** Bei TF-IDF-Konfidenz > 85% + erkanntem Datum wird der LLM-Call komplett übersprungen
- **Digitale PDFs:** werden via `pdftotext` extrahiert – kein OCR-Overhead
- **Gescannte PDFs:** `ocrmypdf --skip-text --pages 1-2` – nur die ersten 2 Seiten, bereits vorhandener Text wird nicht neu verarbeitet
- **TF-IDF:** Char-N-Gram (2–4) gegen `stammdaten.json` – sprachunabhängig, robust gegenüber Tippfehlern
