# Muutosloki

Uusimmat ensin. Yksi otsikko päivää kohden; saman päivän julkaisut ovat sen alla. Jokainen julkaisu on yhdistetty
`main`-haaraan pull requestina; demo osoitteessa https://ibkr.arxsavonum.com päivitetään julkaisun jälkeen.

## Tulossa (dev)

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

## 2026-11-08

### CFD-korjaus ja README-sisällysluettelo ([#6](https://github.com/vilpponen/IBKR-yhteenveto/pull/6))

**Korjattu**
- Yksityishenkilö: CFD-tappioita ei enää vähennetä. CFD-voitot lasketaan kauppakohtaisesti muuksi pääomatuloksi
  (OmaVero 16B), tappiollisia kauppoja ei huomioida (Verohallinto). CFD:iin liittyviä rahoituskuluja ei vähennetä.
  Osakeyhtiön laskelma ei muutu; muistio pyytää vahvistamaan CFD:iden käsittelyn kirjanpitäjältä.

**Uutta**
- README: sisällysluettelo ja "Viimeisimmät muutokset" (5 uusinta julkaisua tästä muutoslokista).

## 2026-11-07

### Palautekanavat ([#5](https://github.com/vilpponen/IBKR-yhteenveto/pull/5))

**Uutta**
- Palaute ja virheilmoitukset: [GitHub Issues](https://github.com/vilpponen/IBKR-yhteenveto/issues/new/choose)
  (valmiit lomakkeet virheilmoitukselle ja parannusehdotukselle) tai info@arxsavonum.com.
- Lomakkeet ja sovellus muistuttavat: älä liitä oikeita raportteja, tilinumeroita, nimiä tai summia.
- Tietoturvaongelmat voi ilmoittaa yksityisesti ([SECURITY.md](SECURITY.md)).
- Tämä muutosloki.

### Demo ja ohjeet ([#4](https://github.com/vilpponen/IBKR-yhteenveto/pull/4))

**Uutta**
- Demo selaimessa: https://ibkr.arxsavonum.com
- Linkki sovelluksesta GitHub-repoon.

**Muutettu**
- README kertoo selvästi, mitkä raportit tarvitaan: osakeyhtiölle Activity Statement CSV riittää,
  yksityishenkilölle CSV + PDF (tarkat kauppakohtaiset EUR-määrät). Sama ohje sovelluksen latauslaatikossa.

### Palvelin ei tallenna mitään ([#3](https://github.com/vilpponen/IBKR-yhteenveto/pull/3))

**Muutettu**
- Palvelin ei säilytä mitään: ei istuntoja, ei tiedostoja, ei väliaikaistiedostoja levylle, ei raporttien sisältöä
  lokeihin. Raportit, tulos ja Excel-työkirja pysyvät vain selainikkunassa.
- Palvelimella ajettaessa sivu kertoo, että raportit lähetetään vain laskentaa varten.

**Korjattu**
- Palvelimen loki kaatui tukemattomilla pyynnöillä (esim. HEAD).

### Windows-asennus ([#2](https://github.com/vilpponen/IBKR-yhteenveto/pull/2))

**Uutta**
- Asennus ja päivitys yhdellä PowerShell-komennolla (`irm … install.ps1 | iex`).
- `run.cmd`: myöhemmin käynnistys kaksoisklikkauksella.
- Asennuksen automaattitestit Windowsilla (PowerShell 5.1 ja 7) ja macOS:llä.

### macOS-asennus ([#1](https://github.com/vilpponen/IBKR-yhteenveto/pull/1))

**Uutta**
- Asennus ja päivitys yhdellä komennolla (`curl … install.sh | bash`) valitsemaasi kansioon.
- Käyttöönotto-ohjeet ilman gitiä tai GitHub-tunnusta.

### Ensimmäinen versio

**Uutta**
- **Osakeyhtiö:** kirjanpito (KPL) ilman tasauseriä, alimman arvon periaate, tase IBKR:n NAV:sta ja EVL-verolaskelma (6B).
- **Yksityishenkilö:** luovutusvoitot ja -tappiot FIFO-menetelmällä kauppapäivän kursseilla (9A), osingot ja
  lähdeverot (16B), pääomatulovero-arvio.
- Tulos Excel-työkirjana, jossa luvut ovat kaavoja ja jäljitettävissä IBKR:n raporttiin.
- Täsmäytys IBKR:n omiin lukuihin (Change in NAV).
