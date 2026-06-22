@echo off
setlocal enabledelayedexpansion
title PostScan Build – Windows

echo ============================================================
echo  PostScan Builder – Windows
echo ============================================================
echo.

:: ── Python prüfen ────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python nicht gefunden.
    echo Bitte Python 3.11+ von https://python.org installieren.
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

:: ── Tesseract prüfen ─────────────────────────────────────────
where tesseract >nul 2>&1
if errorlevel 1 (
    echo [WARNUNG] Tesseract nicht gefunden. OCR wird nicht funktionieren.
    echo Download: https://github.com/UB-Mannheim/tesseract/wiki
) else (
    echo [OK] Tesseract gefunden
)

:: ── Ghostscript prüfen ───────────────────────────────────────
where gswin64c >nul 2>&1
if errorlevel 1 (
    where gswin32c >nul 2>&1
    if errorlevel 1 (
        echo [WARNUNG] Ghostscript nicht gefunden.
        echo Download: https://www.ghostscript.com/releases/gsdnld.html
    ) else (
        echo [OK] Ghostscript gefunden
    )
) else (
    echo [OK] Ghostscript gefunden
)

:: ── Inno Setup prüfen ────────────────────────────────────────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
    echo [OK] Inno Setup gefunden
) else (
    echo [FEHLER] Inno Setup nicht gefunden.
    echo Download: https://jrsoftware.org/isdl.php
    pause & exit /b 1
)

echo.

:: ── Virtuelle Umgebung ───────────────────────────────────────
if not exist "build_venv_win\" (
    echo [1/4] Erstelle virtuelle Umgebung...
    python -m venv build_venv_win
) else (
    echo [1/4] Virtuelle Umgebung vorhanden
)

echo [2/4] Installiere Python-Abhängigkeiten...
call build_venv_win\Scripts\activate.bat
pip install --quiet --upgrade pip
pip install --quiet -r windows\requirements.txt
if errorlevel 1 (
    echo [FEHLER] pip install fehlgeschlagen.
    pause & exit /b 1
)

:: ── PyInstaller Build ─────────────────────────────────────────
echo [3/4] Baue App mit PyInstaller...
if exist dist\ rmdir /s /q dist
if exist build\ rmdir /s /q build
pyinstaller windows\PostScan.spec
if errorlevel 1 (
    echo [FEHLER] PyInstaller fehlgeschlagen.
    pause & exit /b 1
)

:: ── Inno Setup Installer ─────────────────────────────────────
echo [4/4] Erstelle Installer mit Inno Setup...
"%ISCC%" windows\installer.iss
if errorlevel 1 (
    echo [FEHLER] Inno Setup fehlgeschlagen.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Fertig! Installer: windows\PostScan-Setup.exe
echo ============================================================
pause
