"""Excel workbook writer. Every derived figure is a live formula; statement data are inputs (blue)."""
from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .xlsx_mem import workbook_bytes

from .books import Books, _is_div_wht, _is_pil, classify_transfers, wht_country
from .parse_common import CFD_CLASSES

Y8_LABELS = {"addback": "Asetettu optio: lisätään takaisin (OPT-Y8)",
             "deduct": "Asetettu optio: vähennetään (kirjanpito; ei lähdettä)",
             "fair_value": "Asetettu optio: EVL 27 e § (käypä arvo)"}
from .version import __version__

FONT = "Arial"
NUM = '#,##0.00;-#,##0.00;"–"'
PCT = '0.0%'
F_BASE = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_TITLE = Font(name=FONT, size=14, bold=True, color="1F3864")
F_SUB = Font(name=FONT, size=9, italic=True, color="595959")
F_HDR = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_INPUT = Font(name=FONT, size=10, color="0000FF")
F_LINK = Font(name=FONT, size=10, color="008000")
F_SEC = Font(name=FONT, size=10, bold=True, color="1F3864")
FILL_HDR = PatternFill("solid", fgColor="1F3864")
FILL_SEC = PatternFill("solid", fgColor="DDE4F0")
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
FILL_TOT = PatternFill("solid", fgColor="F2F2F2")
TOP = Border(top=Side(style="thin", color="808080"))


class Sheet:
    def __init__(self, wb, title, widths):
        self.ws = wb.create_sheet(title)
        self.name = title
        self.r = 1
        for i, w in enumerate(widths, 1):
            self.ws.column_dimensions[get_column_letter(i)].width = w

    def q(self, cell):  # cross-sheet reference
        return f"'{self.name}'!{cell}"

    def title(self, text, sub=None):
        self.ws.cell(self.r, 1, text).font = F_TITLE
        self.r += 1
        if sub:
            for s_ in sub if isinstance(sub, list) else [sub]:
                self.ws.cell(self.r, 1, s_).font = F_SUB
                self.r += 1
        self.r += 1

    def header(self, cols):
        for i, c in enumerate(cols, 1):
            x = self.ws.cell(self.r, i, c)
            x.font, x.fill = F_HDR, FILL_HDR
            x.alignment = Alignment(wrap_text=True, vertical="center")
        self.r += 1

    def section(self, text, ncols):
        for i in range(1, ncols + 1):
            self.ws.cell(self.r, i).fill = FILL_SEC
        self.ws.cell(self.r, 1, text).font = F_SEC
        self.r += 1

    def row(self, values, kinds=None, bold=False, total=False, fmt=None):
        """kinds per column: 'in' (input/blue), 'link' (green), 'f' (formula/black), 't' (text)."""
        kinds = kinds or []
        r = self.r
        for i, val in enumerate(values, 1):
            if val is None:
                continue
            c = self.ws.cell(r, i, val)
            k = kinds[i - 1] if i - 1 < len(kinds) else None
            c.font = (F_INPUT if k == "in" else F_LINK if k == "link" else F_BOLD if bold else F_BASE)
            if bold and k in ("link", "in"):
                c.font = Font(name=FONT, size=10, bold=True, color=c.font.color)
            if isinstance(val, (int, float)) or (isinstance(val, str) and val.startswith("=")):
                c.number_format = fmt[i - 1] if fmt and i - 1 < len(fmt) and fmt[i - 1] else NUM
            if total:
                c.fill, c.border = FILL_TOT, TOP
        self.r += 1
        return r

    def note(self, text, col=1):
        c = self.ws.cell(self.r, col, text)
        c.font = F_SUB
        c.alignment = Alignment(wrap_text=False)
        self.r += 1

    def blank(self, n=1):
        self.r += n


