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

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date

from .books import _is_div_wht, _is_pil, _div_country, wht_country
from .model import Statement
from .parse_common import CFD_CLASSES, CRYPTO_CLASSES, OPTION_CLASSES, codes


def _fi(x: float, d: int = 2) -> str:
    """Finnish number format: 1 234,56"""
    x = 0.0 if abs(x) < 0.5 * 10 ** -d else x
    return f"{x:,.{d}f}".replace(",", "\u00a0").replace(".", ",")

# Regulated markets (or equivalent) for futures and standardised options: losses are deductible only there
# (Vero 48914; KVL 1/2021: US exchanges supervised by a federal authority are equivalent). EEA + US by default.
REGULATED_EXCHANGES = {
    # United States (CFTC / SEC supervised)
    "CME", "CBOT", "NYMEX", "COMEX", "CFE", "CBOE", "CBOE2", "C2", "ICEUS", "NYBOT", "ISE", "PHLX", "AMEX", "ARCA",
    "BOX", "MIAX", "EMERALD", "PEARL", "GEMINI", "MERCURY", "EDGX", "BATS", "NASDAQOM", "NASDAQBX", "PSE", "NYSE",
    "NASDAQ",
    # EEA
    "EUREX", "DTB", "IDEM", "MEFFRV", "MEFF", "MONEP", "MATIF", "OMS", "OMH", "OMC", "OSE.NOR", "FTA", "EOE",
    "ENEXT.BE", "BELFOX", "WSE", "ATHEX",
}
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
    fx_mode: str = "ibkr"              # "ibkr": IBKR's per-trade EUR; "ecb": ECB rate of the settlement date
    extra_regulated: str = ""          # user's additional regulated/equivalent exchanges, comma-separated
    use_presumption: bool = True       # hankintameno-olettama per lot when it gives the lower gain (Vero 48262 §4.2.2)
    # year-start positions: {symbol: {"method": "lots"|"manual"|"olettama"|"ibkr",
    #   "lots": [{"date": "YYYY-MM-DD", "qty": n, "cost_eur": x} or {"date", "qty", "olettama": true}]}}
    opening_choices: dict = field(default_factory=dict)
    treaty_rates: dict = field(default_factory=lambda: {"DK": 0.15, "US": 0.15, "SE": 0.15, "NO": 0.15, "DE": 0.15,
                                                        "NL": 0.15, "CH": 0.10, "GB": 0.0, "AU": 0.15, "CA": 0.15,
                                                        "FR": 0.0})


# How the acquisition cost (or, for a short, the original sale price) of a matched lot was determined
SOURCES = {
    "fifo": "FIFO",
    "history": "Edellisvuoden raportti",
    "manual": "Käyttäjän syöttämä",
    "olettama": "Hankintameno-olettama",
    "ibkr": "IBKR-päättely (valittu)",
    "unresolved": "RATKAISEMATON — IBKR-päättely",
}


@dataclass
class Match:
    symbol: str
    sale_date: str
    buy_date: str
    qty: float
    proceeds: float      # luovutushinta EUR: GROSS sale price (before selling commission and put-premium deduction)
    cost: float          # actual hankintameno + kulut EUR: purchase incl. commission, selling commission, put premium
    short: bool = False
    method: str = "fifo"  # key of SOURCES
    premium: float = 0.0  # option premium EUR included in cost (exercised call or put)
    presumption_rate: float = 0.0          # 0.2 / 0.4 when hankintameno-olettama may be used, else 0
    deduction: float | None = None         # what is deducted: cost, or the olettama when it gives the lower gain
    note: str = ""                          # e.g. fractional shares paid in cash in a corporate action

    @property
    def presumption(self) -> float:
        return self.presumption_rate * self.proceeds

    @property
    def presumption_used(self) -> bool:
        return self.deduction is not None and self.presumption_rate > 0 and abs(self.deduction - self.presumption) < 1e-9 \
            and (self.method == "olettama" or self.presumption > self.cost)

    @property
    def source(self) -> str:
        r = f"{round(self.presumption_rate * 100)} %"
        if self.method == "olettama":
            return f"Hankintameno-olettama {r}"
        base = SOURCES.get(self.method, self.method) + (f" · {self.note}" if self.note else "")
        return f"{base} · olettama {r}" if self.presumption_used else base

    @property
    def result(self) -> float:
        return self.proceeds - (self.deduction if self.deduction is not None else self.cost)


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
    opening: list[dict] = field(default_factory=list)    # year-start lots consumed this year + how they were handled
    crypto_matches: list[Match] = field(default_factory=list)  # virtuaalivaluuttojen luovutukset (FIFO per coin)
    option_events: list[dict] = field(default_factory=list)  # exercises / assignments and how the premium was used
    ca_events: list[dict] = field(default_factory=list)      # corporate actions applied to share lots
    blocked: list[str] = field(default_factory=list)         # symbols whose FIFO stopped at an unknown corporate action
    der_exch: dict[str, str] = field(default_factory=dict)  # derivative symbol -> listing exchange ('' unknown)
    nondeductible: set = field(default_factory=set)          # derivative symbols off regulated markets
    written: dict = field(default_factory=dict)              # written option lots {"closed": [...], "open": [...]}
    wopt_rows: list[dict] = field(default_factory=list)      # written-option adjustments to IBKR's realized results
    end_lots: list[dict] = field(default_factory=list)   # open lots at period end (export for next year)
    preliminary: bool = False                             # some year-start lot has no user decision


def _ten_years(buy: str, sale: str) -> bool:
    try:
        b, s_ = date.fromisoformat(buy[:10]), date.fromisoformat(sale[:10])
    except ValueError:
        return False
    try:
        anniv = b.replace(year=b.year + 10)
    except ValueError:          # 29 Feb
        anniv = b.replace(year=b.year + 10, day=28)
    return s_ >= anniv


