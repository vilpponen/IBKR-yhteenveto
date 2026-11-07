# IBKR-yhteenveto

Interactive Brokersin (IBKR) vuosiraportit Suomen verotukseen — **osakeyhtiölle** kirjanpito ja EVL-verolaskelma,
**yksityishenkilölle** OmaVeroon ilmoitettavat pääomatulot. Tulos on Excel-työkirja, jossa kaikki luvut ovat
kaavoja ja jokainen erä on jäljitettävissä IBKR:n raporttiin.

Sovellus toimii **paikallisesti omalla koneellasi** (Pythonin oma web-palvelin, `127.0.0.1`). Raportteja ei lähetetä
minnekään, eikä sivu lataa mitään internetistä.

> ⚠️ **Ei veroneuvontaa.** Työkalu tekee laskelman ja näyttää perusteet, mutta tulkinnat (esim. omaisuuslaji,
> lähdeverojen hyvitys) kannattaa vahvistaa kirjanpitäjältä tai Verohallinnosta. Säännöt: verovuodet 2025–2026.

---

## Käyttöönotto

### 1. Asenna Python 3.10 tai uudempi

* **macOS:** asenna python.org:sta (https://www.python.org/downloads/) tai `brew install python`.
  Tarkista Päätteessä (Terminal): `python3 --version`. macOS:n mukana tuleva `python3` (Xcode Command Line Tools) on
  usein 3.9 — se on liian vanha.
* **Windows:** asenna python.org:sta ja ruksi asennuksessa **"Add python.exe to PATH"**.
  Tarkista PowerShellissä: `py --version`.

### 2. Lataa ja käynnistä (ilman GitHub-tunnusta tai gitiä)

**macOS** — avaa Pääte (Terminal). Luo sovellukselle oma kansio, siirry siihen ja aja asennus
(esimerkissä `Documents/IBKR-yhteenveto`; kansion paikan ja nimen voi valita vapaasti):

```bash
mkdir -p ~/Documents/IBKR-yhteenveto
cd ~/Documents/IBKR-yhteenveto
curl -fsSL https://raw.githubusercontent.com/vilpponen/IBKR-yhteenveto/main/install.sh | bash
```

Komento lataa sovelluksen tähän kansioon, asentaa riippuvuudet sen sisään (`.venv`) ja avaa selaimen. Mitään ei
asennu kansion ulkopuolelle. Skriptin voi lukea ennen ajoa: [install.sh](install.sh).

**Seuraavilla kerroilla** sama kansio + sama komento — se päivittää uusimpaan versioon ja käynnistää:

```bash
cd ~/Documents/IBKR-yhteenveto
curl -fsSL https://raw.githubusercontent.com/vilpponen/IBKR-yhteenveto/main/install.sh | bash
```

(Ilman päivitystä: `cd ~/Documents/IBKR-yhteenveto && bash run.sh`.) Poisto: poista kansio.
Jos komennon ajaa kansiossa, jossa on jo muita tiedostoja (esim. kotikansio), sovellus asennetaan sen alikansioon
`IBKR-yhteenveto`.

**Windows 10/11** — avaa PowerShell (Käynnistä-valikko → kirjoita *PowerShell*). Luo sovellukselle oma kansio,
siirry siihen ja aja asennus:

```powershell
mkdir -Force $HOME\IBKR-yhteenveto
cd $HOME\IBKR-yhteenveto
irm https://raw.githubusercontent.com/vilpponen/IBKR-yhteenveto/main/install.ps1 | iex
```

Kansio kannattaa luoda kotikansioon (`C:\Users\<nimi>\IBKR-yhteenveto`) eikä OneDriven synkronoimaan *Tiedostot*-kansioon.
Toiminta on sama kuin macOS:ssä: lataus tähän kansioon, riippuvuudet `.venv`:iin, selain aukeaa. Skriptin voi lukea
ennen ajoa: [install.ps1](install.ps1).

**Seuraavilla kerroilla:** kaksoisklikkaa kansion **`run.cmd`** (käynnistää ilman päivitystä), tai päivitä ja
käynnistä samalla komennolla:

```powershell
cd $HOME\IBKR-yhteenveto
irm https://raw.githubusercontent.com/vilpponen/IBKR-yhteenveto/main/install.ps1 | iex
```

Selain aukeaa osoitteeseen http://127.0.0.1:8501. Lopetus: **Ctrl+C** pääteikkunassa (tai sulje ikkuna).
Poisto: poista kansio — mitään ei asennu sen ulkopuolelle.

**Ilman komentoriviä:** GitHub-sivulla **Code → Download ZIP**, pura zip ja käynnistä kansiosta `bash run.sh`
(macOS, Päätteessä) tai kaksoisklikkaa `run.cmd` (Windows; jos Windows kysyy, valitse *Suorita*).
Päivitys: lataa ja pura uusi zip.

### Gitin käyttäjille

```bash
git clone https://github.com/vilpponen/IBKR-yhteenveto.git
cd IBKR-yhteenveto
./run.sh          # luo .venv:n, asentaa pdfplumber + openpyxl, avaa http://127.0.0.1:8501
```

Päivitys: `git pull`.

### Komentorivi ilman selainta

```bash
.venv/bin/python -m ibkr_yhteenveto raportti.csv raportti.pdf -o tulos.xlsx
```

## Mitkä raportit IBKR:stä

| Raportti | Mistä | Antaa |
|---|---|---|
| **Activity Statement, CSV** | Portal → Performance & Reports → Statements → Activity → Annual / Custom → CSV | Change in NAV -tarkistukset, transaktioverot (FTT), kaikki rahaliikenne |
| **Realized Summary tai Activity Statement, PDF** | sama, PDF | Kauppakohtaiset EUR-määrät (*Forex P/L Details*) — tarvitaan henkilön FIFO-laskentaan |

Pudota saman tilin ja kauden raportit yhdessä — ne yhdistetään (CSV:stä tarkistukset, PDF:stä tarkat kauppakurssit).

## Osakeyhtiö (Oy)

* **Tulos ilman tasauseriä:** taloudellinen tulos = NAV loppu − NAV alku − nettosiirrot. Eritellyt erät (osingot,
  lähdeverot, korot bruttona, jaksotukset, kulut, FTT) vähennetään → kaupankäynnin tulos, joka jaetaan R&U-raportin
  luovutusvoittoihin/-tappioihin ja johdettuun valuuttakurssieroon. IBKR:n R&U *Forex* -riviä ei kirjata
  (EUR-perusvaluuttatilillä se on jo osaketuloksessa — muuten tulisi tuplakirjaus).
* **Alin arvo (KPL 5:6):** realisoitumaton tappio = arvonalentuminen, voittoa ei kirjata.
* **Tase** IBKR:n NAV-riveistä, tilikartta debet = kredit, täsmäytys NAV:iin sentilleen.
* **EVL-täsmäytys (6B):** lähdeverot lisätään takaisin ja hyvitetään sopimusrajaan asti; *muun omaisuuden*
  arvonalentumiset lisätään takaisin; EVL 8 a §:n osaketappiorajoitus; omaisuuslaji valittavissa.
* **Siirrot:** talletukset/nostot yhtiön pankkitilin ja IBKR:n välillä (tili 1900); perutut nostot nettoutuvat.

## Yksityishenkilö

* **Arvopaperit (9A):** FIFO hankintaerittäin IBKR:n kauppakohtaisista EUR-määristä — myyntihinta myyntipäivän ja
  hankintameno ostopäivän kurssilla (Verohallinnon tapa). Luovutushinnat, hankintamenot, voitot ja tappiot.
* **Johdannaiset** (futuurit, optiot, CFD): voitot ja tappiot.
* **Ulkomaan pääomatulot (16B):** osingot (85 % veronalaista), lähdeveron hyvitys sopimusrajaan asti, korot.
* **Vähennykset:** marginaalilainan korot, IBKR-kulut, aiempien vuosien vahvistetut tappiot.
* **Pienten luovutusten verovapaus** (luovutushinnat ≤ 1 000 €), pääomatulovero 30 % / 34 % (> 30 000 €).
* Edellisvuosien erät, joiden ostokurssia raportissa ei ole, merkitään ja niiden hankintameno johdetaan IBKR:n
  realisoidusta tuloksesta.

## Tarkistukset

Työkirja ja näkymä näyttävät, täsmääkö laskelma IBKR:n omiin lukuihin (Change in NAV): osingot, lähdeverot, korot,
kulut, provisiot, siirrot, kaupankäynnin tulos ja NAV. Kaikkien erotusten pitää olla 0.

## Kehitys

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests            # julkiset testit (keksitty esimerkkiaineisto)
python scripts/check_private.py             # estää tilinumerot, PDF/XLSX:t ja oikeat CSV:t repossa
ln -sf ../../scripts/check_private.py .git/hooks/pre-commit
```

Omia raportteja vastaan voi testata paikallisesti (`tests/test_local_real.py`, ympäristömuuttujat). **Älä koskaan
commitoi oikeita raportteja** — `.gitignore` ja `check_private.py` estävät sen. Lisää omat nimesi tms. tiedostoon
`.private-words` (ei versionhallinnassa), niin tarkistus estää myös ne.

Rakenne: `ibkr_yhteenveto/` (parserit, laskenta, Excel), `server.py` (paikallinen palvelin), `static/index.html` (UI).

---

## English

Local tool that turns Interactive Brokers statements (PDF/CSV) into Finnish tax figures: bookkeeping (KPL) and
the EVL tax bridge for a Finnish limited company, or OmaVero capital-income figures for an individual (FIFO at
trade-date EUR rates). Runs on `127.0.0.1` with Python's standard-library HTTP server; nothing leaves your machine.
`./run.sh` to start. Not tax advice. MIT licence.
