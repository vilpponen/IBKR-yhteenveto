"""JSON-ready summaries for the web UI (no UI framework dependencies)."""
from __future__ import annotations

from collections import defaultdict

from .books import Books, Settings, build, classify_transfers
from .excel import write_workbook
from .excel_personal import write_personal_workbook
from .model import Statement
from .personal import SOURCES, PBooks, PSettings, build_personal, omavero_fields, opening_lots



def _fi(x: float, d: int = 2) -> str:
    """Finnish number format: 1 234,56"""
    x = 0.0 if abs(x) < 0.5 * 10 ** -d else x
    return f"{x:,.{d}f}".replace(",", "\u00a0").replace(".", ",")

def _t(columns, rows, money=None):
    """Table: money = indices of numeric EUR columns (formatted client-side)."""
    return {"columns": columns, "rows": rows, "money": money if money is not None else []}


def recognised(st: Statement) -> dict:
    found = {
        "NAV": bool(st.nav), "Realized & Unrealized": bool(st.ru), "Avoimet positiot": bool(st.positions),
        "Kaupat/provisiot": st.commissions_eur is not None, "Korot": bool(st.interest),
        "Osingot": bool(st.dividends), "Lähdeverot": bool(st.withholding),
        "Talletukset & nostot": bool(st.deposits),
        "Transaktioverot (FTT)": st.transaction_fees_eur is not None or "Transaction Fees" in st.change_in_nav,
        "Change in NAV -tarkistukset": "Mark-to-Market" in st.change_in_nav,
        "Kauppakohtaiset EUR-määrät": bool(st.stock_legs) and all(x.get("exact") for x in st.stock_legs),
        "EKP-kurssit (valinnainen)": bool(st.ecb_rates),
    }
    return {
        "title": st.title, "name": st.name, "account": st.account, "customer_type": st.customer_type,
        "period_start": st.period_start, "period_end": st.period_end, "sources": st.source_files,
        "found": found, "nav_start": st.nav_start, "nav_end": st.nav_end,
        "net_deposits": st.deposits_total_eur or 0.0, "stock_legs": len(st.stock_legs),
        "is_corporate": any(k in (st.customer_type or "").lower() for k in ("corporate", "institution")),
        "history_periods": list(st.history_periods),
        # year-start positions consumed this period that need the user's decision (personal mode)
        "opening_lots": opening_lots(st),
        "warnings": list(st.warnings),
    }


# ------------------------------------------------------------------ company
def company(st: Statement, s: Settings) -> tuple[dict, bytes]:
    b: Books = build(st, s)
    v = b.v
    ok = abs(v["book_result"] - v["book_result_check"]) < 0.01 and abs(v["bs_equity"] - v["eq_close_calc"]) < 0.05
    kinds = classify_transfers(st.deposits)
    res = {
        "mode": "company",
        "heading": f"{s.company or st.name} · {st.account} · {st.period_start} – {st.period_end}",
        "caption": f"Omaisuuslaji: {s.share_category} · FTT: {_fi(v['ftt'])} € · avaavat arvonalentumiset: "
                   f"{_fi(s.opening_writedowns)} € · lähteet: {', '.join(st.source_files)}",
        "metrics": [
            ["Taloudellinen tulos (NAV)", v["E"]], ["Kirjanpidon tulos", v["book_result"]],
            ["Verotettava tulo (EVL)", v["taxable"]], ["Yhteisövero netto", v["tax_net"]],
            ["Valuuttakurssiero (johdettu)", v["F"]],
        ],
        "ok": ok,
        "ok_text": "Täsmäytys OK: tulos täsmää NAV-muutokseen ja tase IBKR:n NAV:iin." if ok else "Täsmäytys ei mene läpi.",
        "warnings": b.warnings,
        "download_label": "Lataa Excel-työkirja",
        "filename": f"{(s.company or st.name).replace(' ', '_')}_IBKR_{st.period_end[:4]}_tilinpaatos.xlsx",
        "sections": [],
        "tabs": {
            "Tuloslaskelma": _t(["Erä", "EUR"], [
                ["Luovutusvoitot", v["gains"]], ["Luovutustappiot", v["losses"]],
                ["Arvonalentumiset (muutos)", v["wd_charge"]], ["Valuuttakurssiero, netto", v["F"]],
                ["Osingot", v["div_ord"]], ["Payment in lieu", v["div_pil"]],
                ["Korkotuotot", v["int_income"]], ["Korkokulut", v["int_expense"]],
                ["Korkojaksotus", v["int_accrual_chg"]], ["Transaktioverot", v["ftt"]], ["Muut kulut", v["fees"]],
                ["Lähdeverot", v["wht_div"] + v["wht_int"]], ["KIRJANPIDON TULOS", v["book_result"]]], [1]),
            "EVL": _t(["Erä", "EUR"], [
                ["Kirjanpidon tulos", v["book_result"]], ["+ Lähdeverot", v["evl_add_wht"]],
                ["+ Arvonalentumiset futuurit/ETF", v["evl_add_wd_other"]],
                ["+ Arvonalentumiset osakkeet", v["evl_add_wd_shares"]],
                ["+ EVL 8 a § ylitys", v["evl8a_excess"]], ["− Tappioiden käyttö", v["evl8a_use_cf"]],
                ["VEROTETTAVA TULO", v["taxable"]], ["Yhteisövero", v["tax_gross"]],
                ["− Hyvitys", v["tax_credit"]], ["MAKSETTAVA", v["tax_net"]]], [1]),
            "Siirrot": _t(["Päivä", "Kuvaus", "Tyyppi", "EUR"],
                          [[x.date, x.description, k, x.amount_eur] for x, k in zip(st.deposits, kinds)], [3]),
            "Tarkistukset": _t(["Erä", "Laskelma", "IBKR", "Erotus"],
                               [[n, o, i, o - i] for n, o, i, _ in b.checks], [1, 2, 3]),
            "Lähdeverot": _t(["Maa", "Tulolaji", "Brutto", "Lähdevero", "Hyvitys", "Palautettava"],
                             [[w["country"], w["type"], w["gross"], w["wht"], w["credit"], w["reclaim"]]
                              for w in b.wht_rows], [2, 3, 4, 5]),
        },
        "notes": [f"Siirrot: talletukset {_fi(v['deposits_in'])} € · nostot {_fi(v['withdrawals'])} € · netto "
                  f"{_fi(v['net_deposits'])} € (perutut parit nettoutuvat nollaan).",
                  f"IBKR R&U Forex (ei kirjata): {_fi(v['ru_forex_realized'] + v['ru_forex_unrealized'])} € · "
                  f"provisiot (sisältyvät hankintamenoihin): {_fi(v['commissions'])} €"],
    }
    if not b.checks:
        res["notes"].append("Ei Change in NAV -osiota (Realized Summary). Activity Statement CSV antaa IBKR-tarkistukset.")
    return res, write_workbook(b)