def _choice_lots(sym: str, opening: float, choice: dict | None, warnings: list[str],
                 premium: bool = False) -> list[list]:
    """Year-start lots for `sym` from the user's choice: [qty_signed, eur_per_unit|None, date, method, 0.0].
    premium=True: an option position (cost = premium paid; no hankintameno-olettama)."""
    if not choice or choice.get("method") in (None, "", "unresolved"):
        return [[opening, None, "avaava", "unresolved", 0.0]]
    if choice.get("method") == "ibkr":
        return [[opening, None, "avaava", "ibkr", 0.0]]
    sign = 1.0 if opening > 0 else -1.0
    out, left = [], abs(opening)
    raw = choice.get("lots") or []
    for i, lot in enumerate(raw):
        q = abs(float(lot.get("qty") or 0)) or (left if i == len(raw) - 1 else 0.0)
        q = min(q, left)
        if q <= 1e-9:
            continue
        d = str(lot.get("date") or "")[:10]
        if lot.get("olettama") or choice.get("method") == "olettama":
            if sign < 0 or not d or premium:
                warnings.append(f"{sym}: hankintameno-olettama vaatii ostopäivän eikä sovellu lyhyeen positioon — "
                                "erä jätetty ratkaisemattomaksi.")
                out.append([sign * q, None, "avaava", "unresolved", 0.0])
            else:
                out.append([sign * q, None, d, "olettama", 0.0])
        else:
            cost = lot.get("cost_eur")
            if cost in (None, "") or not d:
                warnings.append(f"{sym}: alkuperäisestä erästä puuttuu ostopäivä tai hankintameno — erä jätetty "
                                "ratkaisemattomaksi.")
                out.append([sign * q, None, "avaava", "unresolved", 0.0])
            else:
                out.append([sign * q, abs(float(cost)) / q, d, "manual", 0.0])
        left -= q
    if left > 1e-6:
        warnings.append(f"{sym}: syötetyt erät ({_fi(abs(opening) - left, 4)} kpl) eivät kata vuoden alun positiota "
                        f"({_fi(abs(opening), 4)} kpl) — loput {_fi(left, 4)} kpl ratkaisemattomia.")
        out.append([sign * left, None, "avaava", "unresolved", 0.0])
    return out


def _ibkr_premium(st: Statement, ev: dict, leg: dict | None) -> float | None:
    """IBKR folds an exercised call's premium into the share basis: premium ≈ basis − cash of the Ex share row,
    converted at the leg's own EUR/currency ratio. None when it cannot be derived (e.g. puts)."""
    if ev["right"] != "C" or not leg:
        return None
    for r in st.exercise_rows:
        if r["date"] == ev["date"] and r["symbol"] == ev["underlying"] and abs(r["qty"] - leg["qty"]) < 1e-6 \
                and r["cash"] and abs(r["basis"]) > abs(r["cash"]):
            return (abs(r["basis"]) - abs(r["cash"])) * (leg["eur"] / abs(r["cash"]))
    return None


def option_events(st: Statement, warnings: list[str], choices: dict | None = None,
                  written: dict | None = None) -> tuple[list[dict], list[dict]]:
    """FIFO over option contracts; returns (exercise/assignment events, stock legs with the premium applied).

    Bought option exercised (OPT-H3): premium paid → cost of shares received (call) / off the sale price (put).
    Written option assigned in the year it was written (OPT-H4): premium received → sale price of shares delivered
    (call) / off the cost of shares received (put). Written in an earlier year (OPT-H5, option A): no adjustment.
    `written` (optional dict) receives {"closed": [...], "open": [...]} records of written (short) option lots."""
    choices = choices or {}
    legs = [dict(x) for x in st.stock_legs]
    start = st.period_start or ""
    if written is not None:
        written.setdefault("closed", [])
        written.setdefault("open", [])
    if not st.option_trades:
        return [], legs
    end_qty = defaultdict(float)
    for p in st.positions:
        if p.asset_class in OPTION_CLASSES:
            end_qty[p.symbol] += p.quantity
    by_sym = defaultdict(list)
    for i, t in enumerate(st.option_trades):
        by_sym[t["symbol"]].append((t["date"], i, t))
    events = []
    for sym, ts in by_sym.items():
        ts.sort(key=lambda x: (x[0], x[1]))
        opening = end_qty.get(sym, 0.0) - sum(t["qty"] for _, _, t in ts)
        lots: deque = deque()   # [contracts_signed, eur_per_contract or None, date, method]
        if abs(opening) > 1e-9:
            lots.extend([l[:4] for l in _choice_lots(sym, opening, choices.get(sym), warnings, premium=True)])
        for d, _, t in ts:
            q, cs = t["qty"], codes(t["code"])
            px = (t["eur"] / abs(q)) if (q and t["eur"] is not None) else None
            used, q0, closing_short = [], abs(q), q > 0 and lots and lots[0][0] < 0
            while abs(q) > 1e-9 and lots and (lots[0][0] > 0) != (q > 0):
                lot = lots[0]
                n = min(abs(q), abs(lot[0]))
                used.append((n, lot[1], lot[3], lot[2]))
                lot[0] += n if lot[0] < 0 else -n
                q += n if q < 0 else -n
                if abs(lot[0]) < 1e-9:
                    lots.popleft()
            if abs(q) > 1e-9:
                lots.append([q, px, d, "fifo"])
            if used and closing_short and written is not None:   # written option bought back / expired / assigned
                for n, e, m, od in used:
                    same_year = m == "fifo" and od >= start
                    prem = n * e if (e is not None and m not in ("unresolved", "ibkr")) else (
                        t["basis_eur"] * n / q0 if t.get("basis_eur") else None)
                    written["closed"].append({
                        "symbol": sym, "opened": od, "closed": d, "contracts": n, "premium_eur": prem,
                        "cost_eur": (px or 0.0) * n, "how": "A" if "A" in cs else ("Ep" if "Ep" in cs else "C"),
                        "same_year": same_year, "expiry": t.get("expiry", "")})
            if used and ("Ex" in cs or "A" in cs):
                n_tot = sum(u[0] for u in used)
                if "A" in cs:   # written option: only lots written in this period move their premium into shares
                    known = [(n, e) for n, e, m, od in used if e is not None and m == "fifo" and od >= start]
                else:
                    known = [(n, e) for n, e, m, _ in used if e is not None and m not in ("unresolved", "ibkr")]
                events.append({"date": d, "symbol": sym, "underlying": t["underlying"], "right": t["right"],
                               "mult": t["mult"], "contracts": n_tot, "kind": "exercise" if "Ex" in cs else "assignment",
                               "premium_eur": sum(n * e for n, e in known),
                               "unknown_contracts": n_tot - sum(n for n, _ in known),
                               "methods": sorted({m for _, _, m, _ in used}),
                               "bought": min(u[3] for u in used)})
        if written is not None:
            for lot in lots:
                if lot[0] < 0:
                    written["open"].append({"symbol": sym, "opened": lot[2], "contracts": -lot[0],
                                            "premium_eur": (-lot[0]) * lot[1] if lot[1] is not None else None,
                                            "same_year": lot[3] == "fifo" and lot[2] >= start,
                                            "expiry": next((x["expiry"] for x in st.option_trades
                                                            if x["symbol"] == sym and x.get("expiry")), "")})
    used_legs = set()
    for ev in events:
        if ev["kind"] == "assignment":
            _assign(ev, legs, used_legs, warnings)
            continue
        if ev["right"] not in ("C", "P"):
            warnings.append(f"{ev['symbol']}: option tyyppiä (C/P) ei tunnistettu — preemiota ei kohdistettu.")
            ev["target"] = "Ei kohdistettu"
            continue
        want = ev["contracts"] * ev["mult"] * (1 if ev["right"] == "C" else -1)
        leg = next((x for i, x in enumerate(legs) if i not in used_legs and x["symbol"] == ev["underlying"]
                    and x["date"] == ev["date"] and abs(x["qty"] - want) < 1e-6), None)
        if leg is None:
            warnings.append(f"{ev['symbol']}: toteutukselle {ev['date']} ei löytynyt osakekauppaa ({ev['underlying']}, "
                            f"{_fi(want, 0)} kpl) — preemiota ei kohdistettu.")
            ev["target"] = "Ei kohdistettu"
            continue
        used_legs.add(legs.index(leg))
        prem = ev["premium_eur"]
        if ev["unknown_contracts"] > 1e-9:
            if "ibkr" in ev["methods"]:
                sug = _ibkr_premium(st, ev, leg)
                if sug is None:
                    warnings.append(f"{ev['symbol']}: preemiota ei voitu johtaa IBKR:n luvuista — käytetty 0 €.")
                else:
                    prem += sug * ev["unknown_contracts"] / ev["contracts"]
            ev["ibkr_suggestion_eur"] = _ibkr_premium(st, ev, leg)
        ev["premium_eur"] = prem
        leg.setdefault("eur_orig", leg["eur"])   # cash amount before the premium (olettama uses the gross price)
        if ev["right"] == "C":
            leg["eur"] += prem
            ev["target"] = "Osakkeiden hankintamenoon"
        else:
            leg["eur"] = max(leg["eur"] - prem, 0.0)
            ev["target"] = "Vähennetty osakkeiden luovutushinnasta"
        leg["opt_prem"] = leg.get("opt_prem", 0.0) + prem
        leg["option"] = ev["symbol"]
    return events, legs


