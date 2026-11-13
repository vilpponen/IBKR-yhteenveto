# Muutosloki

Uusimmat ensin. Yksi otsikko päivää kohden; saman päivän julkaisut ovat sen alla. Jokainen julkaisu on yhdistetty
`main`-haaraan pull requestina; demo osoitteessa https://ibkr.arxsavonum.com päivitetään julkaisun jälkeen.

**Versionumerot** (`MAJOR.MINOR.PATCH`, 0.x kunnes työkalu on valmis oikeisiin veroilmoituksiin):
keskimmäinen numero (MINOR) nousee, kun tulee uusi toiminto tai **mikä tahansa muutos, joka voi muuttaa laskettuja
lukuja** — jos se on noussut, laske vanha työkirja uudelleen. Viimeinen numero (PATCH) nousee muutoksista, jotka eivät
koskaan muuta lukuja (tekstit, ohjeet, asennus). Työkirjaan ja sovellukseen on merkitty versio, jolla luvut on laskettu.

## Tulossa (dev)

**Uutta**
- **Tarkat rahasummat:** kaikki laskenta tehdään desimaalilukuina täydellä tarkkuudella (ei liukulukuja), ja summat
  pyöristetään senteiksi vasta näkymässä, puolikkaat parilliseen (10,005 → 10,00). Excel-soluihin kirjoitetaan täysi
  tarkkuus, joten työkirjan kaavat täsmäävät laskelmaan sentilleen.
- **Virheellinen syöte pysäyttää laskennan:** lukukelvoton luku, NaN, ääretön, virheellinen päivämäärä, negatiivinen
  määrä tai hankintameno vuoden alun erässä tai negatiivinen asetus antaa selvän virheen (tiedosto, osio, rivi, arvo)
  näkymässä ja komentorivillä (paluukoodi 3). Aiemmin lukukelvoton arvo muuttui hiljaa nollaksi. Tyhjä solu ja "--"
  ovat edelleen 0.
- **Ei verkkoyhteyksiä:** testi varmistaa, ettei laskentakoodi avaa verkkoyhteyksiä.
- **Lukitut riippuvuudet:** `requirements.txt` sisältää tarkat versiot ja SHA-256-tiivisteet kaikille alustoille ja
  Python-versioille 3.10–3.14; asennus (run.sh, run.ps1, CI) tarkistaa ne (`--require-hashes`). Asennus ei enää
  päivitä pipiä verkosta. Lukitus päivitetään skriptillä `scripts/lock_deps.sh`.

**Muutettu**
- IBKR-tarkistusten (Change in NAV) toleranssi on 0,01 € (aiemmin 1 €); sisäiset täsmäytykset ovat tarkkoja.
- Seuraavan vuoden erätiedostoon (JSON) hankintamenot viedään täydellä tarkkuudella (aiemmin pyöristettiin senteiksi).

**Korjattu**
- Osakeyhtiön työkirja: kun jokin osio oli tyhjä (esim. ei osinkoja), sen summakaava viittasi omaan soluunsa
  (kehäviittaus), jolloin Excel varoitti ja osa tilikartan tarkistuksista jäi laskematta. Tyhjään osioon tulee nyt
  rivi "(ei rivejä)".
- Excel-solujen numeromuotoilu säilyy desimaaliluvuilla.

## 2026-11-13

### 0.10.0 — Hankintameno-olettama, kryptovarat ja asetetut optiot ([#10](https://github.com/vilpponen/IBKR-yhteenveto/pull/10))

**Uutta**
- Yksityishenkilö: **hankintameno-olettama erittäin** (20 %, 40 % jos omistettu vähintään 10 vuotta). Olettama
  lasketaan bruttomyyntihinnasta (ennen myyntiprovisiota ja myyntioption preemiota), eikä sen kanssa vähennetä kuluja.
  Laskelma käyttää sitä, kun se antaa pienemmän voiton; se ei synnytä eikä kasvata tappiota. Valinta asetuksissa.
