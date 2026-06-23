@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion
title PostScan – Ersteinrichtung

echo ============================================================
echo  PostScan – Ersteinrichtung
echo  Dieser Schritt ist nur einmalig notwendig.
echo ============================================================
echo.

:: ── Python prüfen ────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [!] Python nicht gefunden.
    echo.
    echo Bitte Python 3.11 oder neuer installieren:
    echo   winget install Python.Python.3.12
    echo   oder: https://python.org/downloads
    echo.
    echo Danach dieses Skript erneut ausfuehren.
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

:: ── Tesseract prüfen ─────────────────────────────────────────
where tesseract >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] Tesseract OCR fehlt – wird fuer die Texterkennung benoetigt.
    echo     Download (64-bit Installer, Sprache "German" auswaehlen):
    echo     https://github.com/UB-Mannheim/tesseract/wiki
    echo.
    echo     Nach der Installation dieses Skript erneut ausfuehren.
    pause & exit /b 1
)
echo [OK] Tesseract gefunden

:: ── Ghostscript prüfen ───────────────────────────────────────
where gswin64c >nul 2>&1 || where gswin32c >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] Ghostscript fehlt – wird fuer die PDF-Verarbeitung benoetigt.
    echo     Download: https://www.ghostscript.com/releases/gsdnld.html
    echo.
    echo     Nach der Installation dieses Skript erneut ausfuehren.
    pause & exit /b 1
)
echo [OK] Ghostscript gefunden

:: ── Poppler / pdftotext prüfen ───────────────────────────────
where pdftotext >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] Poppler (pdftotext) fehlt.
    echo     Download: https://github.com/oschwartz10612/poppler-windows/releases
    echo     Den Inhalt entpacken und den bin\-Ordner zur PATH-Variable hinzufuegen.
    echo.
    echo     Nach der Installation dieses Skript erneut ausfuehren.
    pause & exit /b 1
)
echo [OK] Poppler gefunden

echo.
echo [1/2] Erstelle virtuelle Umgebung...
if exist ".venv\" (
    echo       Bereits vorhanden – wird aktualisiert.
) else (
    python -m venv .venv
)

echo [2/2] Installiere Python-Pakete...
call .venv\Scripts\activate.bat
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pywin32>=306
if errorlevel 1 (
    echo [FEHLER] Installation fehlgeschlagen. Bitte Fehlermeldung oben pruefen.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Einrichtung abgeschlossen!
echo  Starte PostScan mit:  start-windows.bat
echo ============================================================
pause
