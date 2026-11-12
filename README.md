# IBKR-yhteenveto

> **Kokeile heti selaimessa: [ibkr.arxsavonum.com](https://ibkr.arxsavonum.com)** — ei asennusta.
> Raportit käsitellään palvelimen muistissa vain laskennan ajan, eikä **mitään tallenneta**: ei tiedostoja, ei
> istuntoja, ei raporttien sisältöä lokeihin. Tulos ja Excel-työkirja pysyvät vain omassa selainikkunassasi.
> Jos raportti ei saa lähteä koneeltasi lainkaan, asenna sovellus omalle koneellesi ([Käyttöönotto](#käyttöönotto)).
> 
> **Tarvitset:** osakeyhtiö — IBKR:n Activity Statement **CSV**; yksityishenkilö — Activity Statement **CSV + PDF**
> samalta tililtä ja kaudelta ([lisää](#mitkä-raportit-ibkrstä)).

Interactive Brokersin (IBKR) vuosiraportit Suomen verotukseen — **osakeyhtiölle** kirjanpito ja EVL-verolaskelma,
**yksityishenkilölle** OmaVeroon ilmoitettavat pääomatulot. Tulos on Excel-työkirja, jossa kaikki luvut ovat
kaavoja ja jokainen erä on jäljitettävissä IBKR:n raporttiin.

Sovellus toimii **paikallisesti omalla koneellasi** (Pythonin oma web-palvelin, `127.0.0.1`). Raportteja ei lähetetä
minnekään, eikä sivu lataa mitään internetistä.

**Palvelin ei tallenna mitään.** Ei istuntoja, ei tiedostoja, ei väliaikaistiedostoja levylle: jokainen pyyntö
käsitellään muistissa ja unohdetaan, kun vastaus on lähetetty. Raportit, jäsennetty raportti ja Excel-työkirja
pysyvät vain selainikkunassa — sivun päivittäminen tai sulkeminen poistaa ne. Lokiin kirjataan vain pyynnön polku
(virheistä pelkkä virhetyyppi; tarkemmat tiedot vain `--debug`-tilassa). Tämä pätee myös, jos sovellus ajetaan
palvelimella muiden käyttöön; silloin sivu kertoo käyttäjälle, että raportit lähetetään palvelimelle laskentaa varten.

> ⚠️ **Ei veroneuvontaa.** Työkalu tekee laskelman ja näyttää perusteet, mutta tulkinnat (esim. omaisuuslaji,
> lähdeverojen hyvitys) kannattaa vahvistaa kirjanpitäjältä tai Verohallinnosta. Säännöt: verovuodet 2025–2026.

> ℹ️ **Kenelle työkalu sopii nyt.** Työkalu on tällä hetkellä tehty ensisijaisesti **aktiiviselle kaupankävijälle,
> jonka salkku on vuoden alussa tyhjä** (positiot avataan ja suljetaan saman vuoden aikana). Aiempina vuosina
> ostetuille erille sovellus kysyy käsittelytavan ([Vuoden alun positiot](#vuoden-alun-positiot)). Asetetut optiot
> (toteutusvelvoite, vuodenvaihde), yritystapahtumat (esim. splitit) ja kryptot ovat vielä rajallisesti tuettuja —
> laskelma varoittaa niistä. Työkalua kehitetään palautteen perusteella
> ([Palaute](#palaute)).

**Sisällysluettelo**

* [Käyttöönotto](#käyttöönotto)
* [Mitkä raportit IBKR:stä](#mitkä-raportit-ibkrstä)
* [Osakeyhtiö (Oy)](#osakeyhtiö-oy)
* [Yksityishenkilö](#yksityishenkilö)
* [Tarkistukset](#tarkistukset)
* [Palaute](#palaute)
* [Viimeisimmät muutokset](#viimeisimmät-muutokset)
* [Kehitys](#kehitys)
* [English](#english)

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

**Lyhyesti:** osakeyhtiölle riittää **Activity Statement CSV**. Yksityishenkilölle tarvitaan **CSV + PDF**
(saman tilin ja saman kauden Activity Statement molempina), jos tilillä on kauppoja muussa kuin euroissa.

| Kenelle | Vähintään | Suositus | Miksi |
|---|---|---|---|
| **Osakeyhtiö** | Activity Statement **CSV** | CSV (PDF ei muuta tulosta) | CSV:ssä on kaikki: NAV, Change in NAV -tarkistukset, R&U-tulokset, positiot, rahaliikenne ja transaktioverot (FTT) |
| **Yksityishenkilö** | Activity Statement **CSV** | **CSV + PDF** | Verohallinnon tapa vaatii jokaiselle kaupalle EUR-määrän kauppapäivän kurssilla. Ne ovat vain PDF:n *Forex P/L Details* -osiossa. Pelkällä CSV:llä valuuttamääräiset kaupat muunnetaan keskikurssilla (työkalu varoittaa) — testiaineistossa pääomatulo oli noin 3 % liian suuri. Jos kaikki kaupat ovat euroissa, CSV riittää. |

**Aiempina vuosina ostetut osakkeet (yksityishenkilö):** lisää samaan latauslaatikkoon myös edellisten vuosien
Activity Statementit (CSV + PDF). Uusin kausi lasketaan, ja aiemmista luetaan ostoerät EUR-määrineen.

Pelkkä PDF toimii myös, mutta siitä puuttuvat IBKR:n Change in NAV -tarkistukset (laskelman täsmäytys IBKR:n
omiin lukuihin), ja *Realized Summary* -PDF:stä lisäksi transaktioverot.

**Näin lataat raportit:** IBKR Portal → **Performance & Reports → Statements → Activity**
→ jakso **Annual** (tai *Custom*: 1.1.–31.12.) → muoto **CSV**, ja yksityishenkilölle sama uudelleen muodossa
**PDF**. Valitse molempiin sama tili ja sama jakso.

Pudota tiedostot sovellukseen yhdessä — ne yhdistetään (CSV:stä tarkistukset ja rahaliikenne, PDF:stä tarkat
kauppakohtaiset EUR-määrät). Sovellus näyttää ennen laskentaa, mitä raporteista löytyi ja mitä puuttuu.

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
* **Johdannaiset** (futuurit, optiot): voitot ja tappiot.
* **Optioiden toteutus:** ostetun osto-option preemio lisätään saatujen osakkeiden hankintamenoon ja ostetun
  myyntioption preemio vähennetään osakkeiden luovutushinnasta (KHO 2012:69). Tarvitsee Activity Statement CSV:n.
* **CFD:t:** voitot kauppakohtaisesti muuna pääomatulona; tappiot eivät ole vähennyskelpoisia, joten niitä ei
  huomioida (Verohallinto). Kauppakohtainen erittely tarvitsee Activity Statement CSV:n.
* **Ulkomaan pääomatulot (16B):** osingot (85 % veronalaista), lähdeveron hyvitys sopimusrajaan asti, korot.
* **Vähennykset:** marginaalilainan korot, IBKR-kulut, aiempien vuosien vahvistetut tappiot.
* **Hankintameno-olettama** erittäin: 20 % (40 %, jos omistettu vähintään 10 vuotta) bruttomyyntihinnasta, kun se
  antaa pienemmän voiton kuin todelliset kulut; ei koskaan synnytä tappiota. Voi kytkeä pois asetuksista.
* **Pienten luovutusten verovapaus** (luovutushinnat ≤ 1 000 €), pääomatulovero 30 % / 34 % (> 30 000 €).
* **Vuoden alun positiot:** katso alta.

### Vuoden alun positiot

Jos tänä vuonna myydään osakkeita, jotka on ostettu ennen raportin kautta, hankintameno puuttuu raportista.
Sovellus ei täydennä sitä hiljaa, vaan kysyy ennen tuloksia jokaiselle osakkeelle käsittelytavan:

1. **Edellisen vuoden IBKR-raportti** — lisää se latauslaatikkoon; erät luetaan siitä automaattisesti (FIFO).
2. **Alkuperäiset ostotiedot** — ostopäivä ja hankintameno euroina.
3. **Hankintameno-olettama** — 20 % luovutushinnasta (40 %, jos omistettu vähintään 10 vuotta); vaatii ostopäivän.
4. **IBKR:n luku** — hankintameno johdetaan IBKR:n realisoidusta tuloksesta; merkitään työkirjaan.

Valinnat voi viedä ja tuoda JSON-tiedostona, ja tulossivulta saa vuoden lopun avoimet erät JSON-tiedostona ensi
vuoden laskelmaa varten. *Laske silti* näyttää tulokset keskeneräisiksi merkittyinä. Valinnat pysyvät vain
selaimessa.

## Tarkistukset

Työkirja ja näkymä näyttävät, täsmääkö laskelma IBKR:n omiin lukuihin (Change in NAV): osingot, lähdeverot, korot,
kulut, provisiot, siirrot, kaupankäynnin tulos ja NAV. Kaikkien erotusten pitää olla 0.

## Palaute

Virheilmoitukset ja parannusehdotukset:

* **[GitHub Issues](https://github.com/vilpponen/IBKR-yhteenveto/issues/new/choose)** — valmiit lomakkeet
  virheilmoitukselle ja parannusehdotukselle. Ilmoitukset ovat julkisia.
* **Sähköposti: [info@arxsavonum.com](mailto:info@arxsavonum.com?subject=IBKR-yhteenveto%20-%20palaute)** — jos
  sinulla ei ole GitHub-tunnusta tai asia on yksityinen.

⚠️ **Älä liitä oikeita IBKR-raportteja, tilinumeroita, nimiä tai summia** — et issueihin, kuvakaappauksiin etkä
sähköpostiin. Kuvaile ongelma yleisellä tasolla tai muuta luvut keksityiksi.
Tietoturvaongelmat ilmoitetaan yksityisesti: katso [SECURITY.md](SECURITY.md).

## Viimeisimmät muutokset

Sovelluksen versio näkyy otsikossa ja jokaisessa Excel-työkirjassa (`MAJOR.MINOR.PATCH`). Jos keskimmäinen numero on
noussut työkirjan laskemisen jälkeen, laskentaan on tullut muutoksia — laske uudelleen. Viimeisen numeron muutokset
eivät koskaan muuta lukuja.

<!-- muutokset:alku -->
* **2026-11-08** — 0.9.0 Versionumero · 0.8.0 Vuoden alun positiot ja toteutetut optiot · 0.7.0 CFD-korjaus ja README-sisällysluettelo
* **2026-11-07** — 0.6.0 Palautekanavat · 0.5.0 Demo ja ohjeet

Kaikki muutokset: [CHANGELOG.md](CHANGELOG.md).
<!-- muutokset:loppu -->

## Kehitys

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests            # julkiset testit (keksitty esimerkkiaineisto)
python scripts/check_private.py             # estää tilinumerot, PDF/XLSX:t ja oikeat CSV:t repossa
python scripts/readme_sync.py --write       # päivittää "Viimeisimmät muutokset" CHANGELOG.md:stä
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
Try it in the browser at [ibkr.arxsavonum.com](https://ibkr.arxsavonum.com) — statements are processed in memory only and nothing is stored on the server. `./run.sh` to run it locally. Feedback: [GitHub Issues](https://github.com/vilpponen/IBKR-yhteenveto/issues) or info@arxsavonum.com (never attach real statements). Versioning: MINOR bumps whenever calculated figures can change, PATCH never changes figures. Currently aimed mainly at active traders who start the year with an empty portfolio (earlier-year lots are handled by asking the user per lot or by reading previous years' statements; exercised bought options adjust the shares' cost or sale price; written options, corporate actions and crypto are only partly supported yet); it will be improved based on feedback. Not tax advice. MIT licence.