# ------------------------------------------------------------------ personal
def personal(st: Statement, s: PSettings) -> tuple[dict, bytes]:
    pb: PBooks = build_personal(st, s)
    v = pb.v
    groups: dict[str, list] = defaultdict(list)
    for sec, fld, val, note in omavero_fields(pb):
        groups[sec].append([fld, val, note])
    agg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for m in pb.matches:
        a = agg[m.symbol]
        a[0] += m.proceeds
        a[1] += m.proceeds - m.result      # deduction used (actual costs or olettama)
        a[2 if m.result > 0 else 3] += m.result
    warnings = list(pb.warnings)
    if v["small_exempt"]:
        warnings.insert(0, "Pienten luovutusten verovapaus: luovutushinnat yhteensä ≤ 1 000 € → arvopapereiden voitot verovapaita.")
    res = {
        "mode": "personal",
        "heading": f"{s.name or st.name} · {st.account} · {st.period_start} – {st.period_end} · henkilöverotus",
        "caption": f"Lähteet: {', '.join(st.source_files)} · FIFO-osumia {_fi(len(pb.matches), 0)}",
        "metrics": [
            ["Luovutusvoitot", v["sec_gains"] + v["der_gains"] + v["fx_gains"] + v["crypto_gains"]],
            ["Luovutustappiot", v["sec_losses"] + v["der_losses"] + v["fx_losses"] + v["crypto_losses"]],
            ["Pääomatulo (IBKR)", v["capital_income"]], ["Pääomatulovero, arvio", v["tax_net"]],
        ],
        "ok": None, "ok_text": "",
        "preliminary": pb.preliminary,
        "warnings": warnings,
        "download_label": "Lataa Excel (OmaVero-erittely)",
        "filename": f"{(s.name or st.name).replace(' ', '_')}_IBKR_{st.period_end[:4]}_omavero.xlsx",
        "sections": [{"title": k, "table": _t(["Kenttä", "EUR", "Huom."], rows, [1])} for k, rows in groups.items()],
        "sections_title": "Veroilmoitukseen (OmaVero)",
        "sections_caption": "Paljon kauppoja: ilmoita arvopaperikaupat yhteenvetona ja liitä ladattu Excel erittelyksi.",
        "tabs": {
            "Pääomatulolaskelma": _t(["Erä", "EUR"], [
                ["Arvopapereiden voitot − tappiot (FIFO)", 0.0 if v["small_exempt"] else v["sec_net"]],
                ["Johdannaisten voitot − tappiot", v["der_gains"] + v["der_losses"]],
                ["Kryptovarat voitot − tappiot", 0.0 if v["small_exempt"] else v["crypto_gains"] + v["crypto_losses"]],
                ["Valuutat", v["fx_gains"] + v["fx_losses"]],
                ["Osingot × 85 %", v["div_taxable"]], ["Payment in lieu", v["pil_taxable"]],
                ["Korkotulot", v["int_income"]], ["CFD-voitot (muu pääomatulo)", v["cfd_gains"]],
                ["− Korot tulonhankkimisvelasta", -v["int_expense"]],
                ["− Muut tulonhankkimismenot", -v["fees"]], ["− Aiempien vuosien tappiot", -v["cf_used"]],
                ["PÄÄOMATULO", v["capital_income"]], ["Vero (30 % / 34 %)", v["tax_gross"]],
                ["− Ulkomaisen veron hyvitys", -v["tax_credit"]], ["VERO NETTO (arvio)", v["tax_net"]]], [1]),
            "Arvopaperit symboleittain": _t(
                ["Symboli", "Luovutushinnat", "Hankintamenot", "Voitot", "Tappiot", "Netto (FIFO)", "IBKR R&U"],
                [[k, *x, x[2] + x[3], pb.ru_by_symbol.get(k, 0.0)] for k, x in sorted(agg.items())], [1, 2, 3, 4, 5, 6]),
            "Johdannaiset": _t(["Luokka", "Symboli", "Voitot", "Tappiot", "Netto", "Markkinapaikka", "Tappio vähennyskelpoinen"],
                               [[r.asset_class, r.symbol, r.profit, r.loss, r.realized, pb.der_exch.get(r.symbol) or "tuntematon",
                                 "Ei (ei säännelty markkina)" if r.symbol in pb.nondeductible else "Kyllä"]
                                for r in pb.derivatives], [2, 3, 4]),
            "CFD:t": _t(["Päivä", "Symboli", "Tulos", "Käsittely"],
                        [[x["date"], x["symbol"], x["eur"],
                          "Veronalainen (muu pääomatulo)" if x["eur"] > 0 else "Ei huomioida (vähennyskelvoton)"]
                         for x in pb.cfd_rows]
                        + ([["", "Voitot yhteensä", v["cfd_gains"], "Veronalainen"],
                            ["", "Tappiot yhteensä", v["cfd_losses_ignored"], "Ei huomioida"]] if pb.cfd_rows else []),
                        [2]),
            "Lähdeverot": _t(["Maa", "Tulolaji", "Brutto", "Lähdevero", "Hyvitys", "Palautettava"],
                             [[w["country"], w["type"], w["gross"], w["wht"], w["credit"], w["reclaim"]]
                              for w in pb.wht_rows], [2, 3, 4, 5]),
        },
        "notes": ["Arvio IBKR-tilin osuudesta. Lopullinen vero lasketaan OmaVerossa kaikista tuloistasi."]
                 + ([f"Hankintameno-olettama käytetty {int(v['presumption_lots'])} erässä (vähennys todellisia kuluja "
                     f"suurempi {_fi(v['presumption_benefit'])} €)."] if v.get("presumption_lots") else []),
    }
    if not pb.cfd_rows:
        del res["tabs"]["CFD:t"]
    if pb.opening:
        res["tabs"]["Vuoden alun erät"] = _t(
            ["Symboli", "Määrä", "Luovutushinnat", "Hankintamenot", "Tulos", "Käsittely"],
            [[o["symbol"] + (" (short)" if o["short"] else ""), o["qty"], o["proceeds_eur"], o["cost_eur"],
              o["proceeds_eur"] - o["cost_eur"], ", ".join(SOURCES.get(k, k) for k in o["methods"])]
             if o.get("kind") != "option" else
             [o["symbol"] + " (optio)", o["qty"], "–",
              sum(e["premium_eur"] for e in pb.option_events if e["symbol"] == o["symbol"]), "–",
              ", ".join(SOURCES.get(k, k) for k in o["methods"]) + " — preemio"]
             for o in pb.opening], [2, 3, 4])
    if pb.crypto_matches:
        res["tabs"]["Kryptovarat"] = _t(["Symboli", "Myyntipäivä", "Ostopäivä", "Määrä", "Luovutushinta", "Vähennys", "Tulos", "Lähde"],
                                        [[m.symbol, m.sale_date, m.buy_date, m.qty, m.proceeds, m.proceeds - m.result,
                                          m.result, m.source] for m in pb.crypto_matches], [4, 5, 6])
    if pb.ca_events:
        res["tabs"]["Yritystapahtumat"] = _t(
            ["Päivä", "Symboli", "Kerroin", "Määrän muutos", "Käteinen", "Käsittely"],
            [[e["date"], e["symbol"], "–" if e["factor"] is None else round(e["factor"], 4), e["delta"],
              e["proceeds_eur"] if e["proceeds_eur"] is not None else "–", e["handled"]] for e in pb.ca_events], [4])
    if pb.option_events:
        res["tabs"]["Toteutetut optiot"] = _t(
            ["Päivä", "Optio", "Kohde-etuus", "Sopimuksia", "Preemio", "Käsittely"],
            [[e["date"], e["symbol"], e["underlying"], e["contracts"],
              e["premium_eur"] if e["kind"] == "exercise" else "–",
              e.get("target", "") + " · " + ", ".join(SOURCES.get(k, k) for k in e["methods"])]
             for e in pb.option_events], [4])
    # open lots at period end -> JSON the user can import next year as year-start choices
    res["end_lots"] = {"account": st.account, "as_of": st.period_end, "lots": pb.end_lots}
    return res, write_personal_workbook(pb)
