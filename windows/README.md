# PostScan – Windows Installation

## Voraussetzungen

Bevor PostScan unter Windows gestartet werden kann, müssen folgende Programme installiert sein:

- **Tesseract OCR** – für die Texterkennung in gescannten PDFs  
  Download: https://github.com/UB-Mannheim/tesseract/wiki  
  Sprache: Deutsch (`deu`) bei der Installation auswählen

- **Ghostscript** – wird von ocrmypdf benötigt  
  Download: https://www.ghostscript.com/releases/gsdnld.html

- **Poppler** (pdftotext) – für die PDF-Textextraktion  
  Download: https://github.com/oschwartz10612/poppler-windows/releases  
  Nach dem Entpacken den `bin/`-Ordner zur PATH-Umgebungsvariable hinzufügen.

- **Ollama** (optional, für lokale KI) – https://ollama.com  
  Nach der Installation: `ollama pull gemma2:9b`

## Installation

1. `PostScan-Setup.exe` herunterladen (aus den GitHub Actions Artifacts oder von der Releases-Seite)
2. Installer ausführen und Anweisungen folgen
3. PostScan über das Desktop-Symbol oder Startmenü starten

## Selbst bauen

```powershell
# Python-Abhängigkeiten installieren
pip install -r windows/requirements.txt

# PyInstaller-Build
pyinstaller windows/PostScan.spec

# Inno Setup Installer erstellen (Inno Setup muss installiert sein)
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" windows\installer.iss
```

## Automatischer Build via GitHub Actions

Der Branch `windows` enthält eine GitHub Actions Workflow-Datei (`.github/workflows/build-windows.yml`).  
Bei jedem Push auf den `windows`-Branch wird automatisch ein Windows-Installer gebaut und als Artifact bereitgestellt.

## Unterschiede zur macOS-Version

- macOS-Finder-Tags (`com.apple.metadata:_kMDItemUserTags`) sind unter Windows nicht verfügbar und werden übersprungen.
- Das `.command`-Startskript (`PostScan starten.command`) ist macOS-spezifisch und nicht für Windows gedacht.
