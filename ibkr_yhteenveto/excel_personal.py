"""Excel workbook for a personal (henkilöasiakas) IBKR account — OmaVero figures with live formulas."""
from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.worksheet.datavalidation import DataValidation

from .xlsx_mem import workbook_bytes

from .books import _is_div_wht, _is_pil, wht_country
from .excel import FILL_KEY, NUM, PCT, Sheet
from .personal import PBooks, _is_cfd_cost


def write_personal_workbook(b: PBooks) -> bytes:
    st, s, v = b.st, b.s, b.v
    wb = Workbook()
    wb.remove(wb.active)
    ref: dict[str, str] = {}
    period = f"{st.period_start} – {st.period_end}"
    sub = f"{s.name or st.name} · IBKR {st.account} · {period} · henkilöverotus"

    om = Sheet(wb, "OmaVero-kentät", [42, 58, 18, 60])
    sm = Sheet(wb, "Arvopaperit yhteenveto", [14, 16, 18, 18, 16, 16, 16, 16, 30])
    lu = Sheet(wb, "Luovutukset (FIFO)", [14, 12, 12, 12, 16, 16, 16, 20, 8])
    de = Sheet(wb, "Johdannaiset", [16, 22, 16, 16, 16, 30])
    dv = Sheet(wb, "Osingot & lähdeverot", [12, 62, 8, 14, 14, 10, 8, 22])
    kk = Sheet(wb, "Korot & kulut", [12, 58, 8, 14, 14, 30])
    po = Sheet(wb, "Pääomatulo & vero", [62, 18, 60])
    asx = Sheet(wb, "Asetukset", [46, 18, 70])
    mu = Sheet(wb, "Muistio", [30, 140])

    # ---------------------------------------------------------------- Asetukset
    asx.title("Asetukset", ["Keltaiset solut ovat muokattavia."])
    asx.header(["Asetus", "Arvo", "Selite"])
    def inp(label, value, note, key, fmt=None, validation=None):
        r = asx.row([label, value, note], ["t", "in", "t"], fmt=[None, fmt, None])
        asx.ws.cell(r, 2).fill = FILL_KEY
        ref[key] = asx.q(f"$B${r}")
        if validation:
            dvv = DataValidation(type="list", formula1=validation)
            asx.ws.add_data_validation(dvv)
            dvv.add(asx.ws.cell(r, 2))
    inp("Pääomatulon veroprosentti", s.rate_low, "30 % rajaan asti", "r1", PCT)
    inp("Pääomatulon veroprosentti rajan yli", s.rate_high, "34 %", "r2", PCT)
    inp("Raja (€)", s.bracket, "30 000 €", "br")
    inp("Pienten luovutusten raja (€)", s.small_limit, "Luovutushinnat yhteensä enintään → voitot verovapaita", "small")
    inp("Listattujen osinkojen veronalainen osuus", s.div_taxable_share, "85 %", "divsh", PCT)
    inp("Payment in lieu -korvauksen veronalainen osuus", s.pil_taxable_share, "100 % (muu pääomatulo)", "pilsh", PCT)
    inp("Aiempien vuosien vahvistetut luovutustappiot (€)", s.loss_carryforward, "Verotuspäätöksestä, 5 v", "cf")
    asx.blank()
    asx.note("Sininen = syöte raportista, musta = kaava, vihreä = linkki. " + f"Generoitu {date.today().isoformat()}")

    # ---------------------------------------------------------------- Luovutukset (FIFO)
    lu.title("Arvopapereiden luovutukset hankintaerittäin (FIFO)",
             [sub, "EUR: myyntihinta myyntipäivän ja hankintameno ostopäivän kurssilla (IBKR Forex P/L Details).",
              "Myyntihinnasta on vähennetty myyntiprovisio; hankintamenoon sisältyy ostoprovisio."])
    lu.header(["Symboli", "Myyntipäivä", "Ostopäivä", "Määrä", "Luovutushinta €", "Hankintameno €",
               "Voitto/tappio €", "Lähde", "Short"])
    r0 = lu.r
    for m in b.matches:
        r = lu.r
        lu.row([m.symbol, m.sale_date, m.buy_date, m.qty, round(m.proceeds, 2), round(m.cost, 2), f"=E{r}-F{r}",
                m.source, "Kyllä" if m.short else ""],
               ["in", "in", "in", "in", "in", "in", "f", "t", "t"], fmt=[None, None, None, "#,##0.####"])
    r1 = max(lu.r - 1, r0)
    LU = dict(sym=f"'{lu.name}'!$A${r0}:$A${r1}", L=f"'{lu.name}'!$E${r0}:$E${r1}",
              H=f"'{lu.name}'!$F${r0}:$F${r1}", R=f"'{lu.name}'!$G${r0}:$G${r1}")
    rt = lu.row(["Yhteensä", None, None, None, f"=SUM(E{r0}:E{r1})", f"=SUM(F{r0}:F{r1})", f"=SUM(G{r0}:G{r1})"],
                bold=True, total=True)
    ref.update(L=lu.q(f"E{rt}"), H=lu.q(f"F{rt}"))
    rt = lu.row(["Voitot", None, None, None, None, None, f'=SUMIF(G{r0}:G{r1},">0")'], bold=True)
    ref["G"] = lu.q(f"G{rt}")
    rt = lu.row(["Tappiot", None, None, None, None, None, f'=SUMIF(G{r0}:G{r1},"<0")'], bold=True)
    ref["T"] = lu.q(f"G{rt}")

    # ---------------------------------------------------------------- Arvopaperit yhteenveto
    sm.title("Arvopaperit symboleittain", [sub, "Vertailu: IBKR R&U (IBKR muuntaa voiton myyntipäivän kurssilla; Vero käyttää kahta kurssia)."])
    sm.header(["Symboli", "Luovutushinnat", "Hankintamenot", "Voitot", "Tappiot", "Netto (FIFO)", "IBKR R&U", "Ero", "Huom."])
    syms = sorted({m.symbol for m in b.matches} | set(b.ru_by_symbol))
    for sym in syms:
        r = sm.row([sym, f'=SUMIF({LU["sym"]},A{sm.r},{LU["L"]})', f'=SUMIF({LU["sym"]},A{sm.r},{LU["H"]})',
                    f'=SUMIFS({LU["R"]},{LU["sym"]},A{sm.r},{LU["R"]},">0")',
                    f'=SUMIFS({LU["R"]},{LU["sym"]},A{sm.r},{LU["R"]},"<0")', f"=D{sm.r}+E{sm.r}",
                    b.ru_by_symbol.get(sym, 0.0), f"=F{sm.r}-G{sm.r}",
                    "Avaava erä edellisvuodelta" if any(m.symbol == sym and m.source != "FIFO" for m in b.matches) else ""],
                   ["in", "f", "f", "f", "f", "f", "in", "f", "t"])

    # ---------------------------------------------------------------- Johdannaiset
    de.title("Johdannaiset", [sub, "Futuurit ja optiot: IBKR Realized & Unrealized Performance Summary (realisoidut, EUR).",
                                  "CFD:t erikseen alla: muuta pääomatuloa, tappiot vähennyskelvottomia."])
    de.section("FUTUURIT JA OPTIOT (luovutusvoitot ja -tappiot, 9A)", 6)
    de.header(["Luokka", "Symboli", "Voitot", "Tappiot", "Netto", "Huom."])
    r0 = de.r
    for r_ in b.derivatives:
        r = de.r
        de.row([r_.asset_class, r_.symbol, r_.profit, r_.loss, f"=C{r}+D{r}"], ["in", "in", "in", "in", "f"])
    r1 = max(de.r - 1, r0)
    rt = de.row(["Yhteensä", None, f"=SUM(C{r0}:C{r1})" if b.derivatives else 0, f"=SUM(D{r0}:D{r1})" if b.derivatives else 0,
                 f"=C{de.r}+D{de.r}"], bold=True, total=True)
    ref.update(DG=de.q(f"C{rt}"), DL=de.q(f"D{rt}"))
    de.blank()
    fx = [x for x in st.ru if x.asset_class == "Forex"]
    if fx:
        r = de.row(["Valuutat (IBKR Forex)", "USD ym.", sum(x.profit for x in fx), sum(x.loss for x in fx), f"=C{de.r}+D{de.r}",
                    "Mukana verotuksessa" if s.include_fx else "EI mukana: sisältyy jo osakkeiden EUR-tulokseen"],
                   ["t", "t", "in", "in", "f", "t"])
        ref.update(FXG=de.q(f"C{r}") if s.include_fx else "0", FXL=de.q(f"D{r}") if s.include_fx else "0")
    else:
        ref.update(FXG="0", FXL="0")
    de.blank()
    de.section("CFD:T (muu pääomatulo, 16B) — voitot kauppakohtaisesti, tappioita ei huomioida", 6)
    de.header(["Päivä", "Symboli", "Tulos €", "Luokka", None, "Lähde"])
    r0 = de.r
    for x in b.cfd_rows:
        de.row([x["date"], x["symbol"], round(x["eur"], 2), x["cls"], None, x["source"]], ["in", "in", "in", "in", None, "t"])
    r1 = max(de.r - 1, r0)
    rt = de.row(["Voitot (veronalainen muu pääomatulo)", None, f'=SUMIF(C{r0}:C{r1},">0")' if b.cfd_rows else 0],
                bold=True, total=True)
    ref["CFG"] = de.q(f"C{rt}")
    rt = de.row(["Tappiot (vähennyskelvottomia, ei huomioida)", None, f'=SUMIF(C{r0}:C{r1},"<0")' if b.cfd_rows else 0],
                bold=True)
    ref["CFL"] = de.q(f"C{rt}")
    de.note("Verohallinto: CFD-hinnanerosopimuksiin ei sovelleta luovutusvoittosäännöksiä; voitto on pääomatuloa ja tappiota "
            "ei voi vähentää. Kukin kauppa arvioidaan erikseen. IBKR:n CFD-provisioita ei ole vähennetty voitoista.")

    # ---------------------------------------------------------------- Osingot & lähdeverot
    dv.title("Osingot, payment in lieu ja lähdeverot", sub)
    dv.header(["Päivä", "Kuvaus", "Val.", "Määrä", "EUR", "Tyyppi"])
    r0 = dv.r
    for x in st.dividends:
        dv.row([x.date, x.description, x.currency, x.amount, x.amount_eur, "PIL" if _is_pil(x.description) else "Osinko"],
               ["in", "in", "in", "in", "in", "in"])
    r1 = max(dv.r - 1, r0)
    rt = dv.row(["Osingot (brutto)", None, None, None, f'=SUMIF(F{r0}:F{r1},"Osinko",E{r0}:E{r1})'], bold=True)
    ref["div"] = dv.q(f"E{rt}")
    rt = dv.row(["Payment in lieu", None, None, None, f'=SUMIF(F{r0}:F{r1},"PIL",E{r0}:E{r1})'], bold=True)
    ref["pil"] = dv.q(f"E{rt}")
    dv.blank()
    dv.section("LÄHDEVEROT", 8)
    for x in st.withholding:
        dv.row([x.date, x.description, x.currency, x.amount, x.amount_eur,
                "Osinko" if _is_div_wht(x.description) else "Korko", wht_country(x.description, x.currency)],
               ["in", "in", "in", "in", "in", "in", "in"])
    dv.blank()
    dv.section("ULKOMAISEN VERON HYVITYS", 8)
    dv.header(["Maa", "Tulolaji", "Brutto €", "Lähdevero €", "Toteutunut %", "Sopimus-%", "Hyvitys €", "Palautettava €"])
    cr = []
    for w in b.wht_rows:
        r = dv.r
        dv.row([w["country"], w["type"], w["gross"], w["wht"], f"=IFERROR(D{r}/C{r},0)", w["treaty"], w["credit"],
                f"=D{r}-G{r}"], ["in", "in", "in", "in", "f", "in", "in", "f"], fmt=[None, None, None, None, PCT, PCT])
        cr.append(r)
    if cr:
        rt = dv.row(["Yhteensä", None, None, None, None, None, f"=SUM(G{cr[0]}:G{cr[-1]})", f"=SUM(H{cr[0]}:H{cr[-1]})"],
                    bold=True, total=True)
        ref.update(credit=dv.q(f"G{rt}"), reclaim=dv.q(f"H{rt}"))
    else:
        ref.update(credit="0", reclaim="0")
    dv.note("Hyvitys = MIN(lähdevero, sopimusraja × brutto, Suomen vero tulosta). Ylitys haetaan lähdevaltiosta (DK: SKAT).")

    # ---------------------------------------------------------------- Korot & kulut
    kk.title("Korot ja kulut", sub)
    kk.header(["Päivä", "Kuvaus", "Val.", "Määrä", "EUR", "Käsittely"])
    r0 = kk.r
    CFDC = "CFD-kulu (ei vähennyskelpoinen)"
    for x in st.interest:
        kk.row([x.date, x.description, x.currency, x.amount, x.amount_eur,
                "Korkotulo" if x.amount_eur > 0 else CFDC if _is_cfd_cost(x.description) else "Korko tulonhankkimisvelasta"],
               ["in", "in", "in", "in", "in", "t"])
    r1 = max(kk.r - 1, r0)
    rt = kk.row(["Korkotulot", None, None, None, f'=SUMIF(F{r0}:F{r1},"Korkotulo",E{r0}:E{r1})'], bold=True)
    ref["ii"] = kk.q(f"E{rt}")
    rt = kk.row(["Korkokulut (vähennys)", None, None, None, f'=-SUMIF(F{r0}:F{r1},"Korko tulonhankkimisvelasta",E{r0}:E{r1})'],
                bold=True)
    ref["ie"] = kk.q(f"E{rt}")
    kk.blank()
    r0 = kk.r
    for x in st.fees:
        kk.row([x.date, x.description, x.currency, x.amount, x.amount_eur,
                CFDC if _is_cfd_cost(x.description) else "Tulonhankkimismeno"], ["in", "in", "in", "in", "in", "t"])
    r1 = max(kk.r - 1, r0)
    rt = kk.row(["Muut tulonhankkimismenot", None, None, None,
                 f'=-SUMIF(F{r0}:F{r1},"Tulonhankkimismeno",E{r0}:E{r1})' if st.fees else 0], bold=True, total=True)
    ref["fees"] = kk.q(f"E{rt}")

    # ---------------------------------------------------------------- Pääomatulo & vero
    po.title("Pääomatulo ja vero (arvio)", [sub, "Vain IBKR-tilin osuus. Muut pääomatulot ja ansiotulot lisätään OmaVerossa."])
    po.header(["Erä", "EUR", "Peruste"])
    def prow(label, f, note="", kind="f", bold=False, total=False, key=None):
        r = po.row([label, f, note], ["t", kind, "t"], bold=bold, total=total)
        if key:
            ref[key] = po.q(f"$B${r}")
        return f"B{r}"
    po.section("LUOVUTUKSET", 3)
    ex = prow("Pienten luovutusten verovapaus sovelletaan?", f'=IF(AND({ref["L"]}>0,{ref["L"]}<={ref["small"]}),"Kyllä","Ei")',
              "Luovutushinnat ≤ raja")
    g1 = prow("Arvopapereiden voitot", f'=IF({ex}="Kyllä",0,{ref["G"]})', "Luovutukset (FIFO)", "link")
    l1 = prow("Arvopapereiden tappiot", f'=IF(AND({ex}="Kyllä",{ref["H"]}<={ref["small"]}),0,{ref["T"]})', "", "link")
    g2 = prow("Johdannaisten voitot", f"={ref['DG']}", "Johdannaiset", "link")
    l2 = prow("Johdannaisten tappiot", f"={ref['DL']}", "Johdannaiset", "link")
    g3 = prow("Valuutat (jos mukana)", f"={ref['FXG']}+{ref['FXL']}", "Johdannaiset-välilehti", "link")
    dn = prow("Luovutusvoitot − tappiot", f"={g1}+{l1}+{g2}+{l2}+{g3}", bold=True, total=True)
    po.section("MUUT PÄÄOMATULOT", 3)
    d1 = prow("Osingot × veronalainen osuus", f"={ref['div']}*{ref['divsh']}", "85 % listatuista yhtiöistä")
    d2 = prow("Payment in lieu × veronalainen osuus", f"={ref['pil']}*{ref['pilsh']}")
    d3 = prow("Korkotulot", f"={ref['ii']}", "", "link")
    d4 = prow("CFD-voitot (voitolliset kaupat)", f"={ref['CFG']}", "Johdannaiset — tappioita ei vähennetä", "link")
    po.section("VÄHENNYKSET", 3)
    k1 = prow("Korot tulonhankkimisvelasta", f"=-{ref['ie']}", "", "link")
    k2 = prow("Muut tulonhankkimismenot", f"=-{ref['fees']}", "", "link")
    cf = prow("Aiempien vuosien luovutustappiot", f"=-MIN({ref['cf']},MAX(0,{dn}+{d1}+{d2}+{d3}+{d4}))", "Asetukset")
    pi = prow("PÄÄOMATULO (IBKR-osuus)", f"={dn}+{d1}+{d2}+{d3}+{d4}+{k1}+{k2}+{cf}", bold=True, total=True, key="po")
    po.ws.cell(int(pi[1:]), 2).fill = FILL_KEY
    tg = prow("Pääomatulovero", f"=MIN(MAX({pi},0),{ref['br']})*{ref['r1']}+MAX({pi}-{ref['br']},0)*{ref['r2']}",
              "30 % / 34 %", key="tg")
    tc = prow("− Ulkomaisen veron hyvitys", f"=-MIN({ref['credit']},{tg})", "Osingot & lähdeverot", "link", key="tc")
    prow("Vero netto (arvio)", f"={tg}+{tc}", bold=True, total=True, key="tn")
    prow("Lähdevaltioista palautettavissa", f"={ref['reclaim']}", "DK: SKAT · IE: Revenue", "link")
    if b.cfd_rows:
        prow("Tieto: CFD-tappiot, joita ei huomioida (ei mukana yllä)", f"={ref['CFL']}", "Verohallinto: vähennyskelvottomia", "link")
    prow("Negatiivinen tulos → vahvistettava tappio / alijäämähyvitys", f"=IF({pi}<0,-{pi},0)",
         "Vero vahvistaa luovutustappion (5 v); korkojen alijäämä hyvitetään ansiotulojen verosta")

    # ---------------------------------------------------------------- OmaVero-kentät
    om.title("OmaVero — täytettävät tiedot", [sub, "Paljon kauppoja: ilmoita yhteenvetona ja liitä tämä työkirja erittelyksi."])
    om.header(["Osio", "Kenttä", "EUR", "Huom."])
    links = {
        "Osakkeet ja rahastot — luovutushinnat yhteensä": f"={ref['L']}",
        "Osakkeet ja rahastot — hankintamenot ja kulut yhteensä": f"={ref['H']}",
        "Osakkeet ja rahastot — luovutusvoitot yhteensä": f"={ref['G']}",
        "Osakkeet ja rahastot — luovutustappiot yhteensä": f"=-{ref['T']}",
        "Johdannaiset (futuurit, optiot) — voitot": f"={ref['DG']}",
        "Johdannaiset (futuurit, optiot) — tappiot": f"=-{ref['DL']}",
        "Muut pääomatulot — CFD-voitot": f"={ref['CFG']}",
        "Vähennyskelvottomat CFD-tappiot (ei huomioida)": f"=-{ref['CFL']}",
        "Korot tulonhankkimisvelasta (marginaalilaina)": f"={ref['ie']}",
        "Muut tulonhankkimismenot (IBKR-kulut)": f"={ref['fees']}",
    }
    from .personal import omavero_fields
    last = None
    for sec, fld, val, note in omavero_fields(b):
        if sec != last:
            om.section(sec, 4)
            last = sec
        f = links.get(fld, val)
        om.row([None, fld, f, note], [None, "t", "link" if isinstance(f, str) else "in", "t"])
    om.blank()
    om.section("ARVIO", 4)
    for lab, k in [("Pääomatulo (IBKR-osuus)", "po"), ("Pääomatulovero", "tg"), ("Ulkomaisen veron hyvitys", "tc"),
                   ("Vero netto (arvio)", "tn")]:
        om.row([None, lab, f"={ref[k]}"], [None, "t", "link"], bold=(k == "tn"))
    if b.warnings:
        om.blank()
        om.section("HUOMIOT", 4)
        for w in b.warnings:
            om.note("⚠ " + w)

    # ---------------------------------------------------------------- Muistio
    mu.title("Muistio", sub)
    mu.header(["Aihe", "Selitys"])
    for k, t in [
        ("FIFO", "Verohallinto edellyttää, että samanlajiset arvopaperit katsotaan myydyiksi hankintajärjestyksessä (FIFO) "
                 "arvo-osuustilikohtaisesti. Tämä työkirja laskee FIFO:n itse IBKR:n kauppariveistä."),
        ("Valuuttakurssit", "Luovutushinta muunnetaan euroiksi myyntipäivän ja hankintameno ostopäivän kurssilla "
                            "(IBKR Forex P/L Details, kauppakohtaiset EUR-määrät)."),
        ("Hankintameno-olettama", "20 % (40 % jos omistettu ≥ 10 v) myyntihinnasta voidaan käyttää todellisen hankintamenon "
                                  "sijaan, jos se on suurempi — kannattaa vain suurivoittoisissa, pitkään pidetyissä erissä."),
        ("Johdannaiset", "Futuurit ja optiot: voitot ja tappiot IBKR:n realisoiduista tuloksista. Tappiot vähennetään "
                         "luovutusvoitoista ja muista pääomatuloista (5 v)."),
        ("CFD:t", "Verohallinto: CFD-hinnanerosopimuksiin ei sovelleta luovutusvoittoverotuksen säännöksiä. Voitto on "
                  "pääomatuloa (OmaVero: muut pääomatulot), tappiota ei huomioida verotuksessa millään tavalla, ja jokainen "
                  "kauppa arvioidaan erikseen. Laskelma: kunkin sulkevan kaupan IBKR:n realisoitu tulos (CSV Trades, EUR "
                  "luokan provisiosuhteella); voitolliset kaupat veronalaisia, tappiolliset jätetään huomiotta. Ei "
                  "hankintameno-olettamaa eikä pienten luovutusten vapautusta. IBKR:n CFD-provisioita ja CFD-rahoituskuluja "
                  "ei vähennetä (varovainen tulkinta — tarkista tarvittaessa Verohallinnolta)."),
        ("Valuutat", "IBKR:n Forex-riviä ei oletuksena oteta mukaan: EUR-perusvaluuttatilillä sen vaikutus sisältyy jo "
                     "osakkeiden EUR-määräisiin luovutushintoihin ja hankintamenoihin."),
        ("Osingot", "Listattujen yhtiöiden osingoista 85 % on veronalaista pääomatuloa. Lähdevero hyvitetään sopimusrajaan asti; "
                    "ylitys haetaan lähdevaltiosta."),
        ("Korot", "Arvopapereiden ostoon käytetyn marginaalilainan korot ovat vähennyskelpoisia korkoja tulonhankkimisvelasta."),
    ]:
        r = mu.row([k, t], ["t", "t"])
        mu.ws.cell(r, 2).alignment = Alignment(wrap_text=True, vertical="top")

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
    return workbook_bytes(wb)   # in memory: no temp files on disk
