from datetime import datetime

from sqlalchemy.orm import Session

from polymarket_core.core.models import OrderStatus, OrderType, Order, OrderSide
from polymarket_core.db.models import OrderModel


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, order: Order) -> None:
        db_order = OrderModel(
            id=order.id,
            trade_id=order.trade_id,
            token_id=order.token_id,
            order_type=order.order_type,
            side=order.side,
            shares=order.shares,
            status=order.status,
            created_at=order.created_at,
            time_remaining_min=order.time_remaining_min,
            filled_at=order.filled_at,
            filled_price=order.filled_price,
        )
        self._session.add(db_order)
        self._session.commit()

    def get_by_trade_id(self, trade_id: str) -> list[Order]:
        db_orders = self._session.query(OrderModel).filter(
            OrderModel.trade_id == trade_id
        ).order_by(OrderModel.created_at).all()
        return [self._to_domain(o) for o in db_orders]

    def get_pending(self) -> list[Order]:
        db_orders = self._session.query(OrderModel).filter(
            OrderModel.status == OrderStatus.PENDING
        ).all()
        return [self._to_domain(o) for o in db_orders]

    def get_all(self, limit: int = 100) -> list[Order]:
        db_orders = self._session.query(OrderModel).order_by(
            OrderModel.created_at.desc()
        ).limit(limit).all()
        return [self._to_domain(o) for o in db_orders]

    def get_by_id(self, order_id: str) -> Order | None:
        db_order = self._session.query(OrderModel).filter(
            OrderModel.id == order_id
        ).first()
        if not db_order:
            return None
        return self._to_domain(db_order)

    def update_status(
        self,
        order_id: str,
        status: OrderStatus,
        filled_price: float | None = None,
        time_remaining_min: float | None = None,
    ) -> None:
        db_order = self._session.query(OrderModel).filter(
            OrderModel.id == order_id
        ).first()
        if db_order:
            db_order.status = status
            if filled_price is not None:
                db_order.filled_price = filled_price
                db_order.filled_at = datetime.utcnow()
            if time_remaining_min is not None:
                db_order.time_remaining_min = time_remaining_min
            self._session.commit()

    def _to_domain(self, db_order: OrderModel) -> Order:
        return Order(
            id=str(db_order.id),
            trade_id=str(db_order.trade_id),
            token_id=db_order.token_id,
            order_type=OrderType(db_order.order_type),
            side=OrderSide(db_order.side),
            shares=float(db_order.shares),
            status=db_order.status,
            created_at=db_order.created_at,
            time_remaining_min=float(db_order.time_remaining_min) if db_order.time_remaining_min is not None else None,
            filled_at=db_order.filled_at,
            filled_price=float(db_order.filled_price) if db_order.filled_price else None,
        )
