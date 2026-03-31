from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from polymarket_core.core.models import Trade, TradeStatus, MarketOutcome
from polymarket_core.db.models import TradeModel


class TradeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, trade: Trade) -> None:
        db_trade = self._session.query(TradeModel).filter(
            TradeModel.id == trade.id
        ).first()
        if not db_trade:
            db_trade = TradeModel(id=trade.id)
            self._session.add(db_trade)

        db_trade.market_id = trade.market_id
        db_trade.token_id = trade.token_id
        db_trade.market_title = trade.market_title
        db_trade.strike_price = trade.strike_price
        db_trade.outcome = trade.outcome.value if trade.outcome else None
        db_trade.status = trade.status
        db_trade.entry_cost_usdc = float(trade.entry_cost_usdc) if trade.entry_cost_usdc is not None else 0.0
        db_trade.shares = float(trade.shares)
        db_trade.entry_price = float(trade.entry_price) if trade.entry_price is not None else None
        db_trade.created_at = trade.created_at
        db_trade.market_resolves_at = trade.market_resolves_at
        db_trade.resolved_at = trade.resolved_at
        db_trade.total_pnl_usdc = float(trade.total_pnl_usdc) if trade.total_pnl_usdc is not None else None
        db_trade.exit_price = float(trade.exit_price) if trade.exit_price is not None else None
        db_trade.is_hedged = bool(trade.is_hedged)
        db_trade.is_paper = bool(trade.is_paper)
        db_trade.signal_type = trade.signal_type
        db_trade.exit_reason = trade.exit_reason
        db_trade.mcc = trade.mcc
        db_trade.confirmations = trade.confirmations
        db_trade.signal_metadata = trade.signal_metadata

        self._session.commit()

    def get_active(self) -> list[Trade]:
        db_trades = self._session.query(TradeModel).filter(
            TradeModel.status == TradeStatus.ACTIVE
        ).all()
        return [self._to_domain(t) for t in db_trades]

    def get_by_id(self, trade_id: str) -> Trade | None:
        db_trade = self._session.query(TradeModel).filter(
            TradeModel.id == trade_id
        ).first()
        if not db_trade:
            return None
        return self._to_domain(db_trade)

    def get_all(self, limit: int = 100) -> list[Trade]:
        db_trades = self._session.query(TradeModel).order_by(
            TradeModel.created_at.desc()
        ).limit(limit).all()
        return [self._to_domain(t) for t in db_trades]

    def get_by_status(self, status: TradeStatus) -> list[Trade]:
        db_trades = self._session.query(TradeModel).filter(
            TradeModel.status == status
        ).all()
        return [self._to_domain(t) for t in db_trades]

    def get_total_active_cost(self) -> float:
        result = self._session.query(func.sum(TradeModel.entry_cost_usdc)).filter(
            TradeModel.status == TradeStatus.ACTIVE
        ).scalar()
        return float(result or 0.0)

    def get_by_date_range(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100
    ) -> list[Trade]:
        query = self._session.query(TradeModel)
        if start_date:
            query = query.filter(TradeModel.created_at >= start_date)
        if end_date:
            query = query.filter(TradeModel.created_at <= end_date)
        db_trades = query.order_by(TradeModel.created_at.desc()).limit(limit).all()
        return [self._to_domain(t) for t in db_trades]

    def get_by_market_id(self, market_id: str) -> Trade | None:
        db_trade = self._session.query(TradeModel).filter(
            TradeModel.market_id == market_id,
            TradeModel.status == TradeStatus.ACTIVE
        ).first()
        if not db_trade:
            return None
        return self._to_domain(db_trade)

    def exists_for_market(self, market_id: str, is_paper: bool = False) -> bool:
        return self._session.query(TradeModel).filter(
            TradeModel.market_id == market_id,
            TradeModel.is_paper == is_paper
        ).first() is not None

    def update_exit(
        self,
        trade_id: str,
        exit_price: float,
        total_pnl_usdc: float,
        status: TradeStatus,
        exit_reason: str | None = None,
        **kwargs
    ) -> None:
        db_trade = self._session.query(TradeModel).filter(
            TradeModel.id == trade_id
        ).first()
        if db_trade:
            db_trade.exit_price = exit_price
            db_trade.total_pnl_usdc = total_pnl_usdc
            db_trade.status = status
            db_trade.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if exit_reason:
                db_trade.exit_reason = exit_reason
            self._session.commit()

    def update_resolved(
        self,
        trade_id: str,
        status: TradeStatus,
        total_pnl_usdc: float,
        exit_price: float,
        **kwargs
    ) -> None:
        db_trade = self._session.query(TradeModel).filter(
            TradeModel.id == trade_id
        ).first()
        if db_trade:
            db_trade.status = status
            db_trade.total_pnl_usdc = total_pnl_usdc
            db_trade.exit_price = exit_price
            db_trade.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            self._session.commit()

    def get_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None
    ) -> dict:
        query = self._session.query(TradeModel)
        if start_date:
            query = query.filter(TradeModel.created_at >= start_date)
        if end_date:
            query = query.filter(TradeModel.created_at <= end_date)

        all_trades = query.all()

        def calc_group_stats(trades):
            executed = [
                t for t in trades 
                if t.status not in (TradeStatus.CANCELLED, )
            ]
            
            resolved = [
                t for t in executed
                if t.status in (TradeStatus.RESOLVED_WIN, TradeStatus.RESOLVED_LOSS, TradeStatus.STOPPED_OUT)
            ]
            wins = [t for t in resolved if t.status == TradeStatus.RESOLVED_WIN]
            losses = [t for t in resolved if t.status == TradeStatus.RESOLVED_LOSS]
            stopped = [t for t in resolved if t.status == TradeStatus.STOPPED_OUT]

            total_pnl = sum(
                t.total_pnl_usdc for t in executed if t.total_pnl_usdc is not None
            )
            win_rate = (len(wins) / len(resolved) * 100) if resolved else 0.0
            pnls = [t.total_pnl_usdc for t in resolved if t.total_pnl_usdc is not None]
            win_pnls = [p for p in pnls if p > 0]
            loss_pnls = [p for p in pnls if p < 0]

            return {
                "total_trades": len(executed),
                "wins": len(wins),
                "losses": len(losses),
                "stopped_out": len(stopped),
                "active_trades": len([t for t in executed if t.status == TradeStatus.ACTIVE]),
                "total_pnl_usdc": total_pnl,
                "win_rate": win_rate,
                "largest_win_usdc": max(win_pnls) if win_pnls else 0.0,
                "largest_loss_usdc": min(loss_pnls) if loss_pnls else 0.0,
            }

        momentum_trades = [t for t in all_trades if t.signal_type and ("momentum" in t.signal_type.lower() or "IMB" in t.signal_type)]

        base_stats = calc_group_stats(all_trades)
        base_stats["momentum"] = calc_group_stats(momentum_trades)

        return base_stats

    def _to_domain(self, db_trade: TradeModel) -> Trade:
        return Trade(
            id=str(db_trade.id),
            market_id=str(db_trade.market_id),
            token_id=db_trade.token_id,
            market_title=str(db_trade.market_title or ""),
            strike_price=float(db_trade.strike_price or 0.0),
            outcome=MarketOutcome(db_trade.outcome) if db_trade.outcome else MarketOutcome.YES,
            status=db_trade.status,
            entry_cost_usdc=float(db_trade.entry_cost_usdc),
            shares=float(db_trade.shares),
            entry_price=float(db_trade.entry_price) if db_trade.entry_price is not None else None,
            created_at=db_trade.created_at,
            market_resolves_at=db_trade.market_resolves_at,
            resolved_at=db_trade.resolved_at,
            total_pnl_usdc=float(db_trade.total_pnl_usdc) if db_trade.total_pnl_usdc is not None else None,
            exit_price=float(db_trade.exit_price) if db_trade.exit_price is not None else None,
            is_hedged=bool(db_trade.is_hedged),
            is_paper=bool(db_trade.is_paper),
            signal_type=db_trade.signal_type,
            exit_reason=db_trade.exit_reason,
            mcc=db_trade.mcc,
            confirmations=db_trade.confirmations,
            signal_metadata=db_trade.signal_metadata,
        )