- Yksityishenkilö: **yritystapahtumat FIFO:ssa** (Activity Statement CSV). Split, osakkeiden yhdistely ja osake- tai
  rahastoanti jakavat hankintamenon uusille osakkeille, ja omistusaika säilyy. Yhdistelyssä murto-osista maksettu
  käteinen käsitellään luovutuksena. Jos tapahtuman tyyppiä ei tunnisteta, osakkeen laskenta keskeytyy ja tulos
  merkitään keskeneräiseksi (ei hiljaista virhetäsmäytystä).
- Yksityishenkilö: **johdannaisten markkinapaikka**. Futuurien ja optioiden tappiot vähennetään vain, kun
  markkinapaikka on säännelty tai siihen rinnastettava (oletuksena ETA:n ja Yhdysvaltain pörssit, listaa voi täydentää
  asetuksissa). Muiden markkinapaikkojen tappiot näytetään vähennyskelvottomina; voitot verotetaan.
- Komentorivi: **henkilötila** (`--personal`) sekä `--loss-cf`, `--include-fx`, `--no-presumption`,
  `--extra-regulated` ja `--opening-lots` (web-sovelluksen JSON-vienti). Keskeneräinen tulos palauttaa koodin 2.
- Yksityishenkilö: **valinnainen EKP-kurssitila**. Kun EKP:n kurssitiedosto (`eurofxref-hist.csv`) lisätään
  raporttien kanssa, kaupat muunnetaan EKP:n viitekurssilla selvityspäivältä, ja tulos näyttää eron IBKR:n kursseihin.
  Ei verkkoyhteyksiä; oletuksena edelleen IBKR:n kauppakohtaiset EUR-määrät.
- Yksityishenkilö: **kryptovarat** (IBKR:n Crypto-luokka, Activity Statement CSV). Luovutukset FIFO-järjestyksessä
  kolikoittain, hankintameno-olettama kuten osakkeilla, oma kohta OmaVero-kentissä ja työkirjassa. 1 000 euron
  pienten luovutusten raja lasketaan arvopapereiden ja kryptovarojen luovutushinnoista yhteensä. Osakeyhtiössä
  kryptot ovat muuta omaisuutta (kuten aiemmin).
- **Asetetut optiot.** Yksityishenkilö: vuoden lopussa avoinna olevan, tänä vuonna asetetun option preemio
  verotetaan asetusvuonna; aiempana vuonna asetetun option takaisinostossa tai raukeamisessa jo verotettu preemio
  vähennetään; samana vuonna asetettuun ja suljettuun optioon hankintameno-olettama 20 % preemiosta, kun edullisempi.
  Toteutusvelvoite samana vuonna: preemio osakkeiden hintaan; aiempana vuonna asetettu: ei oikaisua. Osakeyhtiö:
  OTC- ja yli 18 kuukauden asetettujen optioiden preemio verotetaan asetusvuonna (EVL 27 d § 1 mom.) ja vähennetään
  sulkemisvuonna. Käsittelyperusteet: `docs/PAATOSREKISTERI.md`.
- Osakeyhtiö: **avoimet asetetut optiot tilinpäätöksessä** (OPT-Y8, ehdotus). Tilikauden lopussa avoinna olevan
  asetetun option kirjanpidon tappio näytetään omana vaiheenaan, ja käsittely valitaan optioittain: lisätään takaisin
  verotuksessa, vähennetään kirjanpidon mukaisesti tai EVL 27 e § (vain käypään arvoon arvostavalle yhtiölle).
  Ilman valintaa tappio lisätään takaisin ja tulos merkitään keskeneräiseksi. Tappio on EVL-täsmäytyksessä omalla
  rivillään (ei enää futuurien ja ETF:ien rivillä), ja edellisenä vuonna lisätty määrä vähennetään uudella syötteellä.
  Komentorivi: `--wopt-y8`, `--fair-value-5-2a`, `--wopt-loss-carry`.
