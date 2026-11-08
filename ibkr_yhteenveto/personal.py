"""Personal (henkilöasiakas) taxation: IBKR statement -> OmaVero figures.

Securities (stocks/ETFs): FIFO over exact EUR trade legs — sale price at the sale-date rate, cost at the
purchase-date rate (Vero method), one gain/loss per acquisition lot.
Derivatives (futures, options): gross gains/losses from IBKR's R&U summary.
CFDs: not disposals. Each profitable closing trade is other capital income; losses are not deductible and are ignored
(Vero: CFD-hinnanerosopimukset). CFD financing costs found in interest/fees are likewise not deducted.
Capital income tax: 30 % up to 30 000 €, 34 % above. Listed-company dividends 85 % taxable.
Small disposals: if total sale prices <= 1 000 € the gains are tax-free (and losses only deductible if
acquisition costs > 1 000 €).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from .books import _is_div_wht, _is_pil, _div_country, wht_country
from .model import Statement
from .parse_common import CFD_CLASSES


def _fi(x: float, d: int = 2) -> str:
    """Finnish number format: 1 234,56"""
    x = 0.0 if abs(x) < 0.5 * 10 ** -d else x
    return f"{x:,.{d}f}".replace(",", "\u00a0").replace(".", ",")

DERIVATIVE_CLASSES = {"Futures", "Equity and Index Options", "Options", "Warrants", "Futures Options",
                      "Options On Futures", "Structured Products"}


def _is_cfd_cost(desc: str) -> bool:
    return "cfd" in (desc or "").lower()


@dataclass
class PSettings:
    name: str = ""
    loss_carryforward: float = 0.0     # confirmed capital losses from previous years (vahvistetut luovutustappiot)
    include_fx: bool = False           # IBKR R&U 'Forex' row as currency disposals (off: overlaps stock EUR P/L)
    rate_low: float = 0.30
    rate_high: float = 0.34
    bracket: float = 30_000.0
    small_limit: float = 1_000.0
    div_taxable_share: float = 0.85    # listed company dividends
    pil_taxable_share: float = 1.0     # payment in lieu (SYEP) — ordinary capital income
    credit_interest_wht: bool = False
    treaty_rates: dict = field(default_factory=lambda: {"DK": 0.15, "US": 0.15, "SE": 0.15, "NO": 0.15, "DE": 0.15,
                                                        "NL": 0.15, "CH": 0.10, "GB": 0.0, "AU": 0.15, "CA": 0.15,
                                                        "FR": 0.0})


@dataclass
class Match:
    symbol: str
    sale_date: str
    buy_date: str
    qty: float
    proceeds: float      # luovutushinta EUR (net of selling commission)
    cost: float          # hankintameno EUR (incl. buying commission)
    short: bool = False
    source: str = "FIFO"  # 'FIFO' or 'Avaava erä (IBKR)'

    @property
    def result(self) -> float:
        return self.proceeds - self.cost


@dataclass
class PBooks:
    st: Statement
    s: PSettings
    matches: list[Match] = field(default_factory=list)
    derivatives: list = field(default_factory=list)
    cfd_rows: list = field(default_factory=list)   # {"date","symbol","cls","eur","source"}
    v: dict[str, float] = field(default_factory=dict)
    wht_rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ru_by_symbol: dict[str, float] = field(default_factory=dict)


def fifo(st: Statement, warnings: list[str]) -> list[Match]:
    end_qty = defaultdict(float)
    for p in st.positions:
        if p.asset_class == "Stocks":
            end_qty[p.symbol] += p.quantity
    legs_by_sym = defaultdict(list)
    for i, x in enumerate(st.stock_legs):
        legs_by_sym[x["symbol"]].append((x["date"], i, x))
    out: list[Match] = []
    for sym, legs in legs_by_sym.items():
        legs.sort(key=lambda t: (t[0], t[1]))
        opening = end_qty.get(sym, 0.0) - sum(x["qty"] for _, _, x in legs)
        lots: deque = deque()  # [qty_signed, eur_per_share or None, date]
        if abs(opening) > 1e-9:
            lots.append([opening, None, "avaava"])
        for date, _, x in legs:
            q, px = x["qty"], x["eur"] / abs(x["qty"]) if x["qty"] else 0.0
            while abs(q) > 1e-9 and lots and (lots[0][0] > 0) != (q > 0):
                lot = lots[0]
                n = min(abs(q), abs(lot[0]))
                if q < 0:   # selling against long lot
                    m = Match(sym, date, lot[2], n, px * n, (lot[1] or 0.0) * n)
                else:       # buying back a short lot
                    m = Match(sym, date, lot[2], n, (lot[1] or 0.0) * n, px * n, short=True)
                if lot[1] is None:
                    m.source = "Avaava erä (IBKR)"
                out.append(m)
                lot[0] += n if lot[0] < 0 else -n
                q += n if q < 0 else -n
                if abs(lot[0]) < 1e-9:
                    lots.popleft()
            if abs(q) > 1e-9:
                lots.append([q, px, date])
    return out


def _fill_opening(matches: list[Match], ru: dict[str, float], warnings: list[str]):
    """Opening lots (bought in an earlier year) have no EUR cost in this statement: back out their cost so the
    symbol's total equals IBKR's realized P/L for those shares."""
    by_sym = defaultdict(list)
    for m in matches:
        by_sym[m.symbol].append(m)
    for sym, ms in by_sym.items():
        op = [m for m in ms if m.source != "FIFO"]
        if not op:
            continue
        known = sum(m.result for m in ms if m.source == "FIFO")
        target = ru.get(sym, 0.0) - known
        tot_qty = sum(m.qty for m in op)
        for m in op:
            share = m.qty / tot_qty if tot_qty else 0
            if m.short:
                m.proceeds = m.cost + target * share
            else:
                m.cost = m.proceeds - target * share
        warnings.append(f"{sym}: {_fi(tot_qty, 0)} kpl myytiin edellisvuoden eristä — hankintameno johdettu IBKR:n "
                        "realisoidusta tuloksesta. Tarkista edellisen vuoden ostokursseista.")


def build_personal(st: Statement, s: PSettings) -> PBooks:
    b = PBooks(st, s)
    v = b.v
    b.warnings += st.warnings
    if not st.stock_legs and any(r.asset_class == "Stocks" for r in st.ru):
        b.warnings.append("Osakekauppojen EUR-rivejä ei löytynyt — luovutushinnat puuttuvat. Käytä PDF:ää, jossa on "
                          "'Forex P/L Details' (Realized Summary / Activity Statement).")
    if any(not x.get("exact", True) for x in st.stock_legs):
        b.warnings.append("Osa valuuttamääräisistä kaupoista muunnettu keskikurssilla (CSV). Tarkat EUR-arvot: "
                          "käytä PDF-raporttia (Forex P/L Details).")

    b.ru_by_symbol = {r.symbol: r.realized for r in st.ru if r.asset_class == "Stocks"}
    b.matches = fifo(st, b.warnings)
    _fill_opening(b.matches, b.ru_by_symbol, b.warnings)
    M = b.matches
    v["sec_proceeds"] = sum(m.proceeds for m in M)
    v["sec_cost"] = sum(m.cost for m in M)
    v["sec_gains"] = sum(m.result for m in M if m.result > 0)
    v["sec_losses"] = sum(m.result for m in M if m.result < 0)
    v["sec_net"] = v["sec_gains"] + v["sec_losses"]
    v["ru_sec_net"] = sum(b.ru_by_symbol.values())

    b.derivatives = [r for r in st.ru if r.asset_class in DERIVATIVE_CLASSES]
    v["der_gains"] = sum(r.profit for r in b.derivatives)
    v["der_losses"] = sum(r.loss for r in b.derivatives)
    fx = [r for r in st.ru if r.asset_class == "Forex"]
    v["fx_gains"] = sum(r.profit for r in fx) if s.include_fx else 0.0
    v["fx_losses"] = sum(r.loss for r in fx) if s.include_fx else 0.0
    v["fx_memo"] = sum(r.realized for r in fx)
    _cfd(b)
    other = [r for r in st.ru if r.asset_class not in DERIVATIVE_CLASSES | CFD_CLASSES | {"Stocks", "Forex"}]
    if other:
        b.warnings.append("Tuntemattomat omaisuusluokat (ei mukana): " + ", ".join(sorted({r.asset_class for r in other})))

    # small disposals (securities)
    v["small_exempt"] = 1.0 if 0 < v["sec_proceeds"] <= s.small_limit else 0.0
    sec_g, sec_l = v["sec_gains"], v["sec_losses"]
    if v["small_exempt"]:
        sec_g = 0.0
        if v["sec_cost"] <= s.small_limit:
            sec_l = 0.0
    v["disp_gains"] = sec_g + v["der_gains"] + v["fx_gains"]
    v["disp_losses"] = sec_l + v["der_losses"] + v["fx_losses"]
    v["disp_net"] = v["disp_gains"] + v["disp_losses"]

    # dividends / interest / fees
    v["div_ord"] = sum(x.amount_eur for x in st.dividends if not _is_pil(x.description))
    v["div_pil"] = sum(x.amount_eur for x in st.dividends if _is_pil(x.description))
    v["div_taxable"] = v["div_ord"] * s.div_taxable_share
    v["pil_taxable"] = v["div_pil"] * s.pil_taxable_share
    v["int_income"] = sum(x.amount_eur for x in st.interest if x.amount_eur > 0)
    v["int_expense"] = -sum(x.amount_eur for x in st.interest if x.amount_eur < 0 and not _is_cfd_cost(x.description))
    cfd_int = -sum(x.amount_eur for x in st.interest if x.amount_eur < 0 and _is_cfd_cost(x.description))
    cfd_fee = -sum(x.amount_eur for x in st.fees if _is_cfd_cost(x.description))
    v["fees"] = -(st.fees_total_eur or 0.0) - cfd_fee
    v["cfd_costs_ignored"] = cfd_int + cfd_fee
    v["wht_div"] = -sum(x.amount_eur for x in st.withholding if _is_div_wht(x.description))
    v["wht_int"] = -sum(x.amount_eur for x in st.withholding if not _is_div_wht(x.description))

    # capital income
    v["other_ci"] = v["div_taxable"] + v["pil_taxable"] + v["int_income"] + v["cfd_gains"]
    v["deductions"] = v["int_expense"] + v["fees"]
    before_cf = v["disp_net"] + v["other_ci"] - v["deductions"]
    v["cf_used"] = min(s.loss_carryforward, max(0.0, v["disp_net"] + v["other_ci"]))
    v["capital_income"] = before_cf - v["cf_used"]
    v["new_loss"] = max(0.0, -(v["disp_net"] + v["other_ci"])) if v["disp_net"] < 0 else 0.0
    po = max(v["capital_income"], 0.0)
    v["tax_gross"] = s.rate_low * min(po, s.bracket) + s.rate_high * max(po - s.bracket, 0.0)

    credit = 0.0
    gross_by_c, wht_by_c = defaultdict(float), defaultdict(float)
    for d in st.dividends:
        if not _is_pil(d.description):
            c_ = wht_country(d.description + " - " + _div_country(st, d.description), d.currency)
            gross_by_c[c_] += d.amount_eur
    for x in st.withholding:
        if _is_div_wht(x.description):
            wht_by_c[wht_country(x.description, x.currency)] -= x.amount_eur
    eff_rate = (v["tax_gross"] / po) if po else s.rate_low
    for c_, w in wht_by_c.items():
        gross = gross_by_c.get(c_, v["div_ord"])
        treaty = s.treaty_rates.get(c_, 0.15)
        cr = min(w, treaty * gross, eff_rate * gross * s.div_taxable_share)
        credit += cr
        b.wht_rows.append({"country": c_, "type": "Osinko", "gross": gross, "wht": w, "rate": w / gross if gross else 0,
                           "treaty": treaty, "credit": cr, "reclaim": max(0.0, w - treaty * gross)})
    if v["wht_int"]:
        cr = min(v["wht_int"], eff_rate * v["int_income"]) if s.credit_interest_wht else 0.0
        credit += cr
        b.wht_rows.append({"country": "IE", "type": "Korko", "gross": v["int_income"], "wht": v["wht_int"],
                           "rate": v["wht_int"] / v["int_income"] if v["int_income"] else 0, "treaty": 0.0,
                           "credit": cr, "reclaim": v["wht_int"] - cr})
    v["tax_credit"] = min(credit, v["tax_gross"])
    v["tax_net"] = v["tax_gross"] - v["tax_credit"]
    v["reclaim"] = sum(r["reclaim"] for r in b.wht_rows)

    if abs(v["sec_net"] - v["ru_sec_net"]) > 0.02 * max(1.0, abs(v["ru_sec_net"])) + 50:
        b.warnings.append(f"Osakkeiden FIFO-tulos {_fi(v['sec_net'], 0)} € poikkeaa IBKR:n R&U-tuloksesta "
                          f"{_fi(v['ru_sec_net'], 0)} € — ero johtuu valuuttakurssimenetelmästä (Vero: osto- ja "
                          "myyntipäivän kurssit). Tarkista, jos ero on suuri.")
    b.warnings.append("Varmista, että IBKR:n lot matching -asetus on FIFO (Verohallinto edellyttää FIFO-järjestystä).")
    return b


def _cfd(b: PBooks) -> None:
    """CFD gains per closing trade (CSV Trades), else per IBKR R&U lot split (PDF only). Losses are ignored."""
    st, v = b.st, b.v
    ru = [r for r in st.ru if r.asset_class in CFD_CLASSES]
    trades = st.cfd_trades
    if trades and all(x.get("eur") is not None for x in trades):
        b.cfd_rows = [{"date": x["date"], "symbol": x["symbol"], "cls": x["cls"], "eur": x["eur"],
                       "source": "Kauppa (IBKR Trades)"} for x in trades]
    elif ru:
        for r in ru:
            for amt in (r.profit, r.loss):
                if amt:
                    b.cfd_rows.append({"date": "", "symbol": r.symbol, "cls": r.asset_class, "eur": amt,
                                       "source": "IBKR R&U (ei kauppaerittelyä)"})
        b.warnings.append("CFD:t: kauppakohtaisia tuloksia ei löytynyt — voitot ja tappiot IBKR:n R&U-yhteenvedosta. "
                          "Lisää Activity Statement CSV, niin CFD-voitot lasketaan kauppakohtaisesti.")
    v["cfd_gains"] = sum(x["eur"] for x in b.cfd_rows if x["eur"] > 0)
    v["cfd_losses_ignored"] = sum(x["eur"] for x in b.cfd_rows if x["eur"] < 0)
    v["ru_cfd_net"] = sum(r.realized for r in ru)
    net = v["cfd_gains"] + v["cfd_losses_ignored"]
    if ru and abs(net - v["ru_cfd_net"]) > 0.02 * max(1.0, abs(v["ru_cfd_net"])) + 50:
        b.warnings.append(f"CFD-kauppojen tulos {_fi(net, 0)} € poikkeaa IBKR:n R&U-tuloksesta "
                          f"{_fi(v['ru_cfd_net'], 0)} € — tarkista CFD-kaupat.")
    if b.cfd_rows:
        b.warnings.append("CFD:t: voitot ovat muuta pääomatuloa (ei luovutusvoittoa); tappioita ei voi vähentää "
                          "(Verohallinto). IBKR:n CFD-provisioita ei ole vähennetty voitoista.")


def omavero_fields(b: PBooks) -> list[tuple[str, str, float, str]]:
    v = b.v
    rows = [
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Osakkeet ja rahastot — luovutushinnat yhteensä", v["sec_proceeds"], "Myyntihinnat, myyntikulut vähennetty"),
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Osakkeet ja rahastot — hankintamenot ja kulut yhteensä", v["sec_cost"], "FIFO, ostopäivän kurssi"),
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Osakkeet ja rahastot — luovutusvoitot yhteensä", v["sec_gains"], "Hankintaerittäin"),
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Osakkeet ja rahastot — luovutustappiot yhteensä", -v["sec_losses"], ""),
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Johdannaiset (futuurit, optiot) — voitot", v["der_gains"], "IBKR R&U"),
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Johdannaiset (futuurit, optiot) — tappiot", -v["der_losses"], "IBKR R&U"),
    ]
    if b.s.include_fx:
        rows += [("Arvopapereiden luovutukset (OmaVero / 9A)", "Valuutat — voitot", v["fx_gains"], "IBKR R&U Forex"),
                 ("Arvopapereiden luovutukset (OmaVero / 9A)", "Valuutat — tappiot", -v["fx_losses"], "")]
    for r in b.wht_rows:
        if r["type"] == "Osinko":
            rows += [("Ulkomaan pääomatulot (OmaVero / 16B)", f"Osingot, {r['country']} — brutto (listattu yhtiö)", r["gross"], "85 % veronalaista"),
                     ("Ulkomaan pääomatulot (OmaVero / 16B)", f"Osingot, {r['country']} — ulkomainen vero (hyvitettävä osa)", r["credit"],
                      f"Pidätetty {_fi(r['wht'])} €; ylitys {_fi(r['reclaim'])} € haetaan lähdevaltiosta")]
    if not b.wht_rows and v["div_ord"]:
        rows.append(("Ulkomaan pääomatulot (OmaVero / 16B)", "Osingot — brutto", v["div_ord"], "85 % veronalaista"))
    if v["div_pil"]:
        rows.append(("Ulkomaan pääomatulot (OmaVero / 16B)", "Muut pääomatulot — payment in lieu of dividend", v["div_pil"], "Osakelainauksen korvaus, 100 %"))
    if b.cfd_rows:
        rows.append(("Ulkomaan pääomatulot (OmaVero / 16B)", "Muut pääomatulot — CFD-voitot", v["cfd_gains"],
                     "Voitolliset CFD-kaupat yhteensä; tappioita ei vähennetä"))
    if v["int_income"]:
        rows.append(("Ulkomaan pääomatulot (OmaVero / 16B)", "Korkotulot — brutto", v["int_income"],
                     f"Lähdevero {_fi(v['wht_int'])} € — palautus lähdevaltiosta" if v["wht_int"] else ""))
    rows += [
        ("Vähennykset", "Korot tulonhankkimisvelasta (marginaalilaina)", v["int_expense"], "Arvopaperien hankintaan otettu velka"),
        ("Vähennykset", "Muut tulonhankkimismenot (IBKR-kulut)", v["fees"], ""),
    ]
    if v["cf_used"]:
        rows.append(("Vähennykset", "Aiempien vuosien vahvistetut luovutustappiot", v["cf_used"], ""))
    if b.cfd_rows or v["cfd_costs_ignored"]:
        rows.append(("Ei ilmoiteta (tieto)", "Vähennyskelvottomat CFD-tappiot (ei huomioida)", -v["cfd_losses_ignored"],
                     "Verohallinto: CFD-tappiota ei huomioida verotuksessa"))
    if v["cfd_costs_ignored"]:
        rows.append(("Ei ilmoiteta (tieto)", "CFD-rahoituskulut (ei vähennetty)", v["cfd_costs_ignored"],
                     "Tulkinta: liittyvät CFD:ihin, joiden tappiot eivät ole vähennyskelpoisia"))
    return rows
