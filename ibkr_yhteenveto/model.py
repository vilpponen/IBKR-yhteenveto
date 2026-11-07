"""Normalized statement model. All *_eur fields are in the account base currency (EUR)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class CashLine:
    date: str
    currency: str
    description: str
    amount: float            # in `currency`
    amount_eur: float = 0.0  # converted (group EUR total / group ccy total)


@dataclass
class RURow:
    """Realized & Unrealized Performance Summary row (EUR)."""
    asset_class: str
    symbol: str
    st_profit: float = 0.0
    st_loss: float = 0.0
    lt_profit: float = 0.0
    lt_loss: float = 0.0
    unrl_profit: float = 0.0  # S/T + L/T unrealized profit
    unrl_loss: float = 0.0    # S/T + L/T unrealized loss (negative)

    @property
    def profit(self) -> float:
        return self.st_profit + self.lt_profit

    @property
    def loss(self) -> float:
        return self.st_loss + self.lt_loss

    @property
    def realized(self) -> float:
        return self.profit + self.loss

    @property
    def unrealized(self) -> float:
        return self.unrl_profit + self.unrl_loss


@dataclass
class Position:
    asset_class: str
    currency: str
    symbol: str
    quantity: float
    mult: float
    cost_price: float
    cost_basis: float    # in currency
    close_price: float
    value: float         # in currency
    unrealized: float    # in currency
    cost_basis_eur: float = 0.0
    value_eur: float = 0.0
    unrealized_eur: float = 0.0


@dataclass
class ForexBalance:
    currency: str
    quantity: float
    cost_basis_eur: float
    value_eur: float
    unrealized_eur: float


@dataclass
class NavRow:
    label: str
    start_total: float
    end_long: float
    end_short: float
    end_total: float


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
    change_in_nav: dict[str, float] = field(default_factory=dict)  # only in full Activity Statements
    ru: list[RURow] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    forex_balances: list[ForexBalance] = field(default_factory=list)

    commissions_eur: Optional[float] = None        # sum of Comm/Fee over all trades (negative)
    commissions_by_class: dict[str, float] = field(default_factory=dict)
    transaction_fees_eur: Optional[float] = None   # e.g. French/Italian FTT (negative)
    transaction_fee_lines: list[CashLine] = field(default_factory=list)

    interest: list[CashLine] = field(default_factory=list)
    interest_total_eur: Optional[float] = None
    fees: list[CashLine] = field(default_factory=list)
    fees_total_eur: Optional[float] = None
    withholding: list[CashLine] = field(default_factory=list)
    withholding_total_eur: Optional[float] = None
    dividends: list[CashLine] = field(default_factory=list)
    dividends_total_eur: Optional[float] = None
    deposits: list[CashLine] = field(default_factory=list)
    deposits_total_eur: Optional[float] = None

    # stock trade legs with exact EUR value (Forex P/L Details for non-base trades, Trades for base-ccy trades)
    # each: {"date","symbol","qty","ccy","eur","exact"} — qty < 0 = sale
    stock_legs: list[dict] = field(default_factory=list)
    etf_symbols: set[str] = field(default_factory=set)  # from Financial Instrument Information (CSV)
    warnings: list[str] = field(default_factory=list)

    # ---- helpers -------------------------------------------------------
    def nav_total(self, label: str, when: str = "end") -> float:
        r = self.nav.get(label)
        if not r:
            return 0.0
        return r.start_total if when == "start" else r.end_total

    @property
    def nav_start(self) -> float:
        return self.nav_total("Total", "start")

    @property
    def nav_end(self) -> float:
        return self.nav_total("Total", "end")

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
                  "dividends", "deposits", "transaction_fee_lines", "stock_legs"):
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
        if not self.commissions_by_class:
            self.commissions_by_class = other.commissions_by_class
        self.etf_symbols |= other.etf_symbols
        self.warnings += other.warnings