def _assign(ev: dict, legs: list[dict], used_legs: set, warnings: list[str]) -> None:
    """OPT-H4 / OPT-H5 (option A) for an assigned written option."""
    prem, prior = ev["premium_eur"], ev["unknown_contracts"]
    if prior > 1e-9:
        warnings.append(f"{ev['symbol']}: toteutusvelvoite {ev['date']} — {_fi(prior, 0)} sopimusta asetettu aiempana "
                        "vuonna; preemio on verotettu asetusvuonna, eikä osakkeiden hintaa oikaista (OPT-H5).")
    if prem <= 1e-9 or ev["right"] not in ("C", "P"):
        ev["target"] = "Toteutusvelvoite — asetettu aiempana vuonna, ei oikaistu (OPT-H5)" if prior > 1e-9 \
            else "Toteutusvelvoite — preemio tuntematon, ei oikaistu"
        return
    n_same = ev["contracts"] - prior
    want = n_same * ev["mult"] * (-1 if ev["right"] == "C" else 1)      # call: shares delivered; put: received
    leg = next((x for i, x in enumerate(legs) if i not in used_legs and x["symbol"] == ev["underlying"]
                and x["date"] == ev["date"] and (x["qty"] > 0) == (want > 0)
                and abs(abs(x["qty"]) - abs(ev["contracts"] * ev["mult"])) < 1e-6), None)
    if leg is None:
        warnings.append(f"{ev['symbol']}: toteutusvelvoitteelle {ev['date']} ei löytynyt osakekauppaa — preemiota ei "
                        "kohdistettu.")
        ev["target"] = "Ei kohdistettu"
        return
    used_legs.add(legs.index(leg))
    if ev["right"] == "C":       # premium received is part of the sale price of the shares delivered
        leg["eur"] += prem
        ev["target"] = "Lisätty toimitettujen osakkeiden luovutushintaan (OPT-H4)"
    else:                        # premium received lowers the acquisition cost of the shares received
        leg.setdefault("eur_orig", leg["eur"])
        leg["eur"] = max(leg["eur"] - prem, 0.0)
        ev["target"] = "Vähennetty saatujen osakkeiden hankintamenosta (OPT-H4)"
    leg["option"] = ev["symbol"]


_CA_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s+for\s+(\d+(?:\.\d+)?)", re.I)


def _ca_kind(desc: str) -> str:
    if re.search(r"\bsplit\b", desc, re.I):
        return "split"
    if re.search(r"stock dividend|bonus (issue|share)|capitali[sz]ation issue|rahastoanti", desc, re.I):
        return "stock_dividend"
    return "unknown"


def corporate_events(st: Statement) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Share corporate actions as per-symbol events: {symbol: [event]}, plus ticker renames {old: new}.

    Rows of one action (same date, type and ratio) are grouped; when the old line is removed under one ticker and the
    new one added under another (typical reverse split), the old ticker's lots move to the new ticker."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in st.corporate_actions:
        m = _CA_RATIO.search(r["description"])
        groups[(r["date"], _ca_kind(r["description"]), m.groups() if m else None)].append(r)
    rename: dict[str, str] = {}
    for (_, _, _), rows in groups.items():
        neg = {r["symbol"] for r in rows if r["qty"] < 0}
        pos = {r["symbol"] for r in rows if r["qty"] > 0}
        if len(neg) == 1 and len(pos) == 1 and neg != pos:
            rename[next(iter(neg))] = next(iter(pos))
    events: dict[str, list[dict]] = defaultdict(list)
    for (d, kind, ratio), rows in groups.items():
        by_sym: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_sym[rename.get(r["symbol"], r["symbol"])].append(r)
        for sym, rs in by_sym.items():
            pe = [r["proceeds_eur"] for r in rs]
            events[sym].append({"date": d, "symbol": sym, "kind": kind,
                                "ratio": (float(ratio[0]), float(ratio[1])) if ratio else None,
                                "delta": sum(r["qty"] for r in rs),
                                "proceeds_eur": None if any(p is None for p in pe) else sum(pe),
                                "description": rs[0]["description"]})
    return events, rename


