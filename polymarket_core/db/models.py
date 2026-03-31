from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, String, Boolean, Index, Text, Enum
)
from sqlalchemy.sql import func

from polymarket_core.db.database import Base
from polymarket_core.core.models import OrderStatus, OrderType, TradeStatus


class MarketModel(Base):
    __tablename__ = "markets"

    id = Column(String, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    yes_price = Column(Float, nullable=False)
    no_price = Column(Float, nullable=False)
    liquidity_usdc = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_markets_active_liquidity", "is_active", "liquidity_usdc"),
    )


class TradeModel(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True, index=True)
    market_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=True)
    market_title = Column(String, nullable=False)
    strike_price = Column(Float, nullable=False, default=0.0)
    outcome = Column(String, nullable=False)
    status = Column(Enum(TradeStatus), nullable=False, default=TradeStatus.ACTIVE)
    entry_cost_usdc = Column(Float, nullable=False)
    shares = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    market_resolves_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    total_pnl_usdc = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    is_hedged = Column(Boolean, default=False)
    is_paper = Column(Boolean, default=False, index=True)
    signal_type = Column(String, nullable=True)
    exit_reason: Column = Column(String, nullable=True)
    mcc = Column(String, nullable=True)
    confirmations = Column(String, nullable=True)
    signal_metadata = Column(Text, nullable=True)
    entry_cvd_60s = Column(Float, nullable=True)
    entry_cvd_session = Column(Float, nullable=True)


    __table_args__ = (
        Index("ix_trades_market_status", "market_id", "status"),
    )


class OrderModel(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, index=True)
    trade_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=True)
    order_type = Column(Enum(OrderType), nullable=False)
    side = Column(String, nullable=False)
    shares = Column(Float, nullable=False)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.PENDING)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    time_remaining_min = Column(Float, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    filled_price = Column(Float, nullable=True)
