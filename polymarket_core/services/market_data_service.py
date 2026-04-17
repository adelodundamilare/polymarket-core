import json
import math
import re
import asyncio
import time
from datetime import datetime, timezone
from collections import deque
from polymarket_core.config import settings
from polymarket_core.external.binance.client import BinanceClient
from polymarket_core.core.constants import WINNING_YES_VALUES, WINNING_NO_VALUES
from polymarket_core.logger import get_logger

logger = get_logger(__name__)


class MarketDataService:
    def __init__(self, binance_client: BinanceClient = None) -> None:
        self._binance = binance_client or BinanceClient()
        self._obi_history: dict[str, deque] = {}

    def calculate_obi_velocity(self, coin: str, current_obi: float) -> float:
        now = time.time()
        if coin not in self._obi_history:
            self._obi_history[coin] = deque(maxlen=10)
            self._obi_history[coin].append((now, current_obi))
            return 0.0
            
        prev_ts, prev_obi = self._obi_history[coin][-1]
        dt = now - prev_ts
        if dt <= 0: return 0.0
        
        velocity = (current_obi - prev_obi) / dt
        self._obi_history[coin].append((now, current_obi))
        return velocity

    def get_token_id(self, market: dict, direction: str) -> str | None:
        try:
            tokens = market.get("tokens") or []
            if tokens and isinstance(tokens, list):
                for t in tokens:
                    res_outcome = str(t.get("outcome", "")).lower()
                    if direction.upper() == "YES" and res_outcome in WINNING_YES_VALUES:
                        logger.debug(f"MarketDataService | Found YES mapping: {res_outcome} -> {t.get('token_id')}")
                        return t.get("token_id")
                    if direction.upper() == "NO" and res_outcome in WINNING_NO_VALUES:
                        logger.debug(f"MarketDataService | Found NO mapping: {res_outcome} -> {t.get('token_id')}")
                        return t.get("token_id")

            ids = market.get("clobTokenIds") or market.get("clob_token_ids")
            if isinstance(ids, str):
                try: ids = json.loads(ids)
                except Exception: pass

            if not ids: return None

            if isinstance(ids, dict):
                return ids.get("YES" if direction.upper() == "YES" else "NO")

            if not isinstance(ids, list) or len(ids) < 2:
                return None

            raw_outcomes = market.get("outcomes")
            outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes

            if outcomes and isinstance(outcomes, list) and len(outcomes) >= 2:
                o0 = str(outcomes[0]).lower()
                is_yes0 = any(val in o0 for val in WINNING_YES_VALUES)

                if direction.upper() == "YES":
                    return ids[0] if is_yes0 else ids[1]
                return ids[1] if is_yes0 else ids[0]

            return ids[0] if direction.upper() == "YES" else ids[1]
        except Exception as e:
            logger.error(f"MarketDataService | Error getting token ID: {e}")
            return None

    def get_strike_price(self, market: dict) -> float:
        line = market.get("line")
        if line:
            try: return float(line)
            except Exception: pass

        q = market.get("question", "")
        match = re.search(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', q)
        if match:
            return float(match.group(1).replace(',', ''))

        return 0.0

    async def get_strike_price_async(self, market: dict) -> float:
        strike = self.get_strike_price(market)
        if strike > 0:
            return strike

        slug = market.get("slug", "")
        if "updown" in slug:
            try:
                parts = slug.split('-')
                if len(parts) >= 4:
                    start_ts = int(parts[-1])
                    symbol = parts[0].upper()
                    klines = await self._binance.get_klines(symbol, interval="1m", limit=1, startTime=start_ts * 1000)
                    if klines:
                        return float(klines[0][1])
            except Exception as e:
                logger.error(f"MarketDataService | Failed to fetch Binance strike: {e}")

        return 0.0

    def calculate_time_remaining(self, market: dict) -> float:
        end_time_str = market.get("endDate") or market.get("end_date")
        if not end_time_str:
            return 0
        try:
            end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
            return (end_dt - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            return 0

    def calculate_market_age(self, market: dict) -> float:
        slug = market.get("slug", "")
        try:
            parts = slug.split('-')
            if len(parts) >= 4:
                return max(0, datetime.now(timezone.utc).timestamp() - int(parts[-1]))
        except Exception: pass
        return 999999.0

    async def get_active_market(self, coin: str) -> dict | None:
        from polymarket_core.external.polymarket.gamma import GammaClient
        async with GammaClient() as gamma:
            return await gamma.get_active_market(coin)

    async def get_token_price(self, client, token_id: str) -> float | None:
        try:
            ob = await client.get_orderbook(token_id)
            if not ob: return None
            bids, asks = ob.get("bids", []), ob.get("asks", [])
            if bids and asks: return (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            if bids: return float(bids[0]["price"])
            if asks: return float(asks[0]["price"])
            return None
        except Exception as e:
            logger.error(f"MarketDataService | Token price fetch failed for {token_id}: {e}")
            return None

    async def get_price_and_volume(self, client, token_id: str) -> tuple[float | None, float | None, float | None, float, float]:
        mid, bid, ask, b_vol, a_vol = None, None, None, 0.0, 0.0
        try:
            ob = await client.get_orderbook(token_id)
            bids, asks = ob.get("bids", []), ob.get("asks", [])
            for b in bids: b_vol += float(b.get("size", 0))
            for a in asks: a_vol += float(a.get("size", 0))
            if bids: bid = max(float(b["price"]) for b in bids)
            if asks: ask = min(float(a["price"]) for a in asks)
            mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        except Exception as e:
            logger.error(f"MarketDataService | Orderbook fetch failed for {token_id}: {e}")
        return mid, bid, ask, b_vol, a_vol

    async def get_market_data_bundle(self, client, market: dict, coin: str, yes_token: str) -> dict | None:
        try:
            bundle = await asyncio.gather(
                self.get_price_and_volume(client, yes_token),
                self._binance.get_price(coin),
                self.get_strike_price_async(market)
            )
            (yes_mid, yes_bid, yes_ask, bid_vol, ask_vol), spot_price, strike_price = bundle
            if spot_price is None: return None

            gamma_price = None
            try:
                o_prices = market.get("outcomePrices") or "[]"
                o_list = json.loads(o_prices) if isinstance(o_prices, str) else o_prices
                if len(o_list) >= 1: gamma_price = float(o_list[0])
            except Exception: pass

            return {
                "YES": yes_mid, "YES_BID": yes_bid, "YES_ASK": yes_ask,
                "GAMMA": gamma_price, "SPOT": spot_price, "STRIKE": strike_price,
                "YES_ID": yes_token, "bid_volume": bid_vol, "ask_volume": ask_vol,
            }
        except Exception as e:
            logger.error(f"MarketDataService | Data bundle failed for {coin}: {e}")
            return None

    async def get_prices_for_markets(self, client, markets: dict[str, dict]) -> dict[str, dict]:
        results: dict[str, dict] = {}
        tasks: list = []
        labels: list[str] = []
        for coin_label, market in markets.items():
            coin = coin_label.split("_")[0]
            yes_token = self.get_token_id(market, "YES")

            if yes_token:
                tasks.append(self.get_market_data_bundle(client, market, coin, yes_token))
                labels.append(coin_label)
            else:
                logger.warning(f"MarketDataService | Mapping failed for {coin_label}. Outcomes: {market.get('outcomes')}")

        if not tasks: return {}
        bundle_results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(bundle_results):
            if not isinstance(res, Exception) and res:
                results[labels[i]] = res
        return results

    @staticmethod
    def calculate_macro_trend(normalized_results: list[str], dominance_pct: float) -> str:
        valid_macro = [r for r in normalized_results if r not in ("pending", "unknown")]
        if not valid_macro:
            return "MIXED"
            
        up_values = {"up", "yes", "true", "0", "above", "higher"}
        down_values = {"down", "no", "false", "1", "below", "lower"}
        
        up_cnt = sum(1 for r in valid_macro if r in up_values)
        dn_cnt = sum(1 for r in valid_macro if r in down_values)
        
        if up_cnt / len(valid_macro) >= dominance_pct:
            return "UPTREND"
        elif dn_cnt / len(valid_macro) >= dominance_pct:
            return "DOWNTREND"
        return "MIXED"

    @staticmethod
    def calculate_obi(alt_data: dict) -> float:
        bid_v = alt_data.get("bid_volume", 0)
        ask_v = alt_data.get("ask_volume", 0)
        if (bid_v + ask_v) <= 0: return 0.0
        return (bid_v - ask_v) / (bid_v + ask_v)

    @staticmethod
    def calculate_fair_probability(spot: float, strike: float, time_rem_sec: float) -> float:
        if strike <= 0 or spot <= 0 or time_rem_sec <= 0: return 0.5
        try:
            t_years = max(time_rem_sec, 1) / (365 * 24 * 3600)
            vol = settings.theoretical_volatility
            d2 = (math.log(spot / strike) - 0.5 * (vol ** 2) * t_years) / (vol * math.sqrt(t_years))
            return float(0.5 * (1 + math.erf(d2 / math.sqrt(2))))
        except Exception: return 0.5

    @staticmethod
    def check_liquidity(alt_data: dict, is_long: bool) -> bool:
        if not settings.confirm_liquidity: return True
        bid, ask = alt_data.get("YES_BID"), alt_data.get("YES_ASK")
        if bid is None or ask is None or bid <= 0: return False
        spread = (ask - bid) / bid
        if spread > settings.max_spread: return False
        depth = alt_data.get("ask_volume", 0) if is_long else alt_data.get("bid_volume", 0)
        return depth >= settings.min_depth_usdc