def fifo_full(st: Statement, warnings: list[str], choices: dict | None = None,
              legs_override: list[dict] | None = None, ca_log: list[dict] | None = None,
              blocked: list[str] | None = None, classes: frozenset = frozenset({"Stocks"})) -> tuple[list[Match], list[dict]]:
    """FIFO per symbol over history legs (earlier statements) + this period's legs.

    Returns this period's disposals and the lots still open at period end. The year-start position (end holding
    minus all known trades) is handled by the user's choice for that symbol; without one it is 'unresolved'."""
    choices = choices or {}
    end_qty = defaultdict(float)
    for p in st.positions:
        if p.asset_class in classes:
            end_qty[p.symbol] += p.quantity
    start = st.period_start or ""
    legs_by_sym = defaultdict(list)
    stock_legs = legs_override if legs_override is not None else st.stock_legs
    ca_events, rename = corporate_events(st)
    for i, x in enumerate(list(st.history_legs) + list(stock_legs)):
        legs_by_sym[rename.get(x["symbol"], x["symbol"])].append((x["date"], i, x))
    out: list[Match] = []
    end_lots: list[dict] = []
    for sym in sorted(set(legs_by_sym) | set(ca_events) | {k for k, q in end_qty.items() if abs(q) > 1e-9}):
        # corporate actions take effect at the start of their day, before that day's trades
        seq = sorted([(d, 1, i, x) for d, i, x in legs_by_sym.get(sym, [])]
                     + [(e["date"], 0, j, e) for j, e in enumerate(ca_events.get(sym, []))], key=lambda t: t[:3])
        legs = [(d, i, x) for d, k, i, x in seq if k == 1]
        opening = (end_qty.get(sym, 0.0) - sum(x["qty"] for _, _, x in legs)
                   - sum(e["delta"] for e in ca_events.get(sym, []) if e["kind"] != "unknown"))
        lots: deque = deque()  # [qty_signed, eur_per_share or None, date, method, option premium per share]
        if abs(opening) > 1e-9:
            lots.extend(_choice_lots(sym, opening, choices.get(sym), warnings))
        stop = False
        for d, kind, _, x in seq:
            if stop:
                break
            if kind == 0:   # corporate action
                stop = _apply_ca(sym, x, lots, d >= start, out, warnings, ca_log)
                if stop and blocked is not None:
                    blocked.append(sym)
                continue
            q, px = x["qty"], x["eur"] / abs(x["qty"]) if x["qty"] else 0.0
            pps = x.get("opt_prem", 0.0) / abs(x["qty"]) if x["qty"] else 0.0
            # gross sale price per share: before the selling commission and before a put-premium deduction
            gross = ((x.get("eur_orig", x["eur"]) + (x.get("comm_eur") or 0.0)) / abs(q)) if q else 0.0
            in_period = d >= start
            while abs(q) > 1e-9 and lots and (lots[0][0] > 0) != (q > 0):
                lot = lots[0]
                n = min(abs(q), abs(lot[0]))
                if in_period:
                    if q < 0:   # selling against long lot: gross price; costs = purchase + (gross − net) of the sale
                        cost = 0.0 if lot[3] == "olettama" else (lot[1] or 0.0) * n + (gross - px) * n
                        m = Match(sym, d, lot[2], n, gross * n, cost, method=lot[3],
                                  presumption_rate=0.4 if _ten_years(lot[2], d) else 0.2)
                    else:       # buying back a short lot
                        m = Match(sym, d, lot[2], n, (lot[1] or 0.0) * n, px * n, short=True, method=lot[3])
                    m.premium = (lot[4] + pps) * n
                    out.append(m)
                lot[0] += n if lot[0] < 0 else -n
                q += n if q < 0 else -n
                if abs(lot[0]) < 1e-9:
                    lots.popleft()
            if abs(q) > 1e-9:
                lots.append([q, px, d, "fifo" if in_period else "history", pps])
        for lot in lots:
            known = lot[1] is not None
            end_lots.append({"symbol": sym, "date": lot[2] if lot[2] != "avaava" else "", "qty": lot[0],
                             "cost_eur": abs(lot[1] * lot[0]) if known else None,
                             "olettama": lot[3] == "olettama", "method": lot[3]})
    return out, end_lots


