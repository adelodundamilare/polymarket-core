from pydantic import BaseModel, Field


class MarketPriceData(BaseModel):

    market_id: str
    yes_price: float = Field(..., ge=0.0, le=1.0)
    no_price: float = Field(..., ge=0.0, le=1.0)


class MarketMetadata(BaseModel):

    id: str
    slug: str
    title: str
    is_active: bool = True
    created_at: str
    updated_at: str


class OrderBookSnapshot(BaseModel):

    market_id: str
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    timestamp: int
