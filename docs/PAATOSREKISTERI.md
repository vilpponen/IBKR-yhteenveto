# Päätösrekisteri

Tämä tiedosto kertoo, **miten IBKR-yhteenveto käsittelee kunkin erän, mihin lähteeseen käsittely nojaa ja mikä on
päätöksen tila**. Se on tarkoitettu sekä ihmisille että koodia muokkaaville tekoälyavustajille: lue se ennen kuin
muutat laskentasääntöä, ja päivitä se samassa commitissa, jos sääntö muuttuu.

Tämä ei ole veroneuvontaa. Lähteet ovat julkisia (Verohallinnon ohjeet, laki, oikeuskäytäntö); tulkinnat on merkitty
tulkinnoiksi.

## Käyttö

- Jokaisella päätöksellä on **pysyvä tunnus** (esim. `OPT-H3`). Tunnusta ei käytetä uudelleen. Koodin kommenteissa
  ja commit-viesteissä voi viitata tunnukseen.
- **Tila** on yksi näistä:

  | Tila | Merkitys |
  |---|---|
  | Voimassa | Toteutettu sovelluksessa. Koodin pitää vastata riviä. |
  | Vahvistettu | Lähde tarkistettu, ei vielä toteutettu. Saa toteuttaa. |
  | Ehdotus | Odottaa omistajan päätöstä. **Ei toteuteta ennen päätöstä.** |
  | Avoin | Ei lähdettä tai kysymys kesken. **Ei toteuteta ennen päätöstä.** |