def _apply_ca(sym: str, ev: dict, lots: deque, in_period: bool, out: list, warnings: list[str],
              log: list[dict] | None) -> bool:
    """Apply a split / stock dividend to the open lots (Vero: total acquisition cost and holding period unchanged;
    cash for fractional shares is a disposal). Returns True when FIFO must stop for the symbol (unknown action)."""
    entry = dict(ev, factor=None, fraction=0.0, handled="")
    if log is not None:
        log.append(entry)
    held = sum(l[0] for l in lots)
    if ev["kind"] == "unknown":
        warnings.append(f"{sym}: tuntematon yritystapahtuma {ev['date']} ({ev['description'][:80]}) — FIFO-laskenta "
                        "keskeytetty tälle osakkeelle; tarkista käsin. Laskelma on keskeneräinen.")
        entry["handled"] = "Tuntematon — FIFO keskeytetty"
        return True
    if abs(held) < 1e-9:
        warnings.append(f"{sym}: yritystapahtuma {ev['date']}, mutta ei avoimia eriä — ohitettu.")
        entry["handled"] = "Ei avoimia eriä — ohitettu"
        return False
    after = held + ev["delta"]
    if ev["ratio"]:
        a, b_ = ev["ratio"]
        f = (1 + a / b_) if ev["kind"] == "stock_dividend" else a / b_
    else:
        f = after / held
    fraction = held * f - after                  # shares (new units) not delivered → paid in cash
    if fraction < -1e-6:
        warnings.append(f"{sym}: yritystapahtuman {ev['date']} määrät eivät täsmää suhteeseen — käytetty IBKR:n määriä.")
        f, fraction = after / held, 0.0
    if f <= 1e-12:      # the whole position disappeared: not a split we can apply
        warnings.append(f"{sym}: yritystapahtuma {ev['date']} poisti koko position ({ev['description'][:80]}) — "
                        "FIFO-laskenta keskeytetty tälle osakkeelle; tarkista käsin. Laskelma on keskeneräinen.")
        entry["handled"] = "Positio poistui — FIFO keskeytetty"
        return True
    for l in lots:                                 # same total cost, same purchase dates
        l[0] *= f
        if l[1] is not None:
            l[1] /= f
        l[4] /= f
    entry["factor"], entry["fraction"] = f, max(fraction, 0.0)
    entry["handled"] = "Erät kerrottu suhteella, hankintameno ennallaan"
    if fraction > 1e-6:
        cash = ev["proceeds_eur"]
        if cash is None:
            warnings.append(f"{sym}: murto-osien käteissuoritus {ev['date']} ilman EUR-määrää — luovutus 0 €.")
            cash = 0.0
        left, sign = fraction, (1 if held > 0 else -1)
        while left > 1e-9 and lots:
            lot = lots[0]
            n = min(left, abs(lot[0]))
            if in_period and sign > 0:
                out.append(Match(sym, ev["date"], lot[2], n, cash * n / fraction,
                                 0.0 if lot[3] == "olettama" else (lot[1] or 0.0) * n, method=lot[3],
                                 presumption_rate=0.4 if _ten_years(lot[2], ev["date"]) else 0.2,
                                 note="murto-osa, yritystapahtuma"))
            lot[0] -= sign * n
            left -= n
            if abs(lot[0]) < 1e-9:
                lots.popleft()
        entry["handled"] += f"; murto-osa {_fi(fraction, 4)} kpl luovutettu käteisellä"
    return False


def crypto_fifo(st: Statement, warnings: list[str], choices: dict | None = None) -> tuple[list[Match], list[dict]]:
    """Crypto assets: FIFO per coin like shares (Vero: virtuaalivaluutat are disposed in acquisition order),
    with year-start lots, IBKR back-out, hankintameno-olettama. No corporate actions or option effects."""
    if not st.crypto_legs:
        return [], []
    from dataclasses import replace
    cst = replace(st, stock_legs=list(st.crypto_legs), history_legs=[], corporate_actions=[], option_trades=[])
    ms, end = fifo_full(cst, warnings, choices, list(st.crypto_legs), classes=frozenset(CRYPTO_CLASSES))
    _ibkr_backout(ms, {r.symbol: r.realized for r in st.ru if r.asset_class in CRYPTO_CLASSES})
    return ms, end


def fifo(st: Statement, warnings: list[str], choices: dict | None = None) -> list[Match]:
    _, legs = option_events(st, [], choices)
    return fifo_full(st, warnings, choices, legs)[0]


def _ibkr_backout(matches: list[Match], ru: dict[str, float]) -> dict[str, float]:
    """Lots without a known cost ('ibkr'/'unresolved'): back out their cost so the symbol's total equals IBKR's
    realized P/L. Returns the backed-out cost (long) / proceeds (short) per symbol."""
    by_sym = defaultdict(list)
    for m in matches:
        by_sym[m.symbol].append(m)
    out = {}
    for sym, ms in by_sym.items():
        op = [m for m in ms if m.method in ("ibkr", "unresolved")]
        if not op:
            continue
        known = sum(m.proceeds - m.cost for m in ms if m.method not in ("ibkr", "unresolved", "olettama"))
        target = ru.get(sym, 0.0) - known
        tot_qty = sum(m.qty for m in op)
        for m in op:
            share = m.qty / tot_qty if tot_qty else 0
            if m.short:
                m.proceeds = m.cost + target * share
            else:
                m.cost = m.proceeds - target * share
        out[sym] = sum(m.proceeds if m.short else m.cost for m in op)
    return out


def apply_presumption(matches: list[Match], enabled: bool) -> None:
    """Hankintameno-olettama per lot (Vero 48262 §4.2.2): 20 % (40 % if held ≥ 10 years) of the GROSS sale price,
    used instead of all actual costs when it gives the lower gain; it never creates or increases a loss."""
    for m in matches:
        if m.short or m.presumption_rate <= 0:
            m.presumption_rate, m.deduction = 0.0, m.cost
        elif m.method == "olettama":          # the user chose the olettama for a year-start lot
            m.deduction = m.presumption
        elif enabled and m.presumption > m.cost:
            m.deduction = m.presumption
        else:
            m.deduction = m.cost


def opening_summary(matches: list[Match], backout: dict[str, float]) -> list[dict]:
    """Year-start lots consumed this period, per symbol (for the UI step and the workbook)."""
    agg: dict[str, dict] = {}
    for m in matches:
        if m.method in ("fifo", "history"):
            continue
        a = agg.setdefault(m.symbol, {"symbol": m.symbol, "short": m.short, "qty": 0.0, "proceeds_eur": 0.0,
                                      "cost_eur": 0.0, "first_sale": m.sale_date, "last_sale": m.sale_date,
                                      "methods": set()})
        a["qty"] += m.qty
        a["proceeds_eur"] += m.proceeds
        a["cost_eur"] += m.cost
        a["first_sale"], a["last_sale"] = min(a["first_sale"], m.sale_date), max(a["last_sale"], m.sale_date)
        a["methods"].add(m.method)
    out = []
    for sym, a in sorted(agg.items()):
        a["methods"] = sorted(a["methods"])
        a["ibkr_suggestion_eur"] = backout.get(sym)
        out.append(a)
    return out