def write_workbook(b: Books) -> bytes:
    st, s, v = b.st, b.s, b.v
    A = s.accounts
    wb = Workbook()
    wb.remove(wb.active)
    ref: dict[str, str] = {}
    period = f"{st.period_start} – {st.period_end}"
    company = s.company or st.name
    hdr_sub = f"{company} · IBKR {st.account} · {period} · Base currency {st.base_currency}"

    # order of tabs (created now, filled below so cross-refs exist)
    ys = Sheet(wb, "Yhteenveto", [46, 18, 18, 70])
    tk = Sheet(wb, "Tilikartta", [8, 52, 16, 16, 16, 9, 60])
    dw = Sheet(wb, "Talletukset & nostot", [12, 46, 8, 16, 16, 40])
    rp = Sheet(wb, "Realisoitu P_L", [12, 22, 15, 15, 15, 15, 9, 15, 15, 40])
    kk = Sheet(wb, "Kulut & korot", [12, 58, 8, 14, 14, 10, 8, 30])
    os_ = Sheet(wb, "Osingot", [12, 62, 8, 14, 14, 18, 30])
    vp = Sheet(wb, "Vuoden lopun positiot", [12, 22, 12, 8, 16, 16, 16, 16, 16, 30])
    evl = Sheet(wb, "EVL-täsmäytys", [64, 16, 70])
    nav = Sheet(wb, "NAV-täsmäytys", [64, 16, 16, 14, 60])
    asx = Sheet(wb, "Asetukset", [44, 26, 70])
    muis = Sheet(wb, "Verotus-muistio", [34, 140])

    # ================================================================ Asetukset
    asx.title("Asetukset — syötteet ja valinnat", ["Keltaiset solut ovat muokattavia. Muut välilehdet laskevat näistä."])
    asx.header(["Asetus", "Arvo", "Selite"])
    asx.row(["Yhtiö", company, "From statement"], ["t", "t", "t"])
    asx.row(["IBKR-tili", st.account, ""], ["t", "t"])
    asx.row(["Kausi", period, f"{st.title}"], ["t", "t", "t"])
    asx.row(["Lähdetiedostot", ", ".join(st.source_files), ""], ["t", "t"])
    def inp(label, value, note, key, fmt=None, validation=None):
        r = asx.row([label, value, note], ["t", "in", "t"], fmt=[None, fmt, None])
        asx.ws.cell(r, 2).fill = FILL_KEY
        ref[key] = asx.q(f"$B${r}")
        if validation:
            dv = DataValidation(type="list", formula1=validation, allow_blank=False)
            asx.ws.add_data_validation(dv)
            dv.add(asx.ws.cell(r, 2))
    inp("Osakkeiden omaisuuslaji (EVL)", s.share_category,
        "'muu omaisuus' (EVL 12 a §): arvonalentumiset ei vähennyskelpoisia ennen luovutusta, osaketappiot "
        "EVL 8 a § -rajoituksen alaisia. 'rahoitusomaisuus' (EVL 9 §): sovi kirjanpitäjän kanssa.",
        "cat", validation='"muu omaisuus,rahoitusomaisuus"')
    inp("Yhteisöverokanta", s.tax_rate, "Yhteisövero 20 %", "tax", PCT)
    inp("Avaavat arvonalentumiset 1.1. (€)", s.opening_writedowns,
        "Edellisen tilinpäätöksen arvonalentumiset avoimista positioista (tämän tiedoston 'Realisoitu P_L' tot. edellisvuodelta).", "wd_open")
    inp("Avaavat kirjaamattomat arvonnousut 1.1. (€)", s.opening_unbooked_gains,
        "Edellisvuoden lopun realisoitumattomat voitot, joita ei kirjattu (KPL 5:6).", "ug_open")
    inp("Aiempien vuosien käyttämättömät osaketappiot (EVL 8 a §) (€)", s.evl8a_carryforward,
        "Vahvistetut muun omaisuuden luovutustappiot, 5 vuotta.", "cf")
    inp("Aiemmin verotetut asetettujen optioiden preemiot (€)", s.wopt_premium_carry,
        "OPT-Y2: OTC- tai yli 18 kk:n asetetut optiot, jotka suljettiin, toteutettiin tai raukesivat tällä tilikaudella "
        "ja joiden preemio verotettiin asetusvuonna — vähennetään nyt.", "wopt_cf")
    inp("Edellisellä tilikaudella lisätyt asetettujen optioiden tappiot (€)", s.wopt_loss_carry,
        "OPT-Y8: edellisen vuoden EVL-täsmäytyksessä takaisin lisätty avoimien asetettujen optioiden tilinpäätöstappio "
        "(sisältyy avaaviin arvonalentumisiin) — vähennetään nyt.", "wopt_loss_cf")
    inp("Hyvitetäänkö korkojen lähdevero Suomessa?", "Kyllä" if s.credit_interest_wht else "Ei",
        "Oletus Ei: FI–IE-sopimus → korko verotetaan vain Suomessa; Irlannin 20 % palautetaan (Form 8-3-6).",
        "intcredit", validation='"Kyllä,Ei"')
    asx.blank()
    asx.note("Väri-koodit: sininen = syöte (IBKR-raportista tai käyttäjältä), musta = kaava, vihreä = linkki toiselle välilehdelle.")
    asx.note(f"Laskettu versiolla IBKR-yhteenveto {__version__} · {date.today().isoformat()}")

    # ================================================================ Talletukset & nostot
    dw.title("Talletukset & nostot", hdr_sub)
    dw.ws.column_dimensions["F"].width = 12
    dw.ws.column_dimensions["G"].width = 44
    dw.header(["Päivä", "Kuvaus", "Val.", "Määrä", "Määrä (EUR)", "Tyyppi", "Käsittely"])
    r0 = dw.r
    for x, kind in zip(st.deposits, classify_transfers(st.deposits)):
        treat = {"Talletus": "Siirto yhtiön pankkitililtä (1900)",
                 "Nosto": "Siirto yhtiön pankkitilille (1900)",
                 "Peruttu": "Peruttu siirto — pari nettoutuu nollaan, ei kirjata"}.get(kind, "Tarkista: peruutukselle ei löytynyt paria")
        dw.row([x.date, x.description, x.currency, x.amount, x.amount_eur, kind, treat],
               ["in", "in", "in", "in", "in", "in", "t"])
    r1 = dw.r - 1
    rng = f"E{r0}:E{max(r1, r0)}"
    krng = f"F{r0}:F{max(r1, r0)}"
    dvk = DataValidation(type="list", formula1='"Talletus,Nosto,Peruttu"')
    dw.ws.add_data_validation(dvk)
    dvk.add(krng)
    rt = dw.row(["Talletukset", None, None, None, f'=SUMIF({krng},"Talletus",{rng})'], bold=True)
    ref["dep_in"] = dw.q(f"E{rt}")
    rt = dw.row(["Nostot", None, None, None, f'=SUMIF({krng},"Nosto",{rng})'], bold=True)
    ref["dep_out"] = dw.q(f"E{rt}")
    dw.row(["Perutut siirrot (netto, pitää olla 0)", None, None, None,
            f'=SUM({rng})-SUMIF({krng},"Talletus",{rng})-SUMIF({krng},"Nosto",{rng})'])
    rt = dw.row(["Nettosiirrot IBKR-tilille", None, None, None, f"=SUM({rng})"], bold=True, total=True)
    ref["dep_net"] = dw.q(f"E{rt}")

    # ================================================================ Realisoitu P_L
    rp.title("Realisoidut ja realisoitumattomat tulokset arvopapereittain (EUR)",
             [hdr_sub, "Lähde: IBKR Realized & Unrealized Performance Summary. EUR-määrät kauppapäivien kursseilla (Verohallinnon käytäntö).",
              "Alin arvo (KPL 5:6): realisoitumaton tappio = arvonalentuminen; realisoitumatonta voittoa ei kirjata."])
    rp.header(["Omaisuusluokka", "Symboli", "Voitot", "Tappiot", "Realisoitu netto", "Realisoitumaton",
               "Osake (EVL 8 a)", "Arvonalentuminen", "Kirjaamaton arvonnousu", "Huom."])
    r0 = rp.r
    y8 = {w["symbol"]: w for w in b.wopt_y8}
    y8_cells = []
    for x in b.symbols:
        r = rp.r
        w = y8.get(x.symbol) if x.asset_class != "Stocks" else None
        huom = (Y8_LABELS[w["applied"]] if w else
                "ETF/rahasto – ei EVL 8 a" if (x.asset_class == "Stocks" and not x.is_share) else "")
        rp.row([x.asset_class, x.symbol, x.realized_profit, x.realized_loss, f"=C{r}+D{r}", x.unrealized,
                "Kyllä" if x.is_share else "Ei", f"=MAX(-F{r},0)", f"=MAX(F{r},0)", huom],
               ["t", "t", "in", "in", "f", "in", "in", "f", "f", "in" if w else "t"])
        if w:
            y8_cells.append(f"J{r}")
    r1 = max(rp.r - 1, r0)
    if y8_cells:
        dvy = DataValidation(type="list", formula1='"' + ",".join(Y8_LABELS.values()) + '"', allow_blank=False)
        rp.ws.add_data_validation(dvy)
        for c_ in y8_cells:
            dvy.add(c_)
    dvs = DataValidation(type="list", formula1='"Kyllä,Ei"')
    rp.ws.add_data_validation(dvs)
    dvs.add(f"G{r0}:G{r1}")
    rt = rp.row(["Yhteensä (kirjataan)", None, f"=SUM(C{r0}:C{r1})", f"=SUM(D{r0}:D{r1})", f"=SUM(E{r0}:E{r1})",
                 f"=SUM(F{r0}:F{r1})", None, f"=SUM(H{r0}:H{r1})", f"=SUM(I{r0}:I{r1})"], bold=True, total=True)
    ref.update(gains=rp.q(f"C{rt}"), losses=rp.q(f"D{rt}"), unrl=rp.q(f"F{rt}"), wd=rp.q(f"H{rt}"), ug=rp.q(f"I{rt}"))
    rows_rng = (r0, r1)
    rt2 = rp.row(["  josta osakkeet (EVL 8 a)", None, f'=SUMIF(G{r0}:G{r1},"Kyllä",C{r0}:C{r1})',
                  f'=SUMIF(G{r0}:G{r1},"Kyllä",D{r0}:D{r1})', None, None, None,
                  f'=SUMIF(G{r0}:G{r1},"Kyllä",H{r0}:H{r1})'])
    ref.update(share_gains=rp.q(f"C{rt2}"), share_losses=rp.q(f"D{rt2}"), share_wd=rp.q(f"H{rt2}"))
    rt3 = rp.row(["  josta futuurit", None, None, None, None, None, None,
                  f'=SUMIF(A{r0}:A{r1},"Futures",H{r0}:H{r1})', f'=SUMIF(A{r0}:A{r1},"Futures",I{r0}:I{r1})'])
    ref.update(fut_ug=rp.q(f"I{rt3}"))
    rt4 = rp.row(["  josta avoimet asetetut optiot (OPT-Y8)", None, None, None, None, None, None,
                  f'=SUMIF(J{r0}:J{r1},"Asetettu optio:*",H{r0}:H{r1})'])
    rt5 = rp.row(["    joista lisätään takaisin verotuksessa", None, None, None, None, None, None,
                  f'=SUMIF(J{r0}:J{r1},"{Y8_LABELS["addback"]}",H{r0}:H{r1})'])
    ref.update(wopt_wd=rp.q(f"H{rt4}"), wopt_add=rp.q(f"H{rt5}"))
    ref["other_wd"] = f"({ref['wd']}-{ref['share_wd']}-{ref['wopt_wd']})"
    rp.blank()
    rp.section("MUISTIO — IBKR:n Forex-rivi (EI kirjata: sisältyy jo EUR-määräisiin osake-/futuuritulokseen)", 10)
    for r in [x for x in st.ru if x.asset_class == "Forex"]:
        rr = rp.r
        rp.row(["Forex", r.symbol, r.profit, r.loss, f"=C{rr}+D{rr}", r.unrealized], ["t", "t", "in", "in", "f", "in"])
        ref.setdefault("fx_memo_rows", []).append(rr)
    if "fx_memo_rows" in ref:
        a_, z_ = ref["fx_memo_rows"][0], ref["fx_memo_rows"][-1]
        ref["ru_fx_total"] = rp.q(f"E{a_}") if a_ == z_ else f"SUM({rp.q(f'E{a_}:E{z_}')})"
        ref["ru_fx_unrl"] = rp.q(f"F{a_}") if a_ == z_ else f"SUM({rp.q(f'F{a_}:F{z_}')})"
    rp.note("Todellinen valuuttakurssiero (marginaalilainan ja käteisen kurssimuutos) lasketaan NAV-täsmäytyksessä: "
            "kaupankäynnin tulos − realisoidut − realisoitumattomien muutos.")

    # ================================================================ Kulut & korot
    kk.title("Korot, kulut, transaktioverot ja lähdeverot", hdr_sub)
    kk.header(["Päivä", "Kuvaus", "Val.", "Määrä", "EUR", "Tyyppi", "Maa", "Käsittely"])
    kk.section("KOROT (bruttona: tuotot ja kulut erikseen)", 8)
    r0 = kk.r
    for x in st.interest:
        kk.row([x.date, x.description, x.currency, x.amount, x.amount_eur,
                "Tuotto" if x.amount_eur > 0 else "Kulu"], ["in", "in", "in", "in", "in", "f"])
    r1 = max(kk.r - 1, r0)
    rt = kk.row(["Korkotuotot (9180)", None, None, None, f'=SUMIF(E{r0}:E{r1},">0")'], bold=True)
    ref["int_inc"] = kk.q(f"E{rt}")
    rt = kk.row(["Korkokulut (9442)", None, None, None, f'=SUMIF(E{r0}:E{r1},"<0")'], bold=True)
    ref["int_exp"] = kk.q(f"E{rt}")
    kk.note("Muunnos EUR: rivit valuuttaryhmän 'Total in EUR' / 'Total' -suhteella (IBKR:n oma muunnos).")
    kk.blank()
    kk.section("MUUT KULUT (Fees)", 8)
    r0 = kk.r
    for x in st.fees:
        kk.row([x.date, x.description, x.currency, x.amount, x.amount_eur], ["in", "in", "in", "in", "in"])
    r1 = max(kk.r - 1, r0)
    rt = kk.row(["Muut rahoituskulut (9446)", None, None, None, f"=SUM(E{r0}:E{r1})" if st.fees else 0], bold=True, total=True)
    ref["fees"] = kk.q(f"E{rt}")
    kk.blank()
    kk.section("TRANSAKTIOVEROT (esim. Ranskan FTT)", 8)
    if st.transaction_fee_lines and s.transaction_fees_override is None:
        r0 = kk.r
        for x in st.transaction_fee_lines:
            kk.row([x.date, x.description, x.currency, x.amount, x.amount_eur], ["in", "in", "in", "in", "in"])
        rt = kk.row(["Transaktioverot (9445)", None, None, None, f"=SUM(E{r0}:E{kk.r - 1})"], bold=True, total=True)
    else:
        src = ("Syötetty käsin (Activity Statement: Transaction Fees / Change in NAV)"
               if s.transaction_fees_override is not None else
               "IBKR Change in NAV" if "Transaction Fees" in st.change_in_nav else
               "EI LÖYTYNYT raportista — syötä tähän jos FR/IT/ES-osakekauppoja")
        rt = kk.row(["Transaktioverot (9445)", src, None, None, v["ftt"]], ["t", "t", None, None, "in"], bold=True, total=True)
        kk.ws.cell(rt, 5).fill = FILL_KEY
    ref["ftt"] = kk.q(f"E{rt}")
    kk.blank()
    kk.section("LÄHDEVEROT", 8)
    r0 = kk.r
    for x in st.withholding:
        typ = "Osinko" if _is_div_wht(x.description) else "Korko"
        kk.row([x.date, x.description, x.currency, x.amount, x.amount_eur, typ, wht_country(x.description, x.currency)],
               ["in", "in", "in", "in", "in", "in", "in"])
    r1 = max(kk.r - 1, r0)
    rt = kk.row(["Lähdeverot osingoista (9981)", None, None, None, f'=SUMIF(F{r0}:F{r1},"Osinko",E{r0}:E{r1})'], bold=True)
    ref["wht_div"] = kk.q(f"E{rt}")
    rt = kk.row(["Lähdeverot koroista (9982)", None, None, None, f'=SUMIF(F{r0}:F{r1},"Korko",E{r0}:E{r1})'], bold=True)
    ref["wht_int"] = kk.q(f"E{rt}")
    kk.blank()
    kk.section("MUISTIO — PROVISIOT (sisältyvät jo hankintamenoihin / luovutushintoihin, EI kirjata erikseen)", 8)
    for cls, val in st.commissions_by_class.items():
        kk.row([None, f"Commissions — {cls}", "EUR", None, val], [None, "t", "t", None, "in"])
    rt = kk.row(["Provisiot yhteensä (muistio)", None, None, None, v["commissions"]], [None, None, None, None, "in"], bold=True, total=True)
    ref["comm_memo"] = kk.q(f"E{rt}")

    # ================================================================ Osingot
    os_.title("Osingot ja payment in lieu", hdr_sub)
    os_.header(["Päivä", "Kuvaus", "Val.", "Määrä", "EUR", "Tyyppi", "Käsittely"])
    r0 = os_.r
    for x in st.dividends:
        pil = _is_pil(x.description)
        os_.row([x.date, x.description, x.currency, x.amount, x.amount_eur, "PIL" if pil else "Osinko",
                 "Muu rahoitustuotto (SYEP-lainaus) — ei osinko, ei lähdeveroa" if pil else
                 "Osinko listatusta yhtiöstä, omistus < 10 % → 100 % veronalainen (EVL 6 a §)"],
                ["in", "in", "in", "in", "in", "in", "t"])
    r1 = max(os_.r - 1, r0)
    rt = os_.row(["Osinkotuotot (9091)", None, None, None, f'=SUMIF(F{r0}:F{r1},"Osinko",E{r0}:E{r1})'], bold=True)
    ref["div"] = os_.q(f"E{rt}")
    rt = os_.row(["Payment in lieu (9092)", None, None, None, f'=SUMIF(F{r0}:F{r1},"PIL",E{r0}:E{r1})'], bold=True)
    ref["pil"] = os_.q(f"E{rt}")
    os_.blank()
    os_.section("ULKOMAISEN VERON HYVITYS (maittain)", 7)
    os_.header(["Maa", "Tulolaji", "Brutto (EUR)", "Lähdevero (EUR)", "Toteutunut %", "Sopimus-%", "Hyvitys / palautettava"])
    credits = []
    for w in b.wht_rows:
        r = os_.r
        os_.row([w["country"], w["type"], w["gross"], w["wht"], f"=IFERROR(D{r}/C{r},0)", w["treaty"]],
                ["in", "in", "in", "in", "f", "in"], fmt=[None, None, None, None, PCT, PCT])
        os_.ws.cell(r, 6).fill = FILL_KEY
        if w["type"] == "Korko":
            cf = f'=IF({ref["intcredit"]}="Kyllä",MIN(D{r},C{r}*{ref["tax"]}),0)'
        else:
            cf = f"=MIN(D{r},F{r}*C{r},C{r}*{ref['tax']})"
        os_.ws.cell(r, 7, cf).number_format = NUM
        os_.ws.cell(r, 7).font = F_BASE
        os_.ws.cell(r, 8, f"=D{r}-G{r}").number_format = NUM
        os_.ws.cell(r, 8).font = F_BASE
        credits.append(r)
    os_.ws.cell(os_.r - len(credits) - 1, 8, "Palautettava lähdevaltiosta").font = F_HDR
    os_.ws.cell(os_.r - len(credits) - 1, 8).fill = FILL_HDR
    os_.ws.column_dimensions["H"].width = 22
    if credits:
        rt = os_.row(["Hyvitettävä yhteensä", None, None, None, None, None,
                      f"=SUM(G{credits[0]}:G{credits[-1]})"], bold=True, total=True)
        os_.ws.cell(rt, 8, f"=SUM(H{credits[0]}:H{credits[-1]})").number_format = NUM
        ref["credit"] = os_.q(f"G{rt}")
        ref["reclaim"] = os_.q(f"H{rt}")
    else:
        ref["credit"], ref["reclaim"] = "0", "0"
    os_.note("Hyvitys = MIN(lähdevero, sopimusraja × brutto, Suomen vero tulosta). Sopimusrajan ylittävä osa haetaan "
             "takaisin lähdevaltiosta (DK: SKAT-palautushakemus; IE: Revenue / Form 8-3-6).")

    # ================================================================ Vuoden lopun positiot
    vp.title(f"Avoimet positiot ja tase {st.period_end}", [hdr_sub, "Arvostus: alin arvo (KPL 5:6). Valuuttamääräiset saamiset ja velat tilinpäätöspäivän kurssiin (KPL 5:3)."])
    vp.header(["Luokka", "Symboli", "Määrä", "Val.", "Hankintameno (val.)", "Markkina-arvo (val.)",
               "Hankintameno EUR", "Markkina-arvo EUR", "Realisoitumaton EUR", "Huom."])
    for p in st.positions:
        r = vp.r
        vp.row([p.asset_class, p.symbol, p.quantity, p.currency, p.cost_basis, p.value, p.cost_basis_eur, p.value_eur,
                f"=H{r}-G{r}", "Futuuri: nimellisarvo, ei taseeseen (päivittäinen MTM-tilitys käteiseen)"
                if p.asset_class == "Futures" else ""],
               ["in", "in", "in", "in", "in", "in", "in", "in", "f", "t"], fmt=[None, None, "#,##0.####"])
    vp.blank()
    vp.section("NAV-RIVIT IBKR:N MUKAAN (EUR)", 10)
    vp.header(["Rivi", None, None, None, "Alku (total)", "Loppu long", "Loppu short", "Loppu total"])
    for k, n in st.nav.items():
        r = vp.r
        vp.row([k, None, None, None, n.start_total, n.end_long, n.end_short, n.end_total],
               ["in", None, None, None, "in", "in", "in", "in"], bold=(k == "Total"))
        ref[f"nav_{k}"] = r
    vp.blank()
    vp.section("VALUUTTASALDOT (Forex Balances)", 10)
    vp.header(["Valuutta", None, "Määrä", None, "Hankintameno EUR", "Arvo EUR", None, None, "Realisoitumaton EUR"])
    for f_ in st.forex_balances:
        vp.row([f_.currency, None, f_.quantity, None, f_.cost_basis_eur, f_.value_eur, None, None, f_.unrealized_eur],
               ["in", None, "in", None, "in", "in", None, None, "in"])

    def navc(label, col):  # reference into NAV rows on positions sheet; col E start, F long, G short, H total
        r = ref.get(f"nav_{label}")
        return vp.q(f"{col}{r}") if r else "0"
    pos_labels = [k for k in st.nav if k not in ("Cash", "Collateral Value", "Securities Right To Use",
                                                 "Interest Accruals", "Dividend Accruals", "Total", "Futures")]
    ref["sec_long"] = "+".join(navc(k, "F") for k in pos_labels) or "0"
    ref["sec_short"] = "+".join(navc(k, "G") for k in pos_labels) or "0"
    ref["acc_long"] = f"{navc('Interest Accruals', 'F')}+{navc('Dividend Accruals', 'F')}"
    ref["acc_short"] = f"{navc('Interest Accruals', 'G')}+{navc('Dividend Accruals', 'G')}"

    # ================================================================ NAV-täsmäytys (the engine)
    nav.title("NAV-täsmäytys — kirjanpidon tulos ilman tasauseriä",
              [hdr_sub, "1) Taloudellinen tulos = NAV loppu − NAV alku − nettosiirrot.  2) Erittelemättömät erät vähennetään → kaupankäynnin tulos.",
               "3) Kaupankäynnin tulos = realisoidut (R&U) + realisoitumattomien muutos + valuuttakurssiero (johdettu)."])
    nav.header(["Erä", "EUR", "", "", "Lähde / selite"])
    def nrow(label, formula, note="", kind="f", bold=False, total=False, key=None):
        r = nav.row([label, formula, None, None, note], ["t", kind, None, None, "t"], bold=bold, total=total)
        if key:
            ref[key] = nav.q(f"$B${r}")
        return f"B{r}"
    nav.section("1. TALOUDELLINEN TULOS", 5)
    a = nrow("NAV alku", f"={navc('Total', 'E')}", "IBKR Net Asset Value", "link", key="nav_s")
    z = nrow("NAV loppu", f"={navc('Total', 'H')}", "IBKR Net Asset Value", "link", key="nav_e")
    d = nrow("− Nettosiirrot (talletukset − nostot)", f"={ref['dep_net']}", "Talletukset & nostot", "link")
    e = nrow("Taloudellinen tulos (E)", f"={z}-{a}-{d}", "", bold=True, total=True, key="E")
    nav.blank()
    nav.section("2. ERITELLYT EI-KAUPANKÄYNTIERÄT (N)", 5)
    n_first = nav.r
    nrow("Osingot", f"={ref['div']}", "Osingot", "link")
    nrow("Payment in lieu", f"={ref['pil']}", "Osingot", "link")
    nrow("Lähdeverot osingoista", f"={ref['wht_div']}", "Kulut & korot", "link")
    nrow("Lähdeverot koroista", f"={ref['wht_int']}", "Kulut & korot", "link")
    nrow("Korkotuotot", f"={ref['int_inc']}", "Kulut & korot", "link")
    nrow("Korkokulut", f"={ref['int_exp']}", "Kulut & korot", "link")
    nrow("Korkojaksotusten muutos", f"=({navc('Interest Accruals', 'H')})-({navc('Interest Accruals', 'E')})",
         "NAV Interest Accruals loppu − alku (sis. FX-muunnoksen)", "link", key="int_acc")
    nrow("Osinkojaksotusten muutos", f"=({navc('Dividend Accruals', 'H')})-({navc('Dividend Accruals', 'E')})",
         "NAV Dividend Accruals loppu − alku", "link", key="div_acc")
    nrow("Muut kulut", f"={ref['fees']}", "Kulut & korot", "link")
    nrow("Transaktioverot (FTT)", f"={ref['ftt']}", "Kulut & korot", "link")
    n_last = nav.r - 1
    n = nrow("Ei-kaupankäyntierät yhteensä (N)", f"=SUM(B{n_first}:B{n_last})", bold=True, total=True)
    nav.blank()
    nav.section("3. KAUPANKÄYNNIN TULOS JA SEN JAKO", 5)
    t = nrow("Kaupankäynnin tulos (T = E − N)", f"={e}-{n}", "Sisältää provisiot (jo hankintamenoissa)", bold=True, key="T")
    g = nrow("  Luovutusvoitot (R&U)", f"={ref['gains']}", "Realisoitu P_L", "link")
    l_ = nrow("  Luovutustappiot (R&U)", f"={ref['losses']}", "Realisoitu P_L", "link")
    u1 = nrow("  Realisoitumaton loppu", f"={ref['unrl']}", "Realisoitu P_L", "link")
    u0 = nrow("  Realisoitumaton alku", f"={ref['ug_open']}-{ref['wd_open']}", "Asetukset", "link")
    f_ = nrow("  Valuuttakurssiero, netto (F = T − voitot − tappiot − Δ realisoitumaton)",
              f"={t}-{g}-{l_}-({u1}-{u0})", "Marginaalilainan/käteisen kurssiero + pyöristykset", bold=True, key="F")
    nav.blank()
    nav.section("4. KIRJANPIDON TULOS (KPL)", 5)
    br = nrow("Kirjanpidon tulos = E − Δ kirjaamattomat arvonnousut",
              f"={e}-({ref['ug']}-{ref['ug_open']})", "Alin arvo: realisoitumattomia voittoja ei kirjata", bold=True, total=True, key="book")
    nav.blank()
    nav.section("MUISTIO — IBKR:n R&U Forex vs. johdettu kurssiero", 5)
    if "ru_fx_total" in ref:
        m1 = nrow("IBKR R&U Forex realisoitu + realisoitumaton", f"={ref['ru_fx_total']}+{ref['ru_fx_unrl']}", "Realisoitu P_L (muistio)", "link")
        nrow("Päällekkäisyys (EUR-osaketuloksessa jo mukana)", f"={m1}-{f_}",
             "Ei kirjata: IBKR:n Forex-rivin ja johdetun kurssieron erotus on jo EUR-määräisessä osaketuloksessa")
    nrow("Provisiot (muistio, sisältyvät T:hen)", f"={ref['comm_memo']}", "Kulut & korot", "link")
    if b.checks:
        nav.blank()
        nav.section("TARKISTUS IBKR:N CHANGE IN NAV -LUKUIHIN", 5)
        nav.header(["Erä", "Tämä laskelma", "IBKR", "Erotus", "Huom."])
        for name, ours, ibkr, note in b.checks:
            r = nav.r
            nav.row([name, ours, ibkr, f"=B{r}-C{r}", note], ["t", "in", "in", "f", "t"])

    # ================================================================ Tilikartta (closing trial balance of IBKR sub-ledger)
    tk.title(f"Tilikartta — IBKR-alatilin saldot {st.period_end} ja tilikauden tulos",
             [hdr_sub, "Tilinumerot oletuksia — vaihda kirjanpitäjän tilikarttaan. Kirjataan muutokset (loppu − alku); ensimmäisenä vuonna = loppusaldot.",
              "Ei tasauseriä: tulos täsmää NAV-täsmäytykseen ja tase IBKR:n NAV:iin."])
    tk.header(["Tili", "Tilin nimi", "Debet (€)", "Kredit (€)", "Saldo (€)", "Tase/TuloS", "Selite"])
    debit_cells, credit_cells = [], []
    def acct(key, debit=None, credit=None, kind="Tase", note="", name=None):
        no, nm = A[key]
        r = tk.r
        tk.row([no, name or nm, debit, credit, f"=IFERROR(C{r},0)-IFERROR(D{r},0)", kind, note],
               ["t", "t", "f", "f", "f", "t", "t"])
        debit_cells.append(f"C{r}")
        credit_cells.append(f"D{r}")
        return r
    tk.section("VASTAAVAA", 7)
    acct("cash", f"={navc('Cash', 'F')}", note="IBKR käteinen, positiiviset valuuttasaldot")
    acct("collateral", f"={navc('Collateral Value', 'H')}", note="Vastaerä 2849 — netto 0 (SYEP / right to use)")
    acct("securities", f"={ref['sec_long']}", note="Pitkät positiot markkina-arvoon (NAV)")
    acct("unbooked", None, f"={ref['ug']}-{ref['fut_ug']}", note="Kirjaamattomat arvonnousut → kirjanpitoarvo = alin arvo")
    acct("prepaid", f"={ref['acc_long']}", note="Kertyneet korko-/osinkosaamiset")
    _rows = "+".join(vp.q(f"H{ref['nav_' + k]}") for k in st.nav if k != "Total") or "0"
    r_round = tk.r
    tk.row(["—", "IBKR NAV -pyöristys (Total − rivien summa)", f"={navc('Total', 'H')}-({_rows})", None,
            f"=IFERROR(C{r_round},0)", "Tase", "IBKR:n raportin senttipyöristys — ei kirjata, näytetään täsmäytyksen vuoksi"],
           ["t", "t", "f", None, "f", "t", "t"])
    debit_cells.append(f"C{r_round}")
    tk.section("VASTATTAVAA", 7)
    acct("margin_loan", None, f"=-({navc('Cash', 'G')})", note="Negatiiviset valuuttasaldot (USD-laina), kurssi 31.12.")
    acct("short_pos", None, f"=-({ref['sec_short']})", note="Lyhyeksimyynnit markkina-arvoon")
    acct("sru", None, f"=-({navc('Securities Right To Use', 'H')})", note="Vastaerä 1810")
    acct("accrued", None, f"=-({ref['acc_short']})", note="Kertyneet maksamattomat korot")
    acct("fut_deferred", None, f"={ref['fut_ug']}", note="Avoimien futuurien voitot jo käteisenä — jaksotetaan")
    tk.section("OMA PÄÄOMA / SIIRROT", 7)
    r_open = tk.r
    tk.row(["2xxx", "IBKR-alatilin avaava saldo (kirjanpitoarvo)", None, f"={ref['nav_s']}-{ref['ug_open']}",
            f"=-D{r_open}", "Tase", "Edellisen tilinpäätöksen saldo"], ["t", "t", None, "f", "f", "t", "t"])
    credit_cells.append(f"D{r_open}")
    acct("transfer", None, f"={ref['dep_net']}", note="Nettosiirto yhtiön pankkitililtä — vastakirjaus 1900 pääkirjassa")
    tk.section("TUOTOT", 7)
    rev0 = tk.r
    acct("gains", None, f"={ref['gains']}", "TuloS", "R&U S/T+L/T voitot (sis. provisiot)")
    acct("dividends", None, f"={ref['div']}", "TuloS")
    acct("pil", None, f"={ref['pil']}", "TuloS")
    acct("int_income", None, f"={ref['int_inc']}", "TuloS", "Bruttona")
    acct("fx_gain", None, f"=MAX({ref['F']},0)", "TuloS", "Johdettu NAV-täsmäytyksestä")
    tk.section("KULUT", 7)
    acct("losses", f"=-{ref['losses']}", None, "TuloS", "R&U S/T+L/T tappiot (sis. provisiot)")
    acct("writedown", f"=MAX({ref['wd']}-{ref['wd_open']},0)", f"=MAX({ref['wd_open']}-{ref['wd']},0)", "TuloS",
         "Muutos: loppu − alku (palautus kreditiin)")
    acct("fx_loss", f"=MAX(-{ref['F']},0)", None, "TuloS", "Johdettu NAV-täsmäytyksestä")
    acct("int_exp", f"=-{ref['int_exp']}", None, "TuloS", "Bruttona")
    acct("int_accrual", f"=MAX(-{ref['int_acc']},0)", f"=MAX({ref['int_acc']},0)", "TuloS")
    acct("div_accrual", f"=MAX(-{ref['div_acc']},0)", f"=MAX({ref['div_acc']},0)", "TuloS")
    acct("ftt", f"=-{ref['ftt']}", None, "TuloS")
    acct("fees", f"=-{ref['fees']}", None, "TuloS")
    acct("wht_div", f"=-{ref['wht_div']}", None, "TuloS", "Lisätään takaisin verotuksessa; hyvitys erikseen")
    acct("wht_int", f"=-{ref['wht_int']}", None, "TuloS", "Palautettavissa Irlannista (ks. Osingot)")
    rev1 = tk.r - 1
    tk.blank()
    tk.section("TÄSMÄYTYS", 7)
    rd = tk.row(["", "Debet yhteensä", "=" + "+".join(f"IFERROR({c},0)" for c in debit_cells)], bold=True)
    rc = tk.row(["", "Kredit yhteensä", None, "=" + "+".join(f"IFERROR({c},0)" for c in credit_cells)], bold=True)
    rdiff = tk.row(["", "Erotus (pitää olla 0)", None, None, f"=ROUND(C{rd}-D{rc},2)"], bold=True, total=True)
    ref["tk_diff"] = tk.q(f"E{rdiff}")
    rres = tk.row(["", "Tilikauden tulos (tuotot − kulut)", None, None,
                   f'=-SUMIF(F{rev0}:F{rev1},"TuloS",E{rev0}:E{rev1})'], bold=True)
    ref["tk_result"] = tk.q(f"E{rres}")
    rchk = tk.row(["", "Ero NAV-täsmäytyksen kirjanpidon tulokseen", None, None, f"=ROUND(E{rres}-{ref['book']},2)"], bold=True)
    ref["tk_vs_book"] = tk.q(f"E{rchk}")

    # ================================================================ EVL-täsmäytys
    evl.title("EVL-täsmäytys — kirjanpidon tulos → verotettava tulo (IBKR-osuus)",
              [hdr_sub, "Vain IBKR-tilin osuus. Yhtiön muut tuotot/kulut ja vahvistetut tappiot lisätään pääkirjanpidossa."])
    evl.header(["Erä", "EUR", "Peruste"])
    def erow(label, formula, note="", kind="f", bold=False, total=False, key=None):
        r = evl.row([label, formula, note], ["t", kind, "t"], bold=bold, total=total)
        if key:
            ref[key] = evl.q(f"$B${r}")
        return f"B{r}"
    bk = erow("Kirjanpidon tulos (KPL)", f"={ref['book']}", "NAV-täsmäytys", "link", bold=True)
    evl.section("LISÄYKSET / VÄHENNYKSET (veroilmoitus 6B)", 3)
    a0 = evl.r
    erow("+ Ulkomaiset lähdeverot kuluna", f"=-({ref['wht_div']}+{ref['wht_int']})",
         "Vero ei ole vähennyskelpoinen kulu; hyvitys erikseen (laki kansainvälisen kaksinkertaisen verotuksen poistamisesta)")
    erow("+ Arvonalentumiset: futuurit / ETF:t (muu omaisuus)", f"={ref['other_wd']}",
         "Futuurit ja ETF:t ovat muuta omaisuutta (EVL 12 a §) — hankintameno vähennetään luovutettaessa")
    erow("+ Arvonalentumiset: osakkeet",
         f'=IF({ref["cat"]}="muu omaisuus",{ref["share_wd"]}-({ref["wd_open"]}-{ref["wopt_loss_cf"]}),0)',
         "Vain jos osakkeet = muu omaisuus. Rahoitusomaisuutena käsittely kirjanpitäjän kanssa. Avaavista "
         "arvonalentumisista vähennetään asetettujen optioiden osuus (OPT-Y8, oma rivi).")
    erow("+ OPT-Y8: avoimien asetettujen optioiden tilinpäätöstappio", f"={ref['wopt_add']}",
         "Ehdotus, vahvista kirjanpitäjältä: ei vähennyskelpoinen ennen sulkemista, toteutusta tai raukeamista "
         "(EVL 27 d § 2 ja 4 mom.; HE 84/2002). Käsittely optioittain: Realisoitu P_L, sarake Huom.", "link")
    erow("− OPT-Y8: edellisellä tilikaudella lisätyt asetettujen optioiden tappiot", f"=-{ref['wopt_loss_cf']}", "Asetukset")
    erow("+ EVL 8 a §: vähennyskelvoton osaketappio", f'=IF({ref["cat"]}="muu omaisuus",MAX(0,-{ref["share_losses"]}-{ref["gains"]}),0)',
         "Osakkeiden luovutustappiot vähennetään vain muun omaisuuden luovutusvoitoista (vuosi + 5 v)")
    erow("+ Asetettujen optioiden preemiot, OTC / yli 18 kk, avoinna (OPT-Y2)", round(b.v.get("evl_add_wopt", 0.0), 2),
         "EVL 27 d § 1 mom.: preemio on asetusvuoden tuloa; kirjanpito tulouttaa sen vasta sulkemisessa", "in")
    erow("− Aiemmin verotetut asetettujen optioiden preemiot (OPT-Y2)", f"=-{ref['wopt_cf']}", "Asetukset")
    erow("− Aiempien vuosien osaketappioiden käyttö", f'=IF({ref["cat"]}="muu omaisuus",-MIN({ref["cf"]},MAX(0,{ref["gains"]}+{ref["share_losses"]})),0)',
         "Asetukset")
    a1 = evl.r - 1
    adj = erow("Oikaisut yhteensä", f"=SUM(B{a0}:B{a1})", bold=True, total=True)
    evl.blank()
    tx = erow("VEROTETTAVA TULO (IBKR-osuus)", f"={bk}+{adj}", "", bold=True, total=True, key="taxable")
    evl.ws.cell(int(tx[1:]), 2).fill = FILL_KEY
    evl.blank()
    evl.section("VERO", 3)
    tg = erow("Yhteisövero", f"=MAX({tx},0)*{ref['tax']}", "Asetukset: verokanta", key="tax_gross")
    tc = erow("− Ulkomaisen veron hyvitys", f"=-MIN({ref['credit']},{tg})", "Osingot: hyvitystaulukko", "link", key="tax_credit")
    erow("Maksettava yhteisövero (IBKR-osuus)", f"={tg}+{tc}", "", bold=True, total=True, key="tax_net")
    erow("Lähdevaltioista palautettavissa (ei hyvitetä)", f"={ref['reclaim']}", "DK: SKAT · IE: Revenue", "link")
    evl.blank()
    evl.section("HUOMIOT", 3)
    for t_ in [
        "Osingot: saaja listaamaton Oy, omistus < 10 % listatusta yhtiöstä → osinko 100 % veronalainen (EVL 6 a §). Ei oikaisua.",
        "Payment in lieu (SYEP): muu rahoitustuotto, veronalainen, ei osinko eikä lähdeveron hyvitykseen oikeuttava.",
        "Provisiot sisältyvät IBKR:n hankintamenoihin ja luovutushintoihin — EI vähennetä erikseen (muuten provisiot vähennettäisiin kahdesti).",
        "Valuuttakurssierot marginaalilainasta ja käteisestä: veronalaisia / vähennyskelpoisia (EVL 5 §, 8 § 1 mom.).",
        "Korkovähennysrajoitus (EVL 18 a §) koskee vasta yli 500 000 € nettokorkokuluja.",
        "Omaisuuslaji (Asetukset): ratkaisee arvonalentumisten ja osaketappioiden käsittelyn — vahvista kirjanpitäjältä.",
    ]:
        evl.note(t_)

    # ================================================================ Yhteenveto
    ys.title(f"{company} — IBKR tilinpäätösyhteenveto", [hdr_sub, "Kaikki luvut linkkejä laskentavälilehdiltä."])
    ys.header(["Erä", "EUR", "", "Huom."])
    def yrow(label, formula, note="", bold=False, total=False):
        return ys.row([label, formula, None, note], ["t", "link", None, "t"], bold=bold, total=total)
    ys.section("PÄÄOMA JA SIIRROT", 4)
    yrow("Talletukset", f"={ref['dep_in']}")
    yrow("Nostot", f"={ref['dep_out']}", "Siirrot yhtiön pankkitilille — sisäinen siirto, ei tulosvaikutusta")
    yrow("NAV kauden lopussa", f"={ref['nav_e']}")
    ys.section("TULOS (KPL)", 4)
    yrow("Luovutusvoitot", f"={ref['gains']}")
    yrow("Luovutustappiot", f"={ref['losses']}")
    yrow("Arvonalentumiset (muutos)", f"=-({ref['wd']}-{ref['wd_open']})")
    yrow("Valuuttakurssiero, netto", f"={ref['F']}", "Johdettu — ei IBKR:n R&U Forex -riviä")
    yrow("Osingot + payment in lieu", f"={ref['div']}+{ref['pil']}")
    yrow("Korot netto (sis. jaksotus)", f"={ref['int_inc']}+{ref['int_exp']}+{ref['int_acc']}")
    yrow("Kulut, FTT ja lähdeverot", f"={ref['fees']}+{ref['ftt']}+{ref['wht_div']}+{ref['wht_int']}+{ref['div_acc']}")
    yrow("Kirjanpidon tulos", f"={ref['book']}", "Täsmää Tilikartta-tulokseen", bold=True, total=True)
    ys.section("VEROTUS (EVL)", 4)
    yrow("Verotettava tulo (IBKR-osuus)", f"={ref['taxable']}", bold=True)
    yrow("Yhteisövero", f"={ref['tax_gross']}")
    yrow("Ulkomaisen veron hyvitys", f"={ref['tax_credit']}")
    yrow("Maksettava vero (IBKR-osuus)", f"={ref['tax_net']}", bold=True, total=True)
    yrow("Palautettavat lähdeverot (DK/IE)", f"={ref['reclaim']}", "Hae lähdevaltiosta")
    ys.section("TARKISTUKSET (kaikkien pitää olla 0)", 4)
    yrow("Tilikartta: debet − kredit", f"={ref['tk_diff']}")
    yrow("Tilikartta-tulos − NAV-täsmäytyksen tulos", f"={ref['tk_vs_book']}")
    if b.checks:
        yrow("IBKR Change in NAV -tarkistuksia", len(b.checks), "Ks. NAV-täsmäytys")
    if b.warnings:
        ys.blank()
        ys.section("VAROITUKSET", 4)
        for w in b.warnings:
            ys.note("⚠ " + w)

    # ================================================================ Verotus-muistio
    muis.title("Muistio kirjanpitäjälle", hdr_sub)
    muis.header(["Aihe", "Selitys"])
    notes = [
        ("1. Menetelmä", "Tulos johdetaan IBKR:n NAV-muutoksesta (talletukset eliminoitu). Kaupankäynnin tulos jaetaan "
         "R&U-raportin realisoituihin voittoihin/tappioihin (kauppapäivien EUR-kurssit) ja johdettuun valuuttakurssieroon. "
         "IBKR:n R&U Forex -riviä ei kirjata: EUR-perusvaluuttatilillä sen vaikutus sisältyy jo osaketulokseen."),
        ("2. Alin arvo", "Avoimet positiot: realisoitumaton tappio kirjataan arvonalentumisena (KPL 5:6), voittoa ei kirjata. "
         "Futuurien päivittäinen MTM on jo käteisessä; realisoitumaton futuurivoitto jaksotetaan siirtovelkaan."),
        ("3. Valuutta", "USD-marginaalilaina ja käteinen arvostetaan tilinpäätöspäivän kurssiin (KPL 5:3) — sisältyy NAV:iin."),
        ("4. Osingot", f"Osingot {v['div_ord']:,.2f} € + payment in lieu {v['div_pil']:,.2f} € (SYEP, ei osinko)."),
        ("5. Lähdeverot", "Osinkojen lähdevero hyvitetään vain sopimusrajaan asti; ylittävä osa haetaan lähdevaltiosta. "
         "Irlannin korkolähdevero palautetaan Irlannista (FI–IE-sopimus) — ei hyvitystä Suomessa."),
        ("6. Omaisuuslaji", f"Osakkeet merkitty: '{s.share_category}'. Vaikuttaa arvonalentumisten vähennyskelpoisuuteen ja "
         "EVL 8 a §:n tappiorajoitukseen. Futuurit/ETF:t = muu omaisuus (Verohallinnon ohje)."),
        ("7. Siirrot", "Talletukset ja nostot ovat siirtoja yhtiön oman pankkitilin ja IBKR-tilin välillä (tili 1900, vastakirjaus pankkitilille pääkirjassa). Ei tulos- eikä verovaikutusta. IBKR:n teksti 'Disbursement Initiated by …' tarkoittaa vain nostopyynnön tekijää."),
        ("8. Dokumentaatio", "Säilytä: IBKR Activity Statement (PDF+CSV), Realized Summary, lähdeverotodistukset, tämä työkirja. "
         f"Laskettu versiolla IBKR-yhteenveto {__version__} ({date.today().isoformat()}); muutokset: CHANGELOG.md."),
    ]
    if any(r.asset_class in CFD_CLASSES for r in b.st.ru):
        notes.append(("9. CFD:t", "CFD-kauppojen voitot ja tappiot on käsitelty kuten muut johdannaiset (veronalaisia / "
                      "vähennyskelpoisia). Verohallinnon EVL-johdannaisohje (2014) ei käsittele CFD:itä — vahvista "
                      "käsittely kirjanpitäjän kanssa. Henkilöverotuksessa CFD-tappiot eivät ole vähennyskelpoisia."))
    if b.wopt_y8:
        notes.append((f"{len(notes) + 1}. Avoimet asetetut optiot (OPT-Y8)",
                      "Tilikauden lopussa avoinna olevan asetetun option kirjanpidon tappio (KPL 5:6 / varaus) lisätään "
                      "takaisin verotuksessa ja vähennetään seuraavana vuonna, kun optio suljetaan, toteutetaan tai "
                      "raukeaa. Sääntö on EHDOTUS (päätösrekisteri OPT-Y8) — vahvista kirjanpitäjältä. Lähteet: "
                      "EVL 27 d § 2 ja 4 mom., 27 e §; HE 84/2002; Verohallinnon ohje 48083 (13.6.2014) kohta 4.3. "
                      "Valinnat: " + "; ".join(f"{w['symbol']}: {Y8_LABELS[w['applied']]}"
                                             + ("" if w["choice"] else " (ei valittu — oletus)") for w in b.wopt_y8)
                      + f". Siirrä seuraavan vuoden asetukseen 'lisätyt asetettujen optioiden tappiot': "
                      f"{v['evl_add_wd_wopt']:,.2f} €."))
    for k, t_ in notes:
        r = muis.row([k, t_], ["t", "t"])
        muis.ws.cell(r, 2).alignment = Alignment(wrap_text=True, vertical="top")
        muis.ws.cell(r, 1).alignment = Alignment(vertical="top")

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = None
    return workbook_bytes(wb)   # in memory: no temp files on disk
