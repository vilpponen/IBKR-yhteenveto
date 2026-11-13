#!/usr/bin/env bash
# IBKR-yhteenveto — käynnistys macOS/Linux:  ./run.sh   (avaa http://127.0.0.1:8501, lopeta Ctrl+C)
#
# Mitä skripti tekee (jokainen komento tulostetaan '+'-merkillä):
#   1. tarkistaa python3:n (3.10+)
#   2. luo yksityisen virtuaaliympäristön ./.venv (mitään ei asenneta järjestelmään)
#   3. asentaa lukitun requirements.txt:n (pdfplumber, openpyxl; tiivisteet tarkistetaan) — vain jos ei jo asennettu;
#      keskeytynyt asennus jatkuu automaattisesti
#   4. käynnistää paikallisen palvelimen (server.py, vain Pythonin standardikirjasto)
# Poisto: poista .venv-kansio.

set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
set -x

step "1/4  Python"
command -v python3
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ vaaditaan"; print(sys.version)'

step "2/4  Virtuaaliympäristö (.venv)"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
else
  echo ".venv on jo olemassa — käytetään sitä"
fi

step "3/4  Riippuvuudet (requirements.txt)"
grep -E '^[a-zA-Z]' requirements.txt | sed 's/ \\$//'
if [ -f .venv/.install-complete ] && cmp -s requirements.txt .venv/.install-complete; then
  echo "Riippuvuudet jo asennettu — ohitetaan (poista .venv pakottaaksesi uudelleenasennuksen)"
else
  # lukitut versiot ja SHA-256-tiivisteet: pip asentaa vain täsmälleen nämä paketit (62N-97)
  .venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r requirements.txt
  .venv/bin/python -c "import pdfplumber, openpyxl; print('imports OK')"
  cp requirements.txt .venv/.install-complete
fi
.venv/bin/python -m pip list --format=columns | grep -iE '^(pdfplumber|openpyxl) '

step "4/4  Käynnistetään http://127.0.0.1:8501  (Ctrl+C lopettaa)"
exec .venv/bin/python server.py "$@"