def opening_lots(st: Statement) -> list[dict]:
    """Year-start positions that this period's sales consume and that need the user's decision (no history)."""
    ms = fifo(st, [])
    ru = {r.symbol: r.realized for r in st.ru if r.asset_class == "Stocks"}
    end_qty = defaultdict(float)
    for p in st.positions:
        if p.asset_class == "Stocks":
            end_qty[p.symbol] += p.quantity
    rows = opening_summary(ms, _ibkr_backout(ms, ru))
    for r in rows:
        r["kind"] = "stock"
    ca, rename = corporate_events(st)
    for r in rows:   # the whole year-start position (the user enters lots for all of it)
        legs = [x["qty"] for x in list(st.history_legs) + list(st.stock_legs)
                if rename.get(x["symbol"], x["symbol"]) == r["symbol"]]
        r["opening_qty"] = (end_qty.get(r["symbol"], 0.0) - sum(legs)
                            - sum(e["delta"] for e in ca.get(r["symbol"], []) if e["kind"] != "unknown"))
        r["ccy"] = next((x["ccy"] for x in st.stock_legs if x["symbol"] == r["symbol"]), "")
    cm, _ = crypto_fifo(st, [])
    crypto_rows = opening_summary(cm, {})
    for r in crypto_rows:
        r["kind"] = "crypto"
        r["ibkr_suggestion_eur"] = sum(m.cost for m in cm if m.symbol == r["symbol"] and m.method == "unresolved")
        r["opening_qty"] = (sum(p.quantity for p in st.positions if p.symbol == r["symbol"])
                            - sum(x["qty"] for x in st.crypto_legs if x["symbol"] == r["symbol"]))
        r["ccy"] = next((x["ccy"] for x in st.crypto_legs if x["symbol"] == r["symbol"]), "")
    return rows + option_opening(option_events(st, [])[0], st) + crypto_rows


def option_opening(events: list[dict], st: Statement) -> list[dict]:
    """Exercised options opened before the period (premium unknown) — need the user's decision like shares."""
    out = {}
    for ev in events:
        if ev["kind"] != "exercise" or ev["unknown_contracts"] <= 1e-9:
            continue
        o = out.setdefault(ev["symbol"], {
            "symbol": ev["symbol"], "kind": "option", "short": False, "qty": 0.0, "proceeds_eur": None,
            "cost_eur": 0.0, "first_sale": ev["date"], "last_sale": ev["date"], "methods": ev["methods"],
            "ibkr_suggestion_eur": None, "ccy": next((t["ccy"] for t in st.option_trades if t["symbol"] == ev["symbol"]), ""),
            "opening_qty": sum(p.quantity for p in st.positions if p.symbol == ev["symbol"])
                           - sum(t["qty"] for t in st.option_trades if t["symbol"] == ev["symbol"]),
            "underlying": ev["underlying"]})
        o["qty"] += ev["unknown_contracts"]
        o["last_sale"] = max(o["last_sale"], ev["date"])
        if ev.get("ibkr_suggestion_eur") is not None:
            o["ibkr_suggestion_eur"] = (o["ibkr_suggestion_eur"] or 0.0) + ev["ibkr_suggestion_eur"] * ev["unknown_contracts"] / ev["contracts"]
    return list(out.values())


