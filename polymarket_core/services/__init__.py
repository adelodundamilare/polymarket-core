from .indicator_service import IndicatorService

async def get_market_metrics(coin: str):
    return await IndicatorService.get_market_metrics(coin)
