from typing import List, Dict
import statistics
from polymarket_core.external.binance.client import BinanceClient

class IndicatorService:
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return []
        emas = []
        multiplier = 2 / (period + 1)
        sma = sum(prices[:period]) / period
        emas.append(sma)
        for i in range(period, len(prices)):
            ema = (prices[i] - emas[-1]) * multiplier + emas[-1]
            emas.append(ema)
        return emas

    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int) -> List[float]:
        if len(highs) < period + 1:
            return []
        tr_list = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr_list.append(tr)
        atrs = []
        current_atr = sum(tr_list[:period]) / period
        atrs.append(current_atr)
        for i in range(period, len(tr_list)):
            current_atr = (current_atr * (period - 1) + tr_list[i]) / period
            atrs.append(current_atr)
        return atrs

    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
        if len(highs) < period * 2:
            return []
        up_moves = [highs[i] - highs[i-1] for i in range(1, len(highs))]
        down_moves = [lows[i-1] - lows[i] for i in range(1, len(lows))]
        plus_dm = []
        minus_dm = []
        for u, d in zip(up_moves, down_moves):
            plus_dm.append(u if u > d and u > 0 else 0)
            minus_dm.append(d if d > u and d > 0 else 0)
        tr = []
        for i in range(1, len(highs)):
            tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
        smooth_tr = sum(tr[:period])
        smooth_plus_dm = sum(plus_dm[:period])
        smooth_minus_dm = sum(minus_dm[:period])
        dx_list = []
        for i in range(period, len(tr)):
            smooth_tr = smooth_tr - (smooth_tr / period) + tr[i]
            smooth_plus_dm = smooth_plus_dm - (smooth_plus_dm / period) + plus_dm[i-1]
            smooth_minus_dm = smooth_minus_dm - (smooth_minus_dm / period) + minus_dm[i-1]
            pdi = 100 * (smooth_plus_dm / smooth_tr) if smooth_tr > 0 else 0
            mdi = 100 * (smooth_minus_dm / smooth_tr) if smooth_tr > 0 else 0
            dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
            dx_list.append(dx)
        if len(dx_list) < period:
            return []
        adxs = []
        current_adx = sum(dx_list[:period]) / period
        adxs.append(current_adx)
        for i in range(period, len(dx_list)):
            current_adx = (current_adx * (period - 1) + dx_list[i]) / period
            adxs.append(current_adx)
        return adxs

    @staticmethod
    async def get_market_metrics(coin: str) -> Dict[str, float]:
        try:
            binance = BinanceClient()
            klines = await binance.get_klines(coin, "1m", limit=40)
            if not klines or len(klines) < 30:
                return {"adx": 0.0, "atr": 0.0, "ema_pct": 0.0}

            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]

            emas = IndicatorService.calculate_ema(closes, 9)
            ema_pct = (round(((emas[-1] - closes[-1]) / closes[-1]) * 100, 2) if emas else 0.0)
            
            atrs = IndicatorService.calculate_atr(highs, lows, closes, 14)
            atr = round(atrs[-1], 4) if atrs else 0.0
            
            adxs = IndicatorService.calculate_adx(highs, lows, closes, 14)
            adx = round(adxs[-1], 2) if adxs else 0.0

            return {
                "adx": adx,
                "atr": atr,
                "ema_pct": ema_pct
            }
        except Exception:
            return {"adx": 0.0, "atr": 0.0, "ema_pct": 0.0}

    @staticmethod
    async def get_structural_trend(coin: str) -> str:
        try:
            binance = BinanceClient()
            # Fetch 5m klines for structural macro trend
            klines = await binance.get_klines(coin, "5m", limit=60)
            if not klines or len(klines) < 50:
                return "MIXED"

            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]
            current_price = closes[-1]

            ema_9 = IndicatorService.calculate_ema(closes, 9)[-1]
            ema_21 = IndicatorService.calculate_ema(closes, 21)[-1]
            
            adxs = IndicatorService.calculate_adx(highs, lows, closes, 14)
            current_adx = round(adxs[-1], 2) if adxs else 0.0

            # UPTREND: 9-EMA > 21-EMA, Price > 9-EMA, ADX > 20
            if ema_9 > ema_21 and current_price > ema_9 and current_adx > 20:
                return "UPTREND"
            # DOWNTREND: 9-EMA < 21-EMA, Price < 9-EMA, ADX > 20
            elif ema_9 < ema_21 and current_price < ema_9 and current_adx > 20:
                return "DOWNTREND"
            else:
                return "MIXED"
                
        except Exception:
            return "MIXED"