def build_personal(st: Statement, s: PSettings) -> PBooks:
    ecb_note = None
    if s.fx_mode == "ecb":
        from dataclasses import replace
        from .fx_ecb import convert_legs
        if not st.ecb_rates:
            ecb_note = ("EKP-kurssit valittu, mutta EKP:n kurssitiedostoa (eurofxref-hist.csv) ei ole lisätty — käytetty "
                        "IBKR:n kursseja.")
        else:
            w: list[str] = []
            alt = build_personal(st, replace(s, fx_mode="ibkr"))
            st = replace(st, stock_legs=convert_legs(st.stock_legs, st.ecb_rates, st.base_currency, w),
                         history_legs=convert_legs(st.history_legs, st.ecb_rates, st.base_currency, w))
            ecb_note = (w, alt.v["sec_net"], alt.v["capital_income"])
    b = PBooks(st, s)
    v = b.v
    b.warnings += st.warnings
    if isinstance(ecb_note, str):
        b.warnings.append(ecb_note)
    if not st.stock_legs and any(r.asset_class == "Stocks" for r in st.ru):
        b.warnings.append("Osakekauppojen EUR-rivejä ei löytynyt — luovutushinnat puuttuvat. Käytä PDF:ää, jossa on "
                          "'Forex P/L Details' (Realized Summary / Activity Statement).")
    if any(not x.get("exact", True) for x in st.stock_legs):
        b.warnings.append("Osa valuuttamääräisistä kaupoista muunnettu keskikurssilla (CSV). Tarkat EUR-arvot: "
                          "käytä PDF-raporttia (Forex P/L Details).")

    b.ru_by_symbol = {r.symbol: r.realized for r in st.ru if r.asset_class == "Stocks"}
    b.option_events, legs = option_events(st, b.warnings, s.opening_choices, b.written)
    b.matches, b.end_lots = fifo_full(st, b.warnings, s.opening_choices, legs, b.ca_events, b.blocked)
    backout = _ibkr_backout(b.matches, b.ru_by_symbol)
    apply_presumption(b.matches, s.use_presumption)
    b.opening = [dict(o, kind="stock") for o in opening_summary(b.matches, backout)]
    b.opening += option_opening(b.option_events, st)
    b.crypto_matches, crypto_end = crypto_fifo(st, b.warnings, s.opening_choices)
    apply_presumption(b.crypto_matches, s.use_presumption)
    b.end_lots += crypto_end
    b.opening += [dict(o, kind="crypto") for o in opening_summary(b.crypto_matches, {})]
    if b.crypto_matches and any(not x.get("exact") for x in st.crypto_legs):
        b.warnings.append("Kryptokaupat muunnettu euroiksi keskikurssilla (IBKR:n luokkasummista); tarkista "
                          "kauppakohtaiset kurssit tarvittaessa.")
    if st.option_trades and not st.stock_legs:
        b.warnings.append("Optiokauppoja löytyi, mutta osakekauppoja ei — toteutusten preemiota ei voitu kohdistaa.")
    unresolved = [o["symbol"] for o in b.opening if "unresolved" in o["methods"]]
    b.preliminary = bool(unresolved) or bool(b.blocked)
    if unresolved:
        b.warnings.insert(0, "KESKENERÄINEN LASKELMA: vuoden alun positioille " + ", ".join(unresolved) +
                          " ei ole valittu käsittelytapaa — hankintameno on päätelty IBKR:n luvuista. Valitse käsittely "
                          "(alkuperäiset tiedot, edellisen vuoden raportti, hankintameno-olettama tai IBKR:n luku).")
    for o in b.opening:
        if o["methods"] == ["ibkr"]:
            b.warnings.append(f"{o['symbol']}: vuoden alun erän hankintameno IBKR:n luvuista (valittu). Verohallinto "
                              "edellyttää alkuperäistä hankintahintaa tai hankintameno-olettamaa.")
    if st.history_periods:
        b.warnings.append("Erähistoria aiemmista raporteista: " + ", ".join(st.history_periods) + ".")
    M = b.matches
    v["sec_proceeds"] = sum(m.proceeds for m in M)
    v["sec_cost"] = sum(m.proceeds - m.result for m in M)   # deductions used: actual costs or olettama
    v["sec_cost_actual"] = sum(m.cost for m in M)
    v["sec_gains"] = sum(m.result for m in M if m.result > 0)
    v["sec_losses"] = sum(m.result for m in M if m.result < 0)
    v["sec_net"] = v["sec_gains"] + v["sec_losses"]
    v["sec_net_actual"] = sum(m.proceeds - m.cost for m in M)
    used = [m for m in M if m.presumption_used]
    v["presumption_lots"] = float(len(used))
    v["presumption_benefit"] = sum(m.presumption - m.cost for m in used if m.method != "olettama")
    v["ru_sec_net"] = sum(b.ru_by_symbol.values())

    b.derivatives = [r for r in st.ru if r.asset_class in DERIVATIVE_CLASSES]
    allowed = REGULATED_EXCHANGES | {x.strip().upper() for x in s.extra_regulated.split(",") if x.strip()}
    b.der_exch = {r.symbol: st.listing_exch.get(r.symbol, "") for r in b.derivatives}
    nondeductible = [r for r in b.derivatives if b.der_exch[r.symbol] and b.der_exch[r.symbol].upper() not in allowed]
    unknown = sorted({r.symbol for r in b.derivatives if not b.der_exch[r.symbol] and r.loss})
    b.nondeductible = {r.symbol for r in nondeductible}
    v["der_gains"] = sum(r.profit for r in b.derivatives)
    v["der_losses"] = sum(r.loss for r in b.derivatives if r.symbol not in b.nondeductible)
    v["der_losses_nondeductible"] = sum(r.loss for r in nondeductible)
    _written_options(b)
    if nondeductible and v["der_losses_nondeductible"]:
        b.warnings.append("Johdannaisia muulla kuin säännellyllä markkinalla (" + ", ".join(sorted(
            {f"{r.symbol} @ {b.der_exch[r.symbol]}" for r in nondeductible})) + "): tappiot "
            f"{_fi(-v['der_losses_nondeductible'])} € eivät ole vähennyskelpoisia (Vero 48914). Lisää markkinapaikka "
            "asetuksiin, jos se on säännelty tai siihen rinnastettava.")
    if unknown:
        b.warnings.append("Markkinapaikka tuntematon (" + ", ".join(unknown[:10]) + ("…" if len(unknown) > 10 else "")
                          + "): tappiot on oletettu vähennyskelpoisiksi. Activity Statement CSV kertoo markkinapaikan.")
    fx = [r for r in st.ru if r.asset_class == "Forex"]
    v["fx_gains"] = sum(r.profit for r in fx) if s.include_fx else 0.0
    v["fx_losses"] = sum(r.loss for r in fx) if s.include_fx else 0.0
    v["fx_memo"] = sum(r.realized for r in fx)
    _cfd(b)
    C = b.crypto_matches
    v["crypto_proceeds"] = sum(m.proceeds for m in C)
    v["crypto_cost"] = sum(m.proceeds - m.result for m in C)
    v["crypto_cost_actual"] = sum(m.cost for m in C)
    v["crypto_gains"] = sum(m.result for m in C if m.result > 0)
    v["crypto_losses"] = sum(m.result for m in C if m.result < 0)
    if any(r.asset_class in CRYPTO_CLASSES for r in st.ru) and not st.crypto_legs:
        b.warnings.append("Kryptovaroja on R&U-raportissa, mutta kauppariviä ei löytynyt — lisää Activity Statement CSV; "
                          "kryptot puuttuvat laskelmasta.")
    other = [r for r in st.ru if r.asset_class not in DERIVATIVE_CLASSES | CFD_CLASSES | CRYPTO_CLASSES | {"Stocks", "Forex"}]
    if other:
        b.warnings.append("Tuntemattomat omaisuusluokat (ei mukana): " + ", ".join(sorted({r.asset_class for r in other})))

    # small disposals: all sale prices of the year together (securities + crypto)
    tot_proceeds = v["sec_proceeds"] + v["crypto_proceeds"]
    v["small_exempt"] = 1.0 if 0 < tot_proceeds <= s.small_limit else 0.0
    sec_g, sec_l = v["sec_gains"], v["sec_losses"]
    cr_g, cr_l = v["crypto_gains"], v["crypto_losses"]
    if v["small_exempt"]:
        sec_g = cr_g = 0.0
        if v["sec_cost_actual"] + v["crypto_cost_actual"] <= s.small_limit:
            sec_l = cr_l = 0.0
    v["disp_gains"] = sec_g + cr_g + v["der_gains"] + v["fx_gains"]
    v["disp_losses"] = sec_l + cr_l + v["der_losses"] + v["fx_losses"]
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

    if abs(v["sec_net_actual"] - v["ru_sec_net"]) > 0.02 * max(1.0, abs(v["ru_sec_net"])) + 50:
        b.warnings.append(f"Osakkeiden FIFO-tulos {_fi(v['sec_net_actual'], 0)} € (todellisilla hankintamenoilla) poikkeaa IBKR:n R&U-tuloksesta "
                          f"{_fi(v['ru_sec_net'], 0)} € — ero johtuu valuuttakurssimenetelmästä (Vero: osto- ja "
                          "myyntipäivän kurssit). Tarkista, jos ero on suuri.")
    b.warnings.append("Varmista, että IBKR:n lot matching -asetus on FIFO (Verohallinto edellyttää FIFO-järjestystä).")
    if isinstance(ecb_note, tuple):
        w, alt_sec, alt_ci = ecb_note
        b.warnings += w
        v["fx_alt_sec_net"], v["fx_alt_capital_income"] = alt_sec, alt_ci
        b.warnings.insert(0, f"Valuuttakurssit: EKP:n viitekurssi selvityspäivältä. Arvopapereiden tulos "
                             f"{_fi(v['sec_net'])} € (IBKR:n kursseilla {_fi(alt_sec)} €, ero {_fi(v['sec_net'] - alt_sec)} €); "
                             f"pääomatulo {_fi(v['capital_income'])} € (IBKR:n kursseilla {_fi(alt_ci)} €).")
    return b


