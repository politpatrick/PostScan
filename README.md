# PostScan

macOS-Tool zur automatischen Analyse und Archivierung von Eingangspost als PDF.

## Funktionsweise

1. PDF öffnen → OCR (ocrmypdf) → Datum via Regex extrahieren
2. TF-IDF Klassifikation gegen Stammdaten (schnell, lokal)
3. Bei Unsicherheit: LLM-Fallback via Ollama (phi3:mini)
4. Felder manuell korrigieren → Bestätigen
5. XMP-Metadaten schreiben + Datei in `archiv/` verschieben

**Dateiname-Schema:** `[Dokumenttyp]_[Absender]_[Datum]_[Personenbezug].pdf`  
**Datumsformat:** `vDD.MM.YY` (z.B. `v21.06.26`)

## Voraussetzungen

- Python 3.10+
- [Ollama](https://ollama.com) mit `phi3:mini` Modell
- ocrmypdf (über Homebrew: `brew install ocrmypdf`)
- pdftotext (über `brew install poppler`)

## Installation

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Ollama-Modell laden
ollama pull phi3:mini

# App starten
python main.py
```

## Verzeichnisstruktur

```
PostScan/
├── eingang/          # PDFs hier ablegen (gitignored)
├── archiv/           # Archivierte Dokumente (gitignored)
├── stammdaten.json   # Lernende Datenbank (gitignored)
├── main.py           # GUI (PyQt6)
├── pipeline.py       # OCR + Extraktion
├── database.py       # Stammdaten-CRUD
└── requirements.txt
```

## GitHub Sync

```bash
git add .
git commit -m "Update"
git push origin main
```

> `stammdaten.json`, `eingang/` und `archiv/` sind bewusst gitignored.
