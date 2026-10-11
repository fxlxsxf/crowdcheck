"""Plain data types shared by providers, metrics and renderers.

Every model can round-trip through a JSON-safe dict so the cache and the mock
fixtures use one format. Parsing is tolerant: a missing field becomes None
instead of an exception, and the metrics decide what None means.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

Side = Literal["buy", "sell"]


def parse_ts(value: Any) -> datetime | None:
    """Accept ISO strings, unix seconds or datetimes; always return aware UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts_out(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(frozen=True)
class Holder:
    wallet: str
    amount: float
    share_of_supply: float | None = None   # 0..1

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Holder:
        return cls(wallet=d["wallet"], amount=_float(d.get("amount")) or 0.0,
                   share_of_supply=_float(d.get("share_of_supply")))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Trade:
    wallet: str
    mint: str
    side: Side
    ts: datetime | None
    token_amount: float
    price: float | None = None       # quote units per token
    quote: str | None = None         # "SOL" or "USD"
    signature: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trade:
        return cls(wallet=d["wallet"], mint=d["mint"], side=d["side"], ts=parse_ts(d.get("ts")),
                   token_amount=_float(d.get("token_amount")) or 0.0, price=_float(d.get("price")),
                   quote=d.get("quote"), signature=d.get("signature"))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ts": _ts_out(self.ts)}


@dataclass(frozen=True)
class Holding:
    mint: str
    amount: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Holding:
        return cls(mint=d["mint"], amount=_float(d.get("amount")) or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MintMeta:
    mint: str
    symbol: str | None = None
    creator: str | None = None
    first_trade_ts: datetime | None = None
    last_trade_ts: datetime | None = None
    first_price: float | None = None
    last_price: float | None = None
    price_low: float | None = None
    price_high: float | None = None
    quote: str | None = None
    trade_count: int | None = None
    # False when the provider stopped paging before reaching the first trade, in
    # which case first_trade_ts is the oldest trade seen, not the real first one.
    history_complete: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MintMeta:
        tc = d.get("trade_count")
        return cls(
            mint=d["mint"], symbol=d.get("symbol"), creator=d.get("creator"),
            first_trade_ts=parse_ts(d.get("first_trade_ts")), last_trade_ts=parse_ts(d.get("last_trade_ts")),
            first_price=_float(d.get("first_price")), last_price=_float(d.get("last_price")),
            price_low=_float(d.get("price_low")), price_high=_float(d.get("price_high")),
            quote=d.get("quote"), trade_count=int(tc) if tc is not None else None,
            history_complete=bool(d.get("history_complete", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "first_trade_ts": _ts_out(self.first_trade_ts),
                "last_trade_ts": _ts_out(self.last_trade_ts)}


@dataclass(frozen=True)
class Position:
    """One wallet's round trip in one mint, built from its trades."""
    wallet: str
    mint: str
    first_buy_ts: datetime | None
    last_sell_ts: datetime | None
    bought: float
    sold: float
    avg_sell_price: float | None     # volume weighted over sells that carry a price
    quote: str | None
    closed: bool

    @property
    def duration_seconds(self) -> float | None:
        if not self.closed or self.first_buy_ts is None or self.last_sell_ts is None:
            return None
        return (self.last_sell_ts - self.first_buy_ts).total_seconds()


@dataclass
class FundingGraph:
    creator: str
    funder: str | None
    wallets: list[str]                 # every wallet visited, creator first
    linked_mints: list[str]            # mints created by any visited wallet, target excluded
    truncated: bool = False            # hit FUNDING_GRAPH_MAX_WALLETS


class MetricName(str, Enum):
    TRACK_RECORD = "track_record"
    WALLET_AGE = "wallet_age"
    DEPLOYER = "deployer"
    OVERLAP = "overlap"
    HOLD_TIME = "hold_time"
    EXIT_PERCENTILE = "exit_percentile"


METRIC_LABELS: dict[MetricName, str] = {
    MetricName.TRACK_RECORD: "Crowd track record",
    MetricName.WALLET_AGE: "Wallet age",
    MetricName.DEPLOYER: "Deployer history",
    MetricName.OVERLAP: "Overlap",
    MetricName.HOLD_TIME: "Hold time",
    MetricName.EXIT_PERCENTILE: "Exit percentile",
}


@dataclass
class MetricResult:
    name: MetricName
    status: Literal["ok", "not_visible"]
    display: str
    raw: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    coverage: str | None = None

    @property
    def visible(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name.value, "status": self.status, "display": self.display,
                "raw": self.raw, "reason": self.reason, "coverage": self.coverage}


@dataclass
class Contribution:
    weight: int
    subscore: float | None       # 0..1, None when the metric is not visible
    points: float | None         # weight * subscore


@dataclass
class ScoreResult:
    total: float | None
    contributions: dict[MetricName, Contribution]
    visible_weight: int
    too_thin: bool

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "visible_weight": self.visible_weight, "too_thin": self.too_thin,
                "contributions": {k.value: asdict(v) for k, v in self.contributions.items()}}


@dataclass
class Report:
    mint: str
    symbol: str | None
    top_n: int
    holders_found: int
    results: list[MetricResult]
    score: ScoreResult
    verdict: str
    closing_line: str
    generated_at: datetime
    notes: list[str] = field(default_factory=list)

    def result(self, name: MetricName) -> MetricResult | None:
        return next((r for r in self.results if r.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {"mint": self.mint, "symbol": self.symbol, "top_n": self.top_n,
                "holders_found": self.holders_found, "results": [r.to_dict() for r in self.results],
                "score": self.score.to_dict(), "verdict": self.verdict, "closing_line": self.closing_line,
                "generated_at": self.generated_at.isoformat(), "notes": self.notes}