def _written_options(b: PBooks) -> None:
    """Written (sold) options on top of IBKR's realized results (Vero 48914 §2.4; decisions in docs/PAATOSREKISTERI.md).

    IBKR realizes a written option's result when it is closed: premium − buyback (or the whole premium on expiry).
    OPT-H1: premium of an option written this year and still open at year-end is taxable this year → added.
    OPT-H6: option written in an earlier year and bought back / expired now: its premium was taxed when written →
            removed from this year (the buyback cost remains a loss; for non-regulated markets only the gain is removed).
    OPT-H7/H8: written and closed in the same year: hankintameno-olettama 20 % of the premium (no buyback cost) when
            it gives the lower gain. Assignments: handled in the shares (OPT-H4) or not at all (OPT-H5)."""
    v, s, W = b.v, b.s, b.written
    ru = defaultdict(float)
    for r in b.derivatives:
        ru[r.symbol] += r.realized
    open_p = prior = prior_nd = benefit = 0.0
    unknown = set()
    for o in W.get("open", []):
        if not o["same_year"]:
            continue
        if o["premium_eur"] is None:
            unknown.add(o["symbol"])
            continue
        open_p += o["premium_eur"]
        b.wopt_rows.append({"rule": "OPT-H1", "symbol": o["symbol"], "date": o["opened"], "contracts": o["contracts"],
                            "amount": o["premium_eur"], "label": "Asetettu, avoin vuoden lopussa: preemio verotetaan nyt"})
    for c in W.get("closed", []):
        if c["how"] == "A":
            continue
        if c["premium_eur"] is None:
            unknown.add(c["symbol"])
            continue
        if not c["same_year"]:
            adj = c["premium_eur"]
            if c["symbol"] in b.nondeductible:        # loss not deductible: only remove a gain
                adj = min(adj, max(0.0, ru[c["symbol"]]))
            ru[c["symbol"]] -= adj
            prior += adj
            if c["symbol"] in b.nondeductible:
                prior_nd += adj
            b.wopt_rows.append({"rule": "OPT-H6", "symbol": c["symbol"], "date": c["closed"], "contracts": c["contracts"],
                                "amount": -adj, "label": "Asetettu aiempana vuonna: jo verotettu preemio vähennetään"})
        elif s.use_presumption:
            gain, olettama = c["premium_eur"] - c["cost_eur"], 0.8 * c["premium_eur"]
            if gain > olettama + 1e-9:
                benefit += gain - olettama
                b.wopt_rows.append({"rule": "OPT-H7", "symbol": c["symbol"], "date": c["closed"],
                                    "contracts": c["contracts"], "amount": -(gain - olettama),
                                    "label": "Hankintameno-olettama 20 % preemiosta (takaisinostokulua ei vähennetä)"})
    if unknown:
        b.warnings.append("Asetettujen optioiden preemio tuntematon (" + ", ".join(sorted(unknown)) + ") — ei oikaistu. "
                          "Lisää Activity Statement CSV.")
    if prior:
        b.warnings.append(f"Aiempana vuonna asetettujen optioiden preemiot {_fi(prior)} € on vähennetty tämän vuoden "
                          "tuloksesta, koska ne verotetaan asetusvuonna (OPT-H6). Tarkista, että ne on ilmoitettu silloin.")
    v["wopt_open_premium"], v["wopt_prior_premium"], v["wopt_presumption"] = open_p, prior, benefit
    v["der_gains"] += open_p - benefit - prior_nd     # non-regulated: the gain is removed, no deductible loss arises
    v["der_losses"] -= prior - prior_nd


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
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Osakkeet ja rahastot — luovutushinnat yhteensä", v["sec_proceeds"], "Bruttomyyntihinnat (ennen myyntikuluja)"),
        ("Arvopapereiden luovutukset (OmaVero / 9A)", "Osakkeet ja rahastot — hankintamenot ja kulut (tai hankintameno-olettamat) yhteensä", v["sec_cost"],
         "FIFO, ostopäivän kurssi" + (f"; olettama {int(v['presumption_lots'])} erässä" if v.get("presumption_lots") else "")),
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
    if b.crypto_matches:
        sec = "Virtuaalivaluutat (OmaVero)"
        rows += [(sec, "Kryptovarat — luovutushinnat yhteensä", v["crypto_proceeds"], "Bruttomyyntihinnat"),
                 (sec, "Kryptovarat — hankintamenot ja kulut (tai hankintameno-olettamat) yhteensä", v["crypto_cost"], "FIFO"),
                 (sec, "Kryptovarat — luovutusvoitot", v["crypto_gains"], ""),
                 (sec, "Kryptovarat — luovutustappiot", -v["crypto_losses"], "")]
    if v.get("der_losses_nondeductible"):
        rows.append(("Ei ilmoiteta (tieto)", "Vähennyskelvottomat johdannaistappiot (ei säännelty markkina)",
                     -v["der_losses_nondeductible"], "Vero 48914: tappio vähennyskelpoinen vain säännellyllä markkinalla"))
    if b.cfd_rows or v["cfd_costs_ignored"]:
        rows.append(("Ei ilmoiteta (tieto)", "Vähennyskelvottomat CFD-tappiot (ei huomioida)", -v["cfd_losses_ignored"],
                     "Verohallinto: CFD-tappiota ei huomioida verotuksessa"))
    if v["cfd_costs_ignored"]:
        rows.append(("Ei ilmoiteta (tieto)", "CFD-rahoituskulut (ei vähennetty)", v["cfd_costs_ignored"],
                     "Tulkinta: liittyvät CFD:ihin, joiden tappiot eivät ole vähennyskelpoisia"))
    return rows
