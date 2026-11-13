#!/usr/bin/env bash
# Lukitsee riippuvuudet: tarkat versiot ja SHA-256-tiivisteet kaikille alustoille (macOS, Windows, Linux) ja
# Python-versioille 3.10–3.14. Asennus tarkistaa tiivisteet (pip install --require-hashes).
#
# Aja julkaisun valmistelussa (päivittää uusimpiin sallittuihin versioihin) ja liitä muutos PR:ään:
#   bash scripts/lock_deps.sh            # päivitä uusimpiin
#   bash scripts/lock_deps.sh --keep     # vain tarkista/muodosta nykyisillä versioilla
# Vaatii uv:n (https://docs.astral.sh/uv/). Uutta riippuvuutta ei lisätä ilman tätä lukitusta.
set -euo pipefail
cd "$(dirname "$0")/.."
up="--upgrade"; [ "${1:-}" = "--keep" ] && up=""
common=(--universal --python-version 3.10 --generate-hashes --no-header --quiet $up)
uv pip compile "${common[@]}" requirements.in -o requirements.txt
uv pip compile "${common[@]}" requirements-dev.in -o requirements-dev.txt
for f in requirements.txt requirements-dev.txt; do
  { printf '# LUKITTU — älä muokkaa käsin. Muodostettu: bash scripts/lock_deps.sh (lähde %s)\n' "${f%.txt}.in"; cat "$f"; } > "$f.tmp"
  mv "$f.tmp" "$f"
done
echo "OK: requirements.txt ja requirements-dev.txt lukittu."
grep -E '^[a-zA-Z]' requirements.txt
