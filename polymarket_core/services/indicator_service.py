from typing import List, Dict, Any
import statistics
from polymarket_core.external.binance.client import BinanceClient
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

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
    def calculate_wick_ratio(highs: List[float], lows: List[float], opens: List[float], closes: List[float], period: int = 14) -> float:
        if len(highs) < period: return 1.0
        wick_sum = 0.0
        range_sum = 0.0
        for i in range(len(highs) - period, len(highs)):
            tr = max(highs[i] - lows[i], 1e-9)
            body = abs(closes[i] - opens[i])
            wick_sum += (tr - body)
            range_sum += tr
        return wick_sum / range_sum

    @staticmethod
    def calculate_body_continuity(opens: List[float], closes: List[float], highs: List[float], lows: List[float], period: int = 14) -> float:
        if len(opens) < period + 1:
            return 1.0
        gap_sum = 0.0
        atr_sum = 0.0
        start = len(opens) - period - 1
        for i in range(start, len(opens) - 1):
            gap = abs(closes[i] - opens[i + 1])
            gap_sum += gap
            atr = max(highs[i] - lows[i], 1e-9)
            atr_sum += atr
        ratio = gap_sum / atr_sum if atr_sum > 0 else 1.0
        return min(ratio, 1.0)

    @staticmethod
    def calculate_directional_consistency(opens: List[float], closes: List[float], period: int = 14) -> float:
        if len(opens) < period:
            return 1.0
        bullish = 0
        start = len(opens) - period
        for i in range(start, len(opens)):
            if closes[i] > opens[i]:
                bullish += 1
        bearish = period - bullish
        dominant = max(bullish, bearish)
        return 1.0 - (dominant / period)

    @staticmethod
    def calculate_cleanliness(highs: List[float], lows: List[float], opens: List[float], closes: List[float], period: int = 14) -> dict:
        wick = IndicatorService.calculate_wick_ratio(highs, lows, opens, closes, period)
        continuity = IndicatorService.calculate_body_continuity(opens, closes, highs, lows, period)
        direction = IndicatorService.calculate_directional_consistency(opens, closes, period)

        score = 1.0 - (0.4 * wick + 0.3 * continuity + 0.3 * direction)
        score = max(0.0, min(1.0, score))

        if score >= 0.70:
            label = "CLEAN"
        elif score >= 0.50:
            label = "NORMAL"
        else:
            label = "MESSY"

        return {
            "cleanliness": round(score, 3),
            "label": label,
            "wick_ratio": round(wick, 3),
            "body_continuity": round(continuity, 3),
            "directional_consistency": round(direction, 3),
        }

    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
        if len(highs) < period * 2:
            return []
            
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []
        
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
            
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm_list.append(up_move)
            else:
                plus_dm_list.append(0)
                
            if down_move > up_move and down_move > 0:
                minus_dm_list.append(down_move)
            else:
                minus_dm_list.append(0)
                
        # Wilders Smoothing
        def smooth(data, p):
            smoothed = [sum(data[:p])]
            for i in range(p, len(data)):
                smoothed.append(smoothed[-1] - (smoothed[-1] / p) + data[i])
            return smoothed

        tr_s = smooth(tr_list, period)
        plus_dm_s = smooth(plus_dm_list, period)
        minus_dm_s = smooth(minus_dm_list, period)
        
        plus_di = [(100 * p / t) if t > 0 else 0 for p, t in zip(plus_dm_s, tr_s)]
        minus_di = [(100 * m / t) if t > 0 else 0 for m, t in zip(minus_dm_s, tr_s)]
        
        dx = []
        for p, m in zip(plus_di, minus_di):
            denom = abs(p + m)
            if denom == 0:
                dx.append(0)
            else:
                dx.append(100 * abs(p - m) / denom)
                
        adxs = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adxs.append((adxs[-1] * (period - 1) + dx[i]) / period)
            
        return adxs

    @staticmethod
    async def get_market_score(coin: str, interval: str = "1m") -> dict:
        try:
            binance = BinanceClient()
            klines = await binance.get_klines(coin, interval, limit=50)
            if not klines or len(klines) < 20:
                return {"score": 0, "label": "MESSY", "metrics": {}}

            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            opens = [float(k[1]) for k in klines]
            closes = [float(k[4]) for k in klines]

            result = IndicatorService.calculate_cleanliness(highs, lows, opens, closes, 14)

            return {
                "label": result["label"],
                "metrics": result
            }
        except Exception as e:
            logger.error(f"Failed to calculate cleanliness engine score for {coin}: {e}")
            return {"label": "MESSY", "metrics": {"cleanliness": 0.0, "wick_ratio": 1.0}}

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
        except Exception as e:
            logger.error(f"Failed to calculate structural trend for {coin}: {e}")
            return "MIXED"
                
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
