"""62N-94: optional ECB reference rates (user-supplied eurofxref-hist.csv; no network, nothing stored)."""
import pytest

from ibkr_yhteenveto import load
from ibkr_yhteenveto.fx_ecb import settle_date
from ibkr_yhteenveto.personal import PSettings, build_personal
from test_options import HEAD, FII, t

STK = "Stocks"
USD = (HEAD + t(STK, "AAA", "2026-03-04", 10, 100, -1000, -1, 1001, "O", ccy="USD")
       + t(STK, "AAA", "2026-03-09", -10, 110, 1100, -1, -1001, "C", ccy="USD")
       + "Trades,Total,,Stocks,USD,,,,,,100,-2,0,98,0,\n"
       + "Trades,Total,,Stocks,EUR,,,,,,90,-1.8,0,88.2,0,\n" + FII).encode()
ECB = b"Date,USD,JPY,\n2026-03-10,1.0,160,\n2026-03-06,1.20,159,\n2026-03-05,1.25,158,\n2026-03-04,1.3,157,\n"


def test_settlement_dates():
    assert settle_date("2026-03-04", "USD") == "2026-03-05"     # T+1 (US)
    assert settle_date("2026-03-06", "USD") == "2026-03-09"     # Friday → Monday
    assert settle_date("2026-03-04", "SEK") == "2026-03-06"     # T+2
    assert settle_date("2024-05-01", "USD") == "2024-05-03"     # T+2 before 28 May 2024


def test_ecb_mode_converts_at_settlement_rate_and_shows_difference():
    st = load([("s.csv", USD), ("eurofxref-hist.csv", ECB)])
    assert st.ecb_rates and set(next(iter(st.ecb_rates.values()))) == {"USD"}     # trimmed to what is needed
    ibkr = build_personal(st, PSettings(use_presumption=False))
    ecb = build_personal(st, PSettings(use_presumption=False, fx_mode="ecb"))
    assert ibkr.v["sec_net"] == pytest.approx(88.2)               # IBKR: 0.9 EUR/USD on both legs
    # ECB: buy settles 5.3. (1001 USD / 1.25), sale settles 10.3. (1099 USD / 1.0)
    (m,) = ecb.matches
    assert m.proceeds == pytest.approx(1100) and m.cost == pytest.approx(1001 / 1.25 + 1)
    assert ecb.v["fx_alt_sec_net"] == pytest.approx(88.2)
    assert ecb.warnings[0].startswith("Valuuttakurssit: EKP:n viitekurssi")


def test_ecb_mode_without_file_falls_back():
    pb = build_personal(load([("s.csv", USD)]), PSettings(fx_mode="ecb", use_presumption=False))
    assert pb.v["sec_net"] == pytest.approx(88.2) and any("eurofxref-hist.csv" in w for w in pb.warnings)


def test_ecb_file_alone_is_rejected():
    with pytest.raises(ValueError):
        load([("eurofxref-hist.csv", ECB)])
