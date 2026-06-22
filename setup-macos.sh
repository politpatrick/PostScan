#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " PostScan – Ersteinrichtung macOS"
echo " Dieser Schritt ist nur einmalig notwendig."
echo "============================================================"
echo

# ── Homebrew ─────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "[!] Homebrew nicht gefunden. Installation:"
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo "    Danach dieses Skript erneut ausfuehren."
    exit 1
fi
echo "[OK] Homebrew gefunden"

# ── Systemabhängigkeiten ──────────────────────────────────────
echo "[1/2] Prüfe/installiere Systemabhängigkeiten..."
for pkg in tesseract ghostscript poppler; do
    if brew list "$pkg" &>/dev/null; then
        echo "      [OK] $pkg"
    else
        echo "      Installiere $pkg..."
        brew install "$pkg"
    fi
done

# ── Python-Umgebung ───────────────────────────────────────────
echo "[2/2] Erstelle virtuelle Umgebung und installiere Pakete..."
if [ -d ".venv" ]; then
    echo "      Bereits vorhanden – wird aktualisiert."
else
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo
echo "============================================================"
echo " Einrichtung abgeschlossen!"
echo " Starte PostScan mit:  'PostScan starten.command'"
echo "============================================================"
