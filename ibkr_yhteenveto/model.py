"""Normalized statement model. All *_eur fields are in the account base currency (EUR)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Optional

from .num import ZERO


@dataclass
class CashLine:
    date: str
    currency: str
    description: str
    amount: Decimal            # in `currency`
    amount_eur: Decimal = ZERO  # converted (group EUR total / group ccy total)


@dataclass
class RURow:
    """Realized & Unrealized Performance Summary row (EUR)."""
    asset_class: str
    symbol: str
    st_profit: Decimal = ZERO
    st_loss: Decimal = ZERO
    lt_profit: Decimal = ZERO
    lt_loss: Decimal = ZERO
    unrl_profit: Decimal = ZERO  # S/T + L/T unrealized profit
    unrl_loss: Decimal = ZERO    # S/T + L/T unrealized loss (negative)

    @property
    def profit(self) -> Decimal:
        return self.st_profit + self.lt_profit

    @property
    def loss(self) -> Decimal:
        return self.st_loss + self.lt_loss

    @property
    def realized(self) -> Decimal:
        return self.profit + self.loss

    @property
    def unrealized(self) -> Decimal:
        return self.unrl_profit + self.unrl_loss


@dataclass
class Position:
    asset_class: str
    currency: str
    symbol: str
    quantity: Decimal
    mult: Decimal
    cost_price: Decimal
    cost_basis: Decimal    # in currency
    close_price: Decimal
    value: Decimal         # in currency
    unrealized: Decimal    # in currency
    cost_basis_eur: Decimal = ZERO
    value_eur: Decimal = ZERO
    unrealized_eur: Decimal = ZERO


@dataclass
class ForexBalance:
    currency: str
    quantity: Decimal
    cost_basis_eur: Decimal
    value_eur: Decimal
    unrealized_eur: Decimal


@dataclass
class NavRow:
    label: str
    start_total: Decimal
    end_long: Decimal
    end_short: Decimal
    end_total: Decimal


@dataclass
class Statement:
    source_files: list[str] = field(default_factory=list)
    title: str = ""
    name: str = ""
    account: str = ""
    base_currency: str = "EUR"
    customer_type: str = ""   # IBKR: Individual / Corporate / Joint ...
    period_start: str = ""
    period_end: str = ""

    nav: dict[str, NavRow] = field(default_factory=dict)
    change_in_nav: dict[str, Decimal] = field(default_factory=dict)  # only in full Activity Statements
    ru: list[RURow] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    forex_balances: list[ForexBalance] = field(default_factory=list)

    commissions_eur: Optional[Decimal] = None        # sum of Comm/Fee over all trades (negative)
    commissions_by_class: dict[str, Decimal] = field(default_factory=dict)
    transaction_fees_eur: Optional[Decimal] = None   # e.g. French/Italian FTT (negative)
    transaction_fee_lines: list[CashLine] = field(default_factory=list)

    interest: list[CashLine] = field(default_factory=list)
    interest_total_eur: Optional[Decimal] = None
    fees: list[CashLine] = field(default_factory=list)
    fees_total_eur: Optional[Decimal] = None
    withholding: list[CashLine] = field(default_factory=list)
    withholding_total_eur: Optional[Decimal] = None
    dividends: list[CashLine] = field(default_factory=list)
    dividends_total_eur: Optional[Decimal] = None
    deposits: list[CashLine] = field(default_factory=list)
    deposits_total_eur: Optional[Decimal] = None

    # stock trade legs with exact EUR value (Forex P/L Details for non-base trades, Trades for base-ccy trades)
    # each: {"date","symbol","qty","ccy","eur","exact"} — qty < 0 = sale
    stock_legs: list[dict] = field(default_factory=list)
    # realized P/L per closing CFD trade (CSV Trades): {"date","symbol","cls","ccy","pl","eur"} — eur None = unconverted
    cfd_trades: list[dict] = field(default_factory=list)
    # ECB reference rates {date: {ccy: units per EUR}} from a user-supplied eurofxref-hist.csv (trimmed to need)
    ecb_rates: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    # listing exchange per symbol (CSV Financial Instrument Information 'Listing Exch')
    listing_exch: dict[str, str] = field(default_factory=dict)
    # crypto trade legs (CSV Trades, Crypto class) — same shape as stock_legs
    crypto_legs: list[dict] = field(default_factory=list)
    # corporate actions on shares (CSV): {"date","symbol","description","qty","proceeds_eur","ccy"}
    corporate_actions: list[dict] = field(default_factory=list)
    # CSV stock order rows {"date","time","symbol","qty","comm","ccy"} — to give PDF lots their share of the commission
    trade_rows: list[dict] = field(default_factory=list)
    # option trades (CSV Trades, option classes): {"date","symbol","underlying","right","mult","qty","ccy","code","eur"}
    # eur = premium cash net of commission (paid for buys, received for sells); None = unconverted
    option_trades: list[dict] = field(default_factory=list)
    # stock rows created by exercise/assignment (CSV, code Ex/A): {"date","symbol","qty","basis","cash","ccy","code"}
    exercise_rows: list[dict] = field(default_factory=list)
    # stock legs from statements of EARLIER periods of the same account (lot history for year-start positions)
    history_legs: list[dict] = field(default_factory=list)
    history_periods: list[str] = field(default_factory=list)   # "YYYY-MM-DD – YYYY-MM-DD" per earlier period
    etf_symbols: set[str] = field(default_factory=set)  # from Financial Instrument Information (CSV)
    warnings: list[str] = field(default_factory=list)

    # ---- helpers -------------------------------------------------------
    def nav_total(self, label: str, when: str = "end") -> Decimal:
        r = self.nav.get(label)
        if not r:
            return ZERO
        return r.start_total if when == "start" else r.end_total

    @property
    def nav_start(self) -> Decimal:
        return self.nav_total("Total", "start")

    @property
    def nav_end(self) -> Decimal:
        return self.nav_total("Total", "end")

    def normalize(self) -> "Statement":
        """Every float in the statement → exact Decimal (shortest repr). Engines call this first, so a statement
        built in code or loaded from old JSON can never mix binary floats into the money arithmetic."""
        from .num import decimalize
        return decimalize(self)

    # ---- JSON round-trip (the web UI keeps the parsed statement in the browser, not on the server)
    def to_dict(self) -> dict:
        d = asdict(self)
        d["etf_symbols"] = sorted(self.etf_symbols)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Statement":
        d = dict(d)
        lines = ("transaction_fee_lines", "interest", "fees", "withholding", "dividends", "deposits")
        st = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        st.nav = {k: NavRow(**v) for k, v in d.get("nav", {}).items()}
        st.ru = [RURow(**r) for r in d.get("ru", [])]
        st.positions = [Position(**r) for r in d.get("positions", [])]
        st.forex_balances = [ForexBalance(**r) for r in d.get("forex_balances", [])]
        for f in lines:
            setattr(st, f, [CashLine(**r) for r in d.get(f, [])])
        st.stock_legs = [dict(x) for x in d.get("stock_legs", [])]
        st.cfd_trades = [dict(x) for x in d.get("cfd_trades", [])]
        st.history_legs = [dict(x) for x in d.get("history_legs", [])]
        st.option_trades = [dict(x) for x in d.get("option_trades", [])]
        st.trade_rows = [dict(x) for x in d.get("trade_rows", [])]
        st.corporate_actions = [dict(x) for x in d.get("corporate_actions", [])]
        st.listing_exch = dict(d.get("listing_exch", {}))
        st.crypto_legs = [dict(x) for x in d.get("crypto_legs", [])]
        st.ecb_rates = {k: dict(v) for k, v in d.get("ecb_rates", {}).items()}
        st.exercise_rows = [dict(x) for x in d.get("exercise_rows", [])]
        st.history_periods = list(d.get("history_periods", []))
        st.etf_symbols = set(d.get("etf_symbols", []))
        st.source_files, st.warnings = list(st.source_files), list(st.warnings)
        st.change_in_nav, st.commissions_by_class = dict(st.change_in_nav), dict(st.commissions_by_class)
        return st

    def merge(self, other: "Statement") -> None:
        """Fill gaps in self from another statement of the same account/period."""
        self.source_files += other.source_files
        for f in ("title", "name", "account", "period_start", "period_end", "customer_type"):
            if not getattr(self, f):
                setattr(self, f, getattr(other, f))
        for f in ("nav", "change_in_nav"):
            d = getattr(self, f)
            for k, v in getattr(other, f).items():
                d.setdefault(k, v)
        for f in ("ru", "positions", "forex_balances", "interest", "fees", "withholding",
                  "dividends", "deposits", "transaction_fee_lines", "stock_legs", "cfd_trades",
                  "option_trades", "exercise_rows", "trade_rows", "corporate_actions", "crypto_legs"):
            if not getattr(self, f) and getattr(other, f):
                setattr(self, f, getattr(other, f))
        # exact per-trade EUR legs (PDF Forex P/L Details) beat CSV legs converted at an average rate
        if other.stock_legs and all(x.get("exact") for x in other.stock_legs) and \
                any(not x.get("exact", True) for x in self.stock_legs):
            self.stock_legs = other.stock_legs
        for f in ("commissions_eur", "transaction_fees_eur", "interest_total_eur", "fees_total_eur",
                  "withholding_total_eur", "dividends_total_eur", "deposits_total_eur"):
            if getattr(self, f) is None and getattr(other, f) is not None:
                setattr(self, f, getattr(other, f))
        for k, x in other.listing_exch.items():
            self.listing_exch.setdefault(k, x)
        if not self.commissions_by_class:
            self.commissions_by_class = other.commissions_by_class
        self.etf_symbols |= other.etf_symbols
        self.warnings += other.warnings
