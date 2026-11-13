"""62N-87: written (sold) options — decisions OPT-H1, H4–H8 (personal) and OPT-Y2 (company) in docs/PAATOSREKISTERI.md.
Synthetic data in IBKR's documented format (codes O / C / A / Ep; closing rows carry the opening trade's basis)."""
import pytest

from ibkr_yhteenveto import Settings, build, load
from ibkr_yhteenveto.personal import PSettings, build_personal
from test_options import FII, OPT, STK, csv, t

C = "AAA 17JUN26 100 C"
POS = ("Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,"
       "Close Price,Value,Unrealized P/L,Code\n")
RU = ("Realized & Unrealized Performance Summary,Header,Asset Category,Symbol,Cost Adj.,Realized S/T Profit,"
      "Realized S/T Loss,Realized L/T Profit,Realized L/T Loss,Realized Total,Unrealized S/T Profit,"
      "Unrealized S/T Loss,Unrealized L/T Profit,Unrealized L/T Loss,Unrealized Total,Total,Code\n")


def ru(sym, realized):
    p, l = (realized, 0) if realized >= 0 else (0, realized)
    return f"Realized & Unrealized Performance Summary,Data,{OPT},{sym},0,{p},{l},0,0,{realized},0,0,0,0,0,{realized},\n"


def personal(data, **kw):
    return build_personal(load([("s.csv", data)]), PSettings(**kw))


def test_open_at_year_end_premium_taxed_now():                      # OPT-H1
    data = csv(t(OPT, C, "2026-03-02", -1, 3, 300, 0, -300, "O")
               + POS + f"Open Positions,Data,Summary,{OPT},EUR,{C},-1,100,3,-300,1,-100,200,\n")
    pb = personal(data)
    assert pb.v["wopt_open_premium"] == 300 and pb.v["der_gains"] == 300
    assert pb.wopt_rows[0]["rule"] == "OPT-H1"


def test_same_year_buyback_and_expiry_use_olettama():                # OPT-H7 / OPT-H8
    bought_back = csv(t(OPT, C, "2026-03-02", -1, 3, 300, 0, -300, "O")
                      + t(OPT, C, "2026-05-04", 1, 0.5, -50, 0, 300, "C") + RU + ru(C, 250))
    pb = personal(bought_back)
    assert pb.v["der_gains"] == pytest.approx(240)                   # 0.8 × 300 instead of 300 − 50
    assert personal(bought_back, use_presumption=False).v["der_gains"] == 250
    expired = csv(t(OPT, C, "2026-03-02", -1, 3, 300, 0, -300, "O")
                  + t(OPT, C, "2026-06-17", 1, 0, 0, 0, 300, "C;Ep") + RU + ru(C, 300))
    assert personal(expired).v["der_gains"] == pytest.approx(240)


def test_written_last_year_bought_back_now():                        # OPT-H6
    data = csv(t(OPT, C, "2026-04-01", 1, 1.2, -120, 0, 300, "C") + RU + ru(C, 180))
    pb = personal(data)
    assert pb.v["wopt_prior_premium"] == pytest.approx(300)
    assert pb.v["der_gains"] + pb.v["der_losses"] == pytest.approx(-120)   # only the buyback cost remains, as a loss
    assert not pb.preliminary


def test_written_last_year_off_regulated_market_only_gain_removed():  # OPT-H6 + OPT-H11
    fii = FII.replace(f"{C},{C},1,AAA,CBOE", f"{C},{C},1,AAA,OFFSHORE")
    data = (csv(t(OPT, C, "2026-04-01", 1, 1.2, -120, 0, 300, "C") + RU + ru(C, 180), fii=fii))
    pb = personal(data)
    assert pb.v["der_gains"] + pb.v["der_losses"] == pytest.approx(0)       # loss would be non-deductible


def test_assignment_written_last_year_not_adjusted():                # OPT-H5, option A
    data = csv(t(STK, "AAA", "2026-01-05", 100, 90, -9000, 0, 9000, "O")
               + t(OPT, C, "2026-06-17", 1, 0, 0, 0, 300, "C;A")
               + t(STK, "AAA", "2026-06-17", -100, 100, 10000, 0, -9000, "C;A"))
    pb = personal(data, use_presumption=False)
    assert pb.matches[0].proceeds == 10000 and "OPT-H5" in pb.option_events[0]["target"]
    assert any("OPT-H5" in w for w in pb.warnings)


def test_same_year_put_assignment_lowers_share_cost():               # OPT-H4
    P = "BBB 17JUN26 95 P"
    data = csv(t(OPT, P, "2026-02-02", -1, 2, 200, 0, -200, "O")
               + t(OPT, P, "2026-06-17", 1, 0, 0, 0, 200, "C;A")
               + t(STK, "BBB", "2026-06-17", 100, 95, -9500, 0, 9300, "O;A")
               + t(STK, "BBB", "2026-08-03", -100, 100, 10000, 0, -9300, "C"))
    (m,) = personal(data, use_presumption=False).matches
    assert (m.cost, m.result) == (9300, 700)


def test_company_long_dated_written_option_taxed_when_written():     # OPT-Y2 / OPT-Y5
    L = "AAA 16JUN28 100 C"
    fii = FII + (f"Financial Instrument Information,Data,{OPT},{L},{L},3,AAA,CBOE,100,2028-06-16,2028-06,C,100,\n")
    data = csv(t(OPT, L, "2026-02-02", -1, 9, 900, 0, -900, "O") + t(OPT, C, "2026-02-02", -1, 3, 300, 0, -300, "O")
               + POS + f"Open Positions,Data,Summary,{OPT},EUR,{L},-1,100,9,-900,9,-900,0,\n"
               + f"Open Positions,Data,Summary,{OPT},EUR,{C},-1,100,3,-300,3,-300,0,\n", fii=fii)
    st = load([("s.csv", data)])
    v = build(st, Settings()).v
    assert v["evl_add_wopt"] == 900                    # > 18 months: taxed now; the 4-month option follows the books
    v2 = build(st, Settings(wopt_premium_carry=500)).v
    assert v2["taxable"] - v["taxable"] == pytest.approx(-500)
