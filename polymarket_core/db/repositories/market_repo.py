from typing import Optional

from sqlalchemy.orm import Session

from polymarket_core.core.models import Market
from polymarket_core.db.models import MarketModel
from polymarket_core.logger import get_logger

logger = get_logger(__name__)


class MarketRepository:

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_all(self, limit: int = 100) -> list[Market]:
        models = (
            self._session.query(MarketModel)
            .limit(limit)
            .all()
        )
        return [self._to_domain(m) for m in models]

    def find_by_id(self, market_id: str) -> Optional[Market]:
        model = (
            self._session.query(MarketModel)
            .filter(MarketModel.id == market_id)
            .first()
        )

        if not model:
            return None

        return self._to_domain(model)

    def find_by_slug(self, slug: str) -> Optional[Market]:
        model = (
            self._session.query(MarketModel)
            .filter(MarketModel.slug == slug)
            .first()
        )

        if not model:
            return None

        return self._to_domain(model)

    def find_all_active(self, limit: int = 100) -> list[Market]:
        models = (
            self._session.query(MarketModel)
            .filter(MarketModel.is_active == True)
            .limit(limit)
            .all()
        )

        return [self._to_domain(m) for m in models]

    def find_by_liquidity(
        self,
        min_liquidity: float,
        limit: int = 100,
    ) -> list[Market]:
        models = (
            self._session.query(MarketModel)
            .filter(
                MarketModel.is_active == True,
                MarketModel.liquidity_usdc >= min_liquidity,
            )
            .limit(limit)
            .all()
        )

        return [self._to_domain(m) for m in models]

    def save(self, market: Market) -> Market:
        model = MarketModel(
            id=market.id,
            slug=market.slug,
            title=market.title,
            yes_price=market.yes_price,
            no_price=market.no_price,
            liquidity_usdc=market.liquidity_usdc,
            is_active=market.is_active,
            created_at=market.created_at,
            updated_at=market.updated_at,
        )

        self._session.merge(model)
        self._session.commit()

        logger.debug(
            "Market saved",
            extra={
                "market_id": market.id,
                "slug": market.slug,
            },
        )

        return market

    def save_many(self, markets: list[Market]) -> None:
        for market in markets:
            model = MarketModel(
                id=market.id,
                slug=market.slug,
                title=market.title,
                yes_price=market.yes_price,
                no_price=market.no_price,
                liquidity_usdc=market.liquidity_usdc,
                is_active=market.is_active,
                created_at=market.created_at,
                updated_at=market.updated_at,
            )
            self._session.merge(model)

        self._session.commit()

        logger.debug(
            "Markets batch saved",
            extra={"count": len(markets)},
        )

    @staticmethod
    def _to_domain(model: MarketModel) -> Market:
        return Market(
            id=model.id,
            slug=model.slug,
            title=model.title,
            yes_price=model.yes_price,
            no_price=model.no_price,
            liquidity_usdc=model.liquidity_usdc,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
