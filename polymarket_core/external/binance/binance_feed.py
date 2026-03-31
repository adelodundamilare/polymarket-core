import asyncio
import json
import time
import httpx
import websockets
from collections import deque
from polymarket_core.config import settings
from polymarket_core.logger import get_logger
from polymarket_core.external.binance.client import BinanceClient

logger = get_logger(__name__)


class BinanceFeed:
    def __init__(self):
        self._prices: dict[str, float] = {}
        self._obi: dict[str, float] = {}
        self._cvd_session: dict[str, float] = {}
        self._trade_history: dict[str, deque] = {}  # (timestamp, signed_qty)
        self._trade_history_vol: dict[str, deque] = {}  # (timestamp, usd_vol)
        self._price_history: dict[str, deque] = {} # (timestamp, price)
        self._vol_session: dict[str, float] = {}
        self._client = BinanceClient()
        self._running = False

    def _symbol(self, coin: str) -> str:
        return f"{coin}USDT"

    async def _bootstrap(self, coin: str):
        try:
            price = await self._client.get_price(coin)
            if price:
                self._prices[coin] = price
                self._vol_session[coin] = 0.0
                self._cvd_session[coin] = 0.0
                self._trade_history[coin] = deque()
                self._trade_history_vol[coin] = deque()
                self._price_history[coin] = deque()
                self._price_history[coin].append((time.time(), price))
                logger.info(f"Binance bootstrap {coin}: Price={self._prices[coin]}")
            else:
                logger.warning(f"Binance bootstrap failed for {coin}: No price returned")
        except Exception as e:
            logger.warning(f"Binance bootstrap failed for {coin}: {e}")

    async def _stream_coin(self, coin: str):
        sym = self._symbol(coin).lower()
        streams = f"{sym}@trade/{sym}@depth20@100ms"
        
        # Fallback WS URLs
        base_urls = [
            "wss://stream.binance.com:9443/stream",
            "wss://stream.binance.com:443/stream",
            "wss://stream.binance.vision/stream"
        ]
        
        while self._running:
            url_idx = 0
            while self._running and url_idx < len(base_urls):
                url = f"{base_urls[url_idx]}?streams={streams}"
                try:
                    async with websockets.connect(url, ping_interval=20, ping_timeout=60) as ws:
                        logger.info(f"Binance WS connected: {coin} on {base_urls[url_idx]}")
                        url_idx = 0 # Reset to primary on success
                        while self._running:
                            try:
                                raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                                stream = raw["stream"]
                                pay = raw["data"]
                                
                                if "@trade" in stream:
                                    price = float(pay["p"])
                                    qty = float(pay["q"])
                                    is_buyer_maker = pay["m"] # True if sell, False if buy
                                    
                                    self._prices[coin] = price
                                    signed_qty = -qty if is_buyer_maker else qty
                                    
                                    self._cvd_session[coin] = self._cvd_session.get(coin, 0.0) + signed_qty
                                    
                                    trade_vol = price * qty
                                    self._vol_session[coin] = self._vol_session.get(coin, 0.0) + trade_vol
                                    
                                    now = time.time()
                                    self._trade_history[coin].append((now, signed_qty))
                                    self._trade_history_vol[coin].append((now, trade_vol))
                                    self._price_history[coin].append((now, price))
                                    
                                    while self._trade_history[coin] and self._trade_history[coin][0][0] < now - 60:
                                        self._trade_history[coin].popleft()
                                        
                                    while self._trade_history_vol[coin] and self._trade_history_vol[coin][0][0] < now - 300: # 5m window
                                        self._trade_history_vol[coin].popleft()

                                    while self._price_history[coin] and self._price_history[coin][0][0] < now - 300: # 5m window
                                        self._price_history[coin].popleft()
                                        
                                elif "@depth" in stream:
                                    bids = pay.get("b", [])
                                    asks = pay.get("a", [])
                                    if bids and asks:
                                        bid_vol = sum(float(b[1]) for b in bids[:10])
                                        ask_vol = sum(float(a[1]) for a in asks[:10])
                                        if (bid_vol + ask_vol) > 0:
                                            self._obi[coin] = (bid_vol - ask_vol) / (bid_vol + ask_vol)

                            except asyncio.TimeoutError:
                                continue
                except Exception as e:
                    logger.warning(f"Binance WS error {coin} on {base_urls[url_idx]}: {e}")
                    url_idx += 1
                    if url_idx < len(base_urls):
                        logger.info(f"Retrying with {base_urls[url_idx]} for {coin}...")
                        await asyncio.sleep(2)
                    else:
                        logger.warning(f"All Binance WS nodes failed for {coin}. Sleeping 10s.")
                        await asyncio.sleep(10)

    async def start(self, coins: list[str]):
        if not coins:
            logger.warning("BinanceFeed started with no coins to watch.")
            return
        self._running = True
        await asyncio.gather(*[self._bootstrap(c) for c in coins])
        for coin in coins:
            asyncio.create_task(self._stream_coin(coin))
        logger.info("Binance multi-metric feed started")

    def stop(self):
        self._running = False

    def get_last_price(self, coin: str) -> float | None:
        return self._prices.get(coin)

    def get_obi(self, coin: str) -> float:
        return self._obi.get(coin, 0.0)

    def get_cvd_60s(self, coin: str) -> float:
        history = self._trade_history.get(coin, [])
        return sum(t[1] for t in history)

    def get_cvd_session(self, coin: str) -> float:
        return self._cvd_session.get(coin, 0.0)

    def get_volume_session(self, coin: str) -> float:
        return self._vol_session.get(coin, 0.0)

    def get_volume_5m(self, coin: str) -> float:
        history = self._trade_history_vol.get(coin, [])
        return sum(t[1] for t in history)

    def get_volume_24h(self, coin: str) -> float:
        # Legacy compat: redirect to session volume
        return self.get_volume_session(coin)

    def get_strike_velocity(self, coin: str) -> float:
        history = self._price_history.get(coin, [])
        if len(history) < 2: return 0.0
        now = time.time()
        past = [p for p in history if p[0] < now - 60]
        if not past: return 0.0
        start_p = past[-1][1]
        curr_p = history[-1][1]
        return (curr_p - start_p) / 60

    def get_acceleration(self, coin: str) -> float:
        history = self._price_history.get(coin, [])
        if len(history) < 2: return 0.0
        now = time.time()
        
        v_now = self.get_strike_velocity(coin)
        
        past_60s = [p for p in history if p[0] < now - 60]
        if len(past_60s) < 2: return 0.0
        
        past_120s = [p for p in history if p[0] < now - 120]
        if not past_120s: return 0.0
        
        v_past = (past_60s[-1][1] - past_120s[-1][1]) / 60
        return (v_now - v_past) / 60
