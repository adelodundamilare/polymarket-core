import httpx
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

class BinanceClient:
    BASE_URLS = [
        "https://api.binance.com/api/v3",
        "https://api-gcp.binance.com/api/v3",
        "https://data-api.binance.vision/api/v3",
    ]

    SYMBOL_MAP = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "XRP": "XRPUSDT",
    }

    def __init__(self, timeout: int = 5) -> None:
        self._timeout = timeout
        self._active_url: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _fetch(self, endpoint: str, params: dict) -> dict | None:
        urls = list(self.BASE_URLS)
        if self._active_url and self._active_url in urls:
            urls.remove(self._active_url)
            urls.insert(0, self._active_url)

        client = await self._get_client()
        for base_url in urls:
            url = f"{base_url}{endpoint}"
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    self._active_url = base_url
                    return response.json()
            except (httpx.HTTPError, Exception) as e:
                if self._active_url == base_url:
                    logger.warning(f"Binance node fail ({base_url}): {e}")
                    self._active_url = None
                continue
        return None

    async def get_price(self, symbol: str) -> float | None:
        binance_symbol = self.SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")

        params = {"symbol": binance_symbol}
        data = await self._fetch("/ticker/price", params)

        if data and "price" in data:
            return float(data["price"])
        return None

    async def get_candle_open(self, symbol: str, interval: str = "15m") -> float | None:
        data = await self.get_klines(symbol, interval, limit=1)
        if data and len(data) > 0:
            return float(data[0][1])
        return None

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100, **kwargs) -> list | None:
        binance_symbol = self.SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")

        params = {
            "symbol": binance_symbol,
            "interval": interval,
            "limit": limit
        }
        params.update(kwargs)

        return await self._fetch("/klines", params)
