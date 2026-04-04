from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class MarketOutcome(str, Enum):
    YES = "YES"
    NO = "NO"


class TradeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    STOPPED_OUT = "STOPPED_OUT"
    RESOLVED_WIN = "RESOLVED_WIN"
    RESOLVED_LOSS = "RESOLVED_LOSS"


class TradeResultFilter(str, Enum):
    WIN = "win"
    LOSS = "loss"
    ACTIVE = "active"
    ALL = "all"


@dataclass
class Market:
    id: str
    slug: str
    title: str
    yes_price: float
    no_price: float
    liquidity_usdc: float
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class Order:
    id: str
    trade_id: str
    order_type: OrderType
    side: OrderSide
    shares: float
    status: OrderStatus
    created_at: datetime
    time_remaining_min: float | None = None
    filled_at: datetime | None = None
    filled_price: float | None = None
    token_id: str | None = None
    adx: float | None = None
    ema9: float | None = None
    ema21: float | None = None
    atr: float | None = None
    gap: str | None = None


@dataclass
class Trade:
    id: str
    market_id: str
    market_title: str
    strike_price: float
    outcome: MarketOutcome
    status: TradeStatus
    entry_cost_usdc: float
    shares: float
    created_at: datetime
    entry_price: float | None = None
    token_id: str | None = None
    market_resolves_at: datetime | None = None
    resolved_at: datetime | None = None
    total_pnl_usdc: float | None = None
    exit_price: float | None = None
    is_hedged: bool = False
    is_paper: bool = False
    signal_type: str | None = None
    exit_reason: str | None = None
    mcc: str | None = None
    confirmations: str | None = None
    signal_metadata: str | None = None
    entry_cvd_60s: float | None = None
    entry_cvd_session: float | None = None
    take_profit_order_id: str | None = None
    take_profit_price: float | None = None
    entry_gap_usd: float | None = None
    trigger_gap: str | None = None
    trigger_atr: float | None = None
    trigger_ema: float | None = None
