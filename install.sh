#!/usr/bin/env bash
# IBKR-yhteenveto — asennus/päivitys + käynnistys yhdellä komennolla (macOS/Linux):
#
#   curl -fsSL https://raw.githubusercontent.com/vilpponen/IBKR-yhteenveto/main/install.sh | bash
#
# Mitä skripti tekee:
#   1. tarkistaa, että python3 (3.10+), curl ja unzip löytyvät — mitään ei asenneta järjestelmään
#   2. lataa uusimman version zip-pakettina GitHubista väliaikaiskansioon
#   3. asentaa sen kansioon, jossa komento ajetaan (suositus: luo ensin tyhjä kansio ja siirry siihen):
#        - jos nykyinen kansio on tyhjä → asentaa siihen
#        - jos nykyinen kansio on jo IBKR-yhteenveto → päivittää sen
#        - muuten (esim. kotikansio) luo/päivittää alikansion ./IBKR-yhteenveto
#      (.venv ja kansioon itse tallentamasi tiedostot säilyvät päivityksessä)
#   4. käynnistää run.sh:n → http://127.0.0.1:8501 (lopetus Ctrl+C)
#
# Saman komennon voi ajaa uudelleen samassa paikassa milloin tahansa: se päivittää ja käynnistää.
# Asetukset: IBKR_DIR=<kansio> (ohittaa yllä olevan), IBKR_ZIP_URL=<zip-osoite>.
# Poisto: poista IBKR-yhteenveto-kansio.

# Koko skripti on funktiossa, jotta bash lukee sen kokonaan ennen ajoa (turvallinen "curl | bash").
main() {
  set -euo pipefail
  local dir
  if [ -n "${IBKR_DIR:-}" ]; then
    dir="$IBKR_DIR"
  elif [ -f "$PWD/server.py" ] && [ -d "$PWD/ibkr_yhteenveto" ]; then
    dir="$PWD"                        # ajettu sovelluskansion sisällä → päivitä se
  elif [ -z "$(ls -A "$PWD" 2>/dev/null | grep -v '^\.DS_Store$')" ]; then
    dir="$PWD"                        # tyhjä kansio → asenna suoraan siihen
  else
    dir="$PWD/IBKR-yhteenveto"        # muuten alikansio tähän
  fi
  local url="${IBKR_ZIP_URL:-https://github.com/vilpponen/IBKR-yhteenveto/archive/refs/heads/main.zip}"
  say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
  die() { printf '\n\033[1;31mVirhe: %s\033[0m\n' "$*" >&2; exit 1; }

  say "1/4  Tarkistetaan python3, curl ja unzip"
  command -v curl >/dev/null || die "curl puuttuu."
  command -v unzip >/dev/null || die "unzip puuttuu."
  if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    die "Tarvitaan Python 3.10 tai uudempi (nyt: $(python3 --version 2>&1 || echo 'ei löydy')).
Asenna osoitteesta https://www.python.org/downloads/ (tai: brew install python), avaa uusi Pääte-ikkuna
ja aja sama komento uudelleen."
  fi
  python3 --version

  say "2/4  Ladataan $url"
  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fL --progress-bar -o "$tmp/app.zip" "$url" || die "Lataus epäonnistui: $url"
  unzip -q "$tmp/app.zip" -d "$tmp/x"
  local src; src="$(find "$tmp/x" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [ -f "$src/run.sh" ] && [ -f "$src/server.py" ] || die "Ladattu paketti ei ole IBKR-yhteenveto."

  if [ -f "$dir/server.py" ] || [ -n "$(ls -A "$dir" 2>/dev/null | grep -v '^\.DS_Store$')" ]; then
    [ -f "$dir/server.py" ] || die "$dir on olemassa, mutta se ei ole IBKR-yhteenveto-kansio. Aja komento toisessa kansiossa."
    say "3/4  Päivitetään $dir"
    rm -rf "$dir/ibkr_yhteenveto" "$dir/static"   # vain ohjelmakoodi — vanhentuneet tiedostot pois
  else
    say "3/4  Asennetaan kansioon $dir"
    { mkdir -p "$dir" 2>/dev/null && [ -w "$dir" ]; } \
      || die "Kansioon $dir ei voi kirjoittaa. Luo kansio esim. kotikansioon: mkdir -p ~/IBKR-yhteenveto && cd ~/IBKR-yhteenveto"
  fi
  cp -R "$src/." "$dir/"

  say "4/4  Käynnistetään"
  cd "$dir"
  exec bash ./run.sh "$@"
}

main "$@"
