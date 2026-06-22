#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " PostScan Builder – macOS"
echo "============================================================"
echo

# ── Homebrew prüfen ──────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "[FEHLER] Homebrew nicht gefunden."
    echo "Installation: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "[OK] Homebrew gefunden"

# ── Python prüfen ────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[FEHLER] Python 3 nicht gefunden. Installation: brew install python"
    exit 1
fi
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
echo "[OK] Python $PY_VER"

# ── Systemabhängigkeiten ──────────────────────────────────────
echo "[1/4] Prüfe/installiere Systemabhängigkeiten..."
for pkg in tesseract ghostscript poppler; do
    if brew list "$pkg" &>/dev/null; then
        echo "      [OK] $pkg"
    else
        echo "      Installiere $pkg..."
        brew install "$pkg"
    fi
done

# ── Virtuelle Umgebung ────────────────────────────────────────
if [ ! -d "build_venv_mac" ]; then
    echo "[2/4] Erstelle virtuelle Umgebung..."
    python3 -m venv build_venv_mac
else
    echo "[2/4] Virtuelle Umgebung vorhanden"
fi

source build_venv_mac/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r macos/requirements.txt

# ── PyInstaller Build ─────────────────────────────────────────
echo "[3/4] Baue App mit PyInstaller..."
rm -rf dist build
pyinstaller macos/PostScan.spec

# ── DMG erstellen ─────────────────────────────────────────────
echo "[4/4] Erstelle DMG..."
hdiutil create \
    -volname "PostScan" \
    -srcfolder dist/PostScan.app \
    -ov -format UDZO \
    dist/PostScan.dmg

echo
echo "============================================================"
echo " Fertig! DMG: dist/PostScan.dmg"
echo "============================================================"
