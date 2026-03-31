import asyncio
from datetime import datetime, timezone
import httpx

from polymarket_core.config import settings
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

class GammaClient:
    COIN_SLUGS = {
        "BTC": "btc-updown-15m",
        "ETH": "eth-updown-15m",
        "SOL": "sol-updown-15m",
        "XRP": "xrp-updown-15m",
    }

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = httpx.Timeout(float(timeout))
        self._client: httpx.AsyncClient | None = None
        self._base_url = settings.polymarket_gamma_url

    async def __aenter__(self) -> "GammaClient":
        self._client = httpx.AsyncClient(timeout=self._timeout, verify=False)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()

    async def get_market_by_slug(self, slug: str) -> dict | None:
        if not self._client:
            raise RuntimeError("Client not initialized")

        url = f"{self._base_url}/markets/slug/{slug}"
        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Gamma API request failed for {url}: {repr(e)}")
            return None

    async def get_current_market(self, coin: str, interval_min: int = 15) -> dict | None:
        coin = coin.lower()
        prefix = f"{coin}-updown-{interval_min}m"
        
        now = datetime.now(timezone.utc)
        minute = (now.minute // interval_min) * interval_min
        current_window = now.replace(minute=minute, second=0, microsecond=0)
        current_ts = int(current_window.timestamp())

        ts_list = [
            current_ts,
            current_ts + (interval_min * 60),
            current_ts - (interval_min * 60)
        ]
        
        tasks = [
            self.get_market_by_slug(f"{prefix}-{ts}")
            for ts in ts_list
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, dict) and res and self._is_active(res):
                return res

        return None

    async def get_current_15m_market(self, coin: str) -> dict | None:
        return await self.get_current_market(coin, 15)

    async def get_current_5m_market(self, coin: str) -> dict | None:
        return await self.get_current_market(coin, 5)

    def get_strike_price(self, market: dict) -> float:
        return float(market["strikePrice"])

    def _is_active(self, market: dict | None) -> bool:
        return bool(market and market.get("acceptingOrders"))

    async def get_recent_market_results(self, coin: str, interval_min: int = 5, count: int = 5) -> list[str]:
        import json
        coin = coin.lower()
        prefix = f"{coin}-updown-{interval_min}m"
        
        now = datetime.now(timezone.utc)
        minute = (now.minute // interval_min) * interval_min
        current_window = now.replace(minute=minute, second=0, microsecond=0)
        current_ts = int(current_window.timestamp())
        
        ts_list = [current_ts - (i * interval_min * 60) for i in range(1, count + 1)]
        
        results = []
        for ts in ts_list:
            slug = f"{prefix}-{ts}"
            market = await self.get_market_by_slug(slug)
            if market:
                # 1. Try explicit winningOutcome
                res = market.get("winningOutcome") or market.get("winning_outcome")
                
                # 2. Try outcomePrices logic (1.0 means won)
                if not res:
                    try:
                        p_raw = market.get("outcomePrices")
                        prices = json.loads(p_raw) if isinstance(p_raw, str) else p_raw
                        if prices and len(prices) >= 2:
                            if float(prices[0]) == 1: res = "Up"
                            elif float(prices[1]) == 1: res = "Down"
                    except: pass
                
                # 3. Last resort: check outcome if market is closed
                if not res and market.get("closed"):
                    res = market.get("outcome")

                results.append(str(res) if res else "PENDING")
            else:
                results.append("UNKNOWN")
        return results