- **Päätösrekisteri** ([docs/PAATOSREKISTERI.md](docs/PAATOSREKISTERI.md)): käsittelysäännöt, niiden lähteet ja tila
  yhdessä tiedostossa. Ei muuta laskentaa.

**Muutettu**
- OmaVero-kentät: luovutushinnat ovat bruttomyyntihintoja ja myyntiprovisiot ovat kuluissa (aiemmin myyntiprovisio
  oli vähennetty luovutushinnasta). Luovutusvoitot eivät muutu, ellei olettamaa käytetä.
- PDF:n kauppakohtaisille riveille myyntiprovisio luetaan CSV:n toimeksiantoriveiltä.

## 2026-11-08

### 0.9.0 — Versionumero ([#8](https://github.com/vilpponen/IBKR-yhteenveto/pull/8))

**Uutta**
- Versionumero: näkyy sovelluksen otsikossa ja alatunnisteessa, Excel-työkirjassa (Asetukset ja Muistio) ja
  komentorivillä (`--version`). Muutoslokin aiemmille julkaisuille lisätty versiot 0.1.0–0.8.0.

**Korjattu**
- PDF-raportin lukeminen vei suurilla raporteilla gigatavuja muistia (sivut jäivät välimuistiin), jolloin palvelin
  keskeytti käsittelyn ja demo näytti virheen "Unexpected token '<' … is not valid JSON". Nyt sivu vapautetaan heti
  luvun jälkeen: muistinkäyttö noin 3 Gt → noin 0,1 Gt. Luvut eivät muutu.
- Jos palvelin palauttaa virhesivun, sovellus näyttää selkeän suomenkielisen virheilmoituksen.

### 0.8.0 — Vuoden alun positiot ja toteutetut optiot ([#7](https://github.com/vilpponen/IBKR-yhteenveto/pull/7))

**Uutta**
- Yksityishenkilö: **vuoden alun positiot**. Jos tänä vuonna myydään aiemmin ostettuja osakkeita, sovellus kysyy
  ennen tuloksia käsittelytavan: edellisen vuoden IBKR-raportti (luetaan automaattisesti), alkuperäiset ostotiedot,
  hankintameno-olettama tai IBKR:n luku. Ilman valintaa tulokset merkitään keskeneräisiksi.
- Edellisten vuosien raportit voi lisätä samaan latauslaatikkoon: niistä rakennetaan erähistoria FIFO-järjestyksessä.
- Valintojen vienti ja tuonti (JSON) sekä vuoden lopun avoimet erät ensi vuoden laskelmaan.
- Työkirjaan Vuoden alun erät -välilehti; jokaisen luovutuksen hankintamenon peruste näkyy erittäin.
- Yksityishenkilö: **toteutetut optiot**. Ostetun osto-option preemio lisätään saatujen osakkeiden hankintamenoon,
  ostetun myyntioption preemio vähennetään luovutushinnasta (KHO 2012:69). Edellisenä vuonna ostetun option
  preemio kysytään vuoden alun positioiden yhteydessä. Toteutusvelvoitteista (asetetut optiot) annetaan varoitus.
- Varoitus, jos IBKR on käyttänyt muuta erätäsmäytystä kuin FIFO:a.

**Korjattu**
- CSV:n euromääräisissä osakeostoissa (ja keskikurssilla muunnetuissa CSV-kaupoissa) ostoprovisio pienensi
  hankintamenoa, vaikka sen pitää kasvattaa sitä. PDF:n kauppakohtaiset EUR-määrät eivät olleet virheellisiä.

**Muutettu**
- README: huomautus, kenelle työkalu sopii nyt (aktiivinen kaupankävijä, salkku tyhjä vuoden alussa) ja mitkä
  tilanteet ovat vielä rajallisesti tuettuja.
- Muutosloki: yksi otsikko päivää kohden.

### 0.7.0 — CFD-korjaus ja README-sisällysluettelo ([#6](https://github.com/vilpponen/IBKR-yhteenveto/pull/6))