- Kun päätös muuttuu, vanha rivi jää näkyviin merkinnällä `Korvattu pvm → uusi tunnus`, ja muutos kirjataan
  [muutoslokiin](#muutosloki).
- Jos koodi ja tämä tiedosto ovat ristiriidassa, kyse on virheestä jommassakummassa: selvitä kumpi on oikein, älä
  muuta toista hiljaa vastaamaan toista.
- Tiedostoon ei kirjoiteta oikeita lukuja, nimiä, tilinumeroita eikä kaupankäynnin kohteita.

## Lähteet

| Lyhenne | Lähde | Tarkistettu |
|---|---|---|
| Vero 48914 | [Johdannaisten verotus](https://www.vero.fi/syventavat-vero-ohjeet/ohje-hakusivu/48914/johdannaisten-verotus2/), annettu 20.9.2022 | 12.11.2026 |
| Vero 48083 | [Johdannaisinstrumenttien verotus EVL 27 d ja 27 e §:n mukaan](https://www.vero.fi/syventavat-vero-ohjeet/ohje-hakusivu/48083/johdannaisinstrumenttien_verotus_elinke/), annettu 13.6.2014 | 12.11.2026 |
| KHO 2012:69 | [Ostetun osto-option preemio osakkeiden hankintamenoon](https://www.finlex.fi/fi/oikeuskaytanto/korkein-hallinto-oikeus/ennakkopaatokset/2012/69) | 12.11.2026 |
| KVL 1/2021 | [Yhdysvaltain markkinapaikat rinnastuvat säänneltyyn markkinaan](https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/94343/kvl0012021/) | 12.11.2026 |
| EU 2022/552 | Komission täytäntöönpanoasetus: SEC:n rekisteröimät Yhdysvaltain arvopaperipörssit | Vero 48914:n kautta |
| HE 84/2002 | [Hallituksen esitys EVL 27 d §:stä](https://api.eduskunta.fi/documents/fi/HE/2002/he_84%2B2002.pdf) | 13.11.2026 (s. 2–3 ja 8) |
| TVL | [Tuloverolaki 1535/1992](https://www.finlex.fi/fi/lainsaadanto/1992/1535) | 13.11.2026 (linkki) |
| EVL | [Elinkeinoverolaki 360/1968](https://www.finlex.fi/fi/lainsaadanto/1968/360) | 13.11.2026 (27 d ja 27 e §) |
| Lomake 77 | [Täyttöohje: pakolliset varaukset ja realisoitumattomat arvonalennukset](https://vero.fi/tietoa-verohallinnosta/yhteystiedot-ja-asiointi/lomakkeet/tayttoohjeet/77_laskelma_elinkeinotoiminnan_tulokses3/) (luottolaitokset ja vakuutusyhtiöt; yleisperiaate) | 13.11.2026 |
| KVL 2025/7 | [Johdannaisella hankitut osakkeet, arvonmuutos](https://www.edilex.fi/kvl/20250007) (ostettu optio / termiini; ei asetettu optio) | 13.11.2026 |

Seuraavat ratkaisut tunnetaan vain yllä olevien lähteiden viittausten kautta; niiden koko tekstiä ei ole luettu:
KHO 9.9.1999 T 2410, KVL 231/1989, KHO 2010:74, KHO 11.4.2005 T 802, KHO 1995-B-522, KHO 2003:35.

## 1. Optiot — yksityishenkilö (TVL)

Koodi: `ibkr_yhteenveto/personal.py` (`option_events`, `fifo_full`). Tehtävät: 62N-86 (toteutettu), 62N-87 (kesken).

| Tunnus | Päätös | Tila | Lähde |
|---|---|---|---|
| OPT-H1 | Asetetun option preemio on veronalaista sinä verovuonna, jona se on nostettavissa (asetusvuosi). | Voimassa (62N-87) | Vero 48914 §2.4 |
| OPT-H2 | Position sulkeminen: tulos = saatu preemio − maksettu preemio, luovutusvoittosäännöin. | Voimassa (IBKR:n realisoitu tulos; 62N-87) | Vero 48914 §2.4 |
| OPT-H3 | Ostettu optio toteutetaan lunastamalla osakkeet: maksettu preemio kuluineen on osa osakkeiden hankintamenoa (osto-optio) tai vähennetään luovutushinnasta (myyntioptio). | Voimassa (62N-86) | KHO 2012:69; Vero 48914 §2.4 |
| OPT-H4 | Asetettu optio toteutetaan **samana vuonna**: preemio osaksi osakkeiden hankintahintaa tai luovutushintaa (osto-optio: lisätään toimitettujen osakkeiden luovutushintaan; myyntioptio: vähennetään saatujen osakkeiden hankintamenosta). Korvaa HEN-12:n. | Voimassa (62N-87; korvasi HEN-12:n 13.11.2026) | Vero 48914 §2.4 ("saatu tai maksettu preemio"); tulkinta |
| OPT-H5 | Asetettu vuonna N, toteutettu vuonna N+1: preemio verotetaan vuonna N eikä osakkeiden hintaa oikaista myöhemmin; käyttäjän asetus ja muistiomerkintä. | Voimassa (62N-87, vaihtoehto A) | Ei lähdettä; ohje ei sovita sääntöjä yhteen |
| OPT-H6 | Asetettu vuonna N, takaisinostettu vuonna N+1: takaisinostokulu on luovutustappiota vuonna N+1 (säännelty markkina). | Voimassa (62N-87) | TVL 50 § 3 mom. 1 k. ("siitä aiheutunut tappio"); tulkinta |
| OPT-H7 | Hankintameno-olettama 20 % on sallittu asetetun option preemioon. | Voimassa (62N-87) | KHO 9.9.1999 T 2410 (Vero 48914 §2.4:n kautta) |
| OPT-H8 | Olettama korvaa todelliset menot: jos sitä käytetään preemioon, takaisinostokulua ei vähennetä erikseen. Olettama vain samana vuonna rauenneille tai suljetuille optioille. | Voimassa (62N-87) | TVL 46 § 1 mom.; tulkinta |
| OPT-H9 | Rauennut ostettu optio on luovutustappiota, jos optiolla käydään kauppaa säännellyllä tai siihen rinnastuvalla markkinalla. | Vahvistettu | TVL 50 § 3 mom. 1 k.; Vero 48914 §2.5 |
| OPT-H10 | Indeksioptio (nettoarvon tilitys): tilitys on luovutushinta ja maksettu preemio hankintameno; tulo kuuluu tilitysvuodelle. | Vahvistettu | Vero 48914 §2.4 |
| OPT-H11 | Säännellyt markkinat: ETA:n säännellyt markkinat ja Yhdysvaltain valvotut pörssit oletuksena; käyttäjä voi täydentää listaa. Muiden markkinapaikkojen johdannaistappiot ovat vähennyskelvottomia, voitot verotetaan. EMIR-vastaavuusluettelon kolmansien maiden markkinat jätetty toistaiseksi pois (päätetty 13.11.2026). | Voimassa (62N-91; `REGULATED_EXCHANGES`) | KVL 1/2021; EU 2022/552; Vero 48914 §1, §2.5 ja §7 |
| OPT-H12 | OTC-johdannainen: voitto on veronalaista pääomatuloa, tappio vähennyskelvoton. | Vahvistettu | Vero 48914 §7 |
| OPT-H13 | Tietolähde: kauppakoodit (O/C, Ex, A, Ep) CSV:stä ja EUR-määrät PDF:stä IBKR:n dokumentaation mukaan; tarkennetaan palautteen perusteella. | Vahvistettu (päätetty 13.11.2026) | IBKR Reporting Reference (Codes, Trades, Option Exercises); ei vielä varmistettu aineistolla, jossa on asetettuja optioita |

## 2. Optiot — osakeyhtiö (EVL 27 d §)

Koodi: `ibkr_yhteenveto/books.py`. Tehtävä: 62N-87 (kesken).

| Tunnus | Päätös | Tila | Lähde |
|---|---|---|---|
| OPT-Y1 | Säännellyllä tai muulla viranomaisen valvomalla markkinalla, voimassaolo enintään 18 kk: asettajan preemio on sen vuoden tuottoa, jona optio suljetaan, toteutetaan tai raukeaa. | Vahvistettu | EVL 27 d § 2 mom.; Vero 48083 §4 |
| OPT-Y2 | OTC tai yli 18 kk: asettajan preemio on asetusvuoden tuloa. Lisäys verolaskelmaan asetusvuonna ja vähennys päättymisvuonna; osakkeiden hankintamenoa ei oikaista. | Voimassa (62N-87; EVL-lisäys automaattisesti, vähennys sulkemisvuonna syötteellä) | EVL 27 d § 1 mom.; Vero 48083 §3.2 ja liite 1 |
| OPT-Y3 | Maksettu preemio vähennetään, kun optio suljetaan, toteutetaan tai raukeaa (kaikissa tapauksissa). | Vahvistettu | EVL 27 d § 3 mom. |
| OPT-Y4 | Toteutus hankkimalla kohde-etuus: asetetun myyntioption preemio pienentää ja ostetun osto-option preemio kasvattaa osakkeiden hankintamenoa. | Vahvistettu | EVL 27 d § 2 ja 3 mom.; Vero 48083 §4.4 ja liite 2 |
| OPT-Y5 | 18 kuukautta lasketaan asettamispäivästä toteutuspäivään, positiokohtaisesti. | Voimassa (62N-87; avoimelle positiolle asettamispäivästä erääntymispäivään) | HE 84/2002; Vero 48083 §4.2.2 |
| OPT-Y6 | Markkinatesti on laajempi kuin henkilöillä: Yhdysvaltain pörssit kelpaavat suoraan lain sanamuodon nojalla. | Vahvistettu | EVL 27 d § 2 mom. |
| OPT-Y7 | Pörssioptiot enintään 18 kk: verotus seuraa kirjanpitoa, eikä EVL-oikaisua tarvita, kun preemio on siirtovelkana option päättymiseen asti. | Vahvistettu | Vero 48083 §4.3 |
| OPT-Y8 | Avoimen asetetun option tilinpäätöshetken tappio (KPL 5:2 -arvostus tai pakollinen varaus) ei ole vähennyskelpoinen ennen kuin optio suljetaan, toteutetaan tai raukeaa; se lisätään takaisin EVL-täsmäytyksessä. Poikkeus: käypään arvoon arvostettu kaupankäyntitarkoituksessa pidettävä rahoitusväline (KPL 5:2a) → EVL 27 e § ja 8 § 1 mom. 2 a k. (ei mikroyritykselle). | Ehdotus (vahvistus kirjanpitäjältä, 62N-95). Toteutettu käyttäjän valintana optioittain (62N-100): lisätään takaisin / vähennetään kirjanpidon mukaisesti / EVL 27 e §; ei esivalintaa, ilman valintaa lisätään takaisin ja tulos on keskeneräinen. Lisätty määrä vähennetään seuraavana vuonna syötteellä. | EVL 27 d § 2 ja 4 mom., 27 e §; HE 84/2002 s. 2–3 ja 8 (realisoitumaton menetys vähennyskelpoinen vain erityissäännöksellä; julkaisematon hallinto-oikeuden päätös 2000: avoimien asetettujen optioiden laskennalliset sulkemiskustannukset eivät vähennyskelpoisia, KHO ei myöntänyt valituslupaa 2001); Vero 48083 §4.3 ja liite 2; Lomake 77. KHO:n vuosikirjaratkaisua ei löytynyt vuoden 2002 jälkeen; KKO ei ratkaise veroasioita. |

## 3. Osakeyhtiö — muut säännöt (KPL / EVL)

Koodi: `ibkr_yhteenveto/books.py`, `ibkr_yhteenveto/excel.py`. Näiden rivien lähteitä ei ole tarkistettu uudelleen
rekisteriä perustettaessa; tarkistus tehdään, kun riviin kosketaan.

| Tunnus | Päätös | Tila |
|---|---|---|
| YHT-1 | Tulos ilman täsmäytyseriä: E = NAV loppu − NAV alku − nettotalletukset. N = osingot, PIL, lähdeverot, korot, siirtyvien erien muutos, kulut ja FTT. T = E − N. | Voimassa |
| YHT-2 | IBKR:n R&U-raportin Forex-riviä ei kirjata, koska se on EUR-perusvaluuttaisella tilillä päällekkäinen osaketuloksen kanssa; valuuttakurssitulos johdetaan. | Voimassa |
| YHT-3 | Komissiot sisältyvät jo IBKR:n hankintamenoon ja luovutushintaan; niitä ei vähennetä uudelleen. | Voimassa |
| YHT-4 | Alin arvo (KPL 5:6): realisoitumaton tappio kirjataan arvonalennuksena (muutos avaavaan varaukseen nähden); realisoitumattomia voittoja ei kirjata. | Voimassa |
| YHT-5 | EVL: kaikki lähdeverot lisätään takaisin; hyvitys lasketaan erikseen, enintään verosopimuksen mukainen määrä. | Voimassa |
| YHT-6 | EVL: futuurien ja ETF:ien arvonalennukset ovat muuta omaisuutta (lisätään takaisin); osakkeet käsitellään asetuksen mukaan (muu omaisuus tai rahoitusomaisuus). Avoimien asetettujen optioiden tilinpäätöstappio käsitellään erikseen (`OPT-Y8`). | Voimassa; omaisuuslaji avoin (62N-95) |
| YHT-7 | Listayhtiön osinko listaamattomalle yhtiölle alle 10 %:n omistuksella on kokonaan veronalaista; PIL on muuta rahoitustuottoa. | Voimassa |
| YHT-8 | Siirrot: peruutus ja sen vastatapahtuma merkitään peruutetuiksi (netto 0); nostot menevät yhtiön omalle pankkitilille ilman verovaikutusta. | Voimassa |
| YHT-9 | Kryptovarat ovat osakeyhtiössä muuta omaisuutta. | Voimassa |

## 4. Yksityishenkilö — muut säännöt (TVL)

Koodi: `ibkr_yhteenveto/personal.py`, `ibkr_yhteenveto/excel_personal.py`. Lähteitä ei ole tarkistettu uudelleen
rekisteriä perustettaessa, ellei rivillä toisin mainita.

| Tunnus | Päätös | Tila |
|---|---|---|
| HEN-1 | FIFO symboleittain; luovutushinta myyntipäivän ja hankintameno ostopäivän kurssilla, yksi tulos hankintaerää kohti. Lyhyet positiot tuettu. | Voimassa |
| HEN-2 | Aiempien vuosien erät: ohjattu käsittely (alkuperäiset tiedot, aiempi raportti, hankintameno-olettama tai IBKR:n luku). | Voimassa (62N-88) |
| HEN-3 | Hankintameno-olettama hankintaerittäin: 20 %, tai 40 % kun omistettu vähintään 10 vuotta. Lasketaan bruttomyyntihinnasta, eikä sen kanssa vähennetä kuluja. Käytetään, kun se antaa pienemmän voiton; se ei synnytä eikä kasvata tappiota. | Voimassa (62N-89) |
| HEN-4 | IBKR:n Forex-rivi ei ole oletuksena mukana. | Voimassa |
| HEN-5 | Pienet luovutukset enintään 1 000 € ovat verovapaita; raja lasketaan arvopapereiden ja kryptovarojen luovutushinnoista yhteensä. Listayhtiön osingosta 85 % on veronalaista. Pääomatulovero 30 % / 34 %. | Voimassa |
| HEN-6 | CFD: voitto on veronalaista pääomatuloa, tappio vähennyskelvoton (KHO 2010:74; Vero 48914 §4.2, tarkistettu 12.11.2026). | Voimassa (62N-85) |
| HEN-7 | Futuurit: voitto rinnastetaan luovutusvoittoon säännellyllä markkinalla; hankintameno-olettamaa ei saa käyttää (TVL 45 § 3 mom.; Vero 48914 §3.2, tarkistettu 12.11.2026). Markkinapaikka kuten OPT-H11. | Voimassa (62N-91) |
| HEN-8 | Yritystapahtumat FIFO:ssa: split, osakkeiden yhdistely ja osake- tai rahastoanti jakavat hankintamenon uusille osakkeille, ja omistusaika säilyy. Murto-osista maksettu käteinen on luovutus. Tuntematon tapahtuma keskeyttää osakkeen laskennan, ja tulos merkitään keskeneräiseksi. | Voimassa (62N-90) |
| HEN-9 | Kryptovarat: FIFO kolikoittain, hankintameno-olettama kuten osakkeilla, oma kohta OmaVero-kentissä. | Voimassa (62N-92) |
| HEN-10 | Valuuttakurssi: oletuksena IBKR:n kauppakohtaiset EUR-määrät. Valinnainen EKP-tila käyttää selvityspäivän viitekurssia käyttäjän lisäämästä kurssitiedostosta; ei verkkoyhteyksiä. | Voimassa (62N-94) |
| HEN-11 | OmaVero-kentissä luovutushinnat ovat bruttomyyntihintoja ja myyntiprovisiot kuluissa. | Voimassa (62N-89) |
| HEN-12 | Asetetun option toteutusvelvoite (koodi A): osakkeiden hintaa ei oikaista preemiolla, ja laskelma varoittaa. | Korvattu 13.11.2026 → OPT-H4 (samana vuonna asetettu) ja OPT-H5 (aiempana vuonna asetettu) |

## 5. Laskenta ja syöte (kaikki tilat)

Koodi: `ibkr_yhteenveto/num.py`, `parse_common.py`, `parse_csv.py`, `parse_pdf.py`, `books.py`, `personal.py`,
`report.py`, `server.py`. Omistajan päätökset 13.11.2026 (62N-97).

| Tunnus | Päätös | Tila |
|---|---|---|
| LAS-1 | Rahasummat ovat `Decimal`-lukuja täydellä tarkkuudella koko laskennan läpi. Pyöristys vain tulostuksessa (näkymä, raportit) senteiksi, puolikkaat parilliseen (half even, 10,005 → 10,00). Excel-työkirjan soluihin kirjoitetaan täysi tarkkuus; Excel näyttää sentit. | Voimassa (62N-97) |
| LAS-2 | Toleranssit: sisäiset täsmäytykset (kirjanpidon tulos ja NAV-muutos, tase, tilikartta) enintään 0,000001 € (laskennallinen jäännös); vertailu IBKR:n omiin Change in NAV -summiin 0,01 €. | Voimassa (62N-97) |
| LAS-3 | Lukukelvoton luku, NaN, ääretön, virheellinen päivämäärä, negatiivinen määrä tai hankintameno vuoden alun erässä tai negatiivinen asetus pysäyttää laskennan ja kertoo tiedoston, osion, rivin ja arvon. Tyhjä solu ja IBKR:n "--" = 0; myynnin negatiivinen määrä on sallittu. | Voimassa (62N-97) |
| LAS-4 | Laskenta on paikallista: ei verkkoyhteyksiä (testi). Riippuvuudet asennetaan vain lukitusta tiedostosta (tarkat versiot ja SHA-256-tiivisteet, `pip install --require-hashes`); lukitus päivitetään käsin julkaisun valmistelussa (`scripts/lock_deps.sh`). | Voimassa (62N-97) |

## Muutosloki

- 13.11.2026 — 62N-97 toteutettu (dev): uusi osio 5, `LAS-1`…`LAS-4` → Voimassa (omistajan päätökset 13.11.2026).

- 13.11.2026 — 62N-100 toteutettu (dev): `OPT-Y8` käyttäjän valintana optioittain (tila pysyy Ehdotus);
  `YHT-6` tarkennettu: asetettujen optioiden tappio omalla rivillään.
- 13.11.2026 — 62N-87 toteutettu (dev): `OPT-H1`, `OPT-H2`, `OPT-H4`…`OPT-H8`, `OPT-Y2` ja `OPT-Y5` → Voimassa;
  `HEN-12` korvattu (`OPT-H4`, `OPT-H5`).
- 13.11.2026 — Omistajan päätökset 62N-87:ään: `OPT-H4`, `OPT-H5` (vaihtoehto A), `OPT-H6`, `OPT-H8` ja `OPT-H13`
  → Vahvistettu; `OPT-H11` pysyy ETA + Yhdysvallat. `OPT-Y8` Avoin → Ehdotus oikeuslähdeselvityksen perusteella
  (HE 84/2002, EVL 27 d–27 e §, Lomake 77). Lisätty `HEN-12` (nykyinen toteutusvelvoitteen käsittely) ja lähteitä.
- 13.11.2026 — Rekisteri perustettu. Optiopäätökset `OPT-H1…H13` ja `OPT-Y1…Y8` lähdetarkistuksen (12.11.2026)
  perusteella; aiemmin toteutetut säännöt `YHT-1…9` ja `HEN-1…11`.
