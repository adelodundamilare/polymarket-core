import httpx
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

class CoinGeckoClient:
    BASE_URL = "https://api.coingecko.com/api/v3"

    SYMBOL_MAP = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "XRP": "ripple",
    }

    def __init__(self, timeout: int = 5) -> None:
        self._timeout = timeout

    async def get_price(self, symbol: str) -> float | None:
        coin_id = self.SYMBOL_MAP.get(symbol.upper())
        if not coin_id:
            return None

        url = f"{self.BASE_URL}/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": "usd"
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if coin_id in data and "usd" in data[coin_id]:
                        return float(data[coin_id]["usd"])
            except Exception as e:
                logger.warning(f"CoinGecko price fetch failed: {e}")

        return None
