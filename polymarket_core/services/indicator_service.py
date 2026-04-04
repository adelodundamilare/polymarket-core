from typing import List
import statistics

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

class MarketRegime:
    STRONG_TREND_UP = "STRONG_TREND_UP"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    STABLE = "STABLE"
    CHOPPY = "CHOPPY"
    NEUTRAL = "NEUTRAL"