**Korjattu**
- Yksityishenkilö: CFD-tappioita ei enää vähennetä. CFD-voitot lasketaan kauppakohtaisesti muuksi pääomatuloksi
  (OmaVero 16B), tappiollisia kauppoja ei huomioida (Verohallinto). CFD:iin liittyviä rahoituskuluja ei vähennetä.
  Osakeyhtiön laskelma ei muutu; muistio pyytää vahvistamaan CFD:iden käsittelyn kirjanpitäjältä.

**Uutta**
- README: sisällysluettelo ja "Viimeisimmät muutokset" (5 uusinta julkaisua tästä muutoslokista).

## 2026-11-07

### 0.6.0 — Palautekanavat ([#5](https://github.com/vilpponen/IBKR-yhteenveto/pull/5))

**Uutta**
- Palaute ja virheilmoitukset: [GitHub Issues](https://github.com/vilpponen/IBKR-yhteenveto/issues/new/choose)
  (valmiit lomakkeet virheilmoitukselle ja parannusehdotukselle) tai info@arxsavonum.com.
- Lomakkeet ja sovellus muistuttavat: älä liitä oikeita raportteja, tilinumeroita, nimiä tai summia.
- Tietoturvaongelmat voi ilmoittaa yksityisesti ([SECURITY.md](SECURITY.md)).
- Tämä muutosloki.

### 0.5.0 — Demo ja ohjeet ([#4](https://github.com/vilpponen/IBKR-yhteenveto/pull/4))

**Uutta**
- Demo selaimessa: https://ibkr.arxsavonum.com
- Linkki sovelluksesta GitHub-repoon.

**Muutettu**
- README kertoo selvästi, mitkä raportit tarvitaan: osakeyhtiölle Activity Statement CSV riittää,
  yksityishenkilölle CSV + PDF (tarkat kauppakohtaiset EUR-määrät). Sama ohje sovelluksen latauslaatikossa.

### 0.4.0 — Palvelin ei tallenna mitään ([#3](https://github.com/vilpponen/IBKR-yhteenveto/pull/3))

**Muutettu**
- Palvelin ei säilytä mitään: ei istuntoja, ei tiedostoja, ei väliaikaistiedostoja levylle, ei raporttien sisältöä
  lokeihin. Raportit, tulos ja Excel-työkirja pysyvät vain selainikkunassa.
- Palvelimella ajettaessa sivu kertoo, että raportit lähetetään vain laskentaa varten.

**Korjattu**
- Palvelimen loki kaatui tukemattomilla pyynnöillä (esim. HEAD).

### 0.3.0 — Windows-asennus ([#2](https://github.com/vilpponen/IBKR-yhteenveto/pull/2))

**Uutta**
- Asennus ja päivitys yhdellä PowerShell-komennolla (`irm … install.ps1 | iex`).
- `run.cmd`: myöhemmin käynnistys kaksoisklikkauksella.
- Asennuksen automaattitestit Windowsilla (PowerShell 5.1 ja 7) ja macOS:llä.

### 0.2.0 — macOS-asennus ([#1](https://github.com/vilpponen/IBKR-yhteenveto/pull/1))

**Uutta**
- Asennus ja päivitys yhdellä komennolla (`curl … install.sh | bash`) valitsemaasi kansioon.
- Käyttöönotto-ohjeet ilman gitiä tai GitHub-tunnusta.

### 0.1.0 — Ensimmäinen versio

**Uutta**
- **Osakeyhtiö:** kirjanpito (KPL) ilman tasauseriä, alimman arvon periaate, tase IBKR:n NAV:sta ja EVL-verolaskelma (6B).
- **Yksityishenkilö:** luovutusvoitot ja -tappiot FIFO-menetelmällä kauppapäivän kursseilla (9A), osingot ja
  lähdeverot (16B), pääomatulovero-arvio.
- Tulos Excel-työkirjana, jossa luvut ovat kaavoja ja jäljitettävissä IBKR:n raporttiin.
- Täsmäytys IBKR:n omiin lukuihin (Change in NAV).
