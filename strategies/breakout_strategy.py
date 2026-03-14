"""
Breakout Strategy
- Konsolidasyon sonrası hacimli kırılma tespiti
- Bull flag benzeri formasyonlar
- ATR bazlı volatilite kontrolü
"""
from typing import Dict
from strategies.base_strategy import BaseStrategy
from core.signal_generator import Signal, SignalType
from config import TECHNICAL_CONFIG
from utils.logger import logger


class BreakoutStrategy(BaseStrategy):
    """Breakout / Bull Flag strateji sınıfı."""

    def __init__(self):
        super().__init__("breakout")
        self.config = TECHNICAL_CONFIG

    def analyze(self, data: Dict) -> Signal:
        """
        Breakout analizi.

        BUY: Yukarı kırılma + hacim patlaması + momentum
        SELL: Kırılma başarısız (geri düşüş) veya aşırı uzama
        """
        close = data.get("close", 0)
        prev_close = data.get("prev_close", 0)
        rsi = data.get("rsi", 50)
        ema_fast = data.get("ema_fast", 0)
        ema_medium = data.get("ema_medium", 0)
        ema_slow = data.get("ema_slow", 0)
        bb_upper = data.get("bb_upper", 0)
        bb_lower = data.get("bb_lower", 0)
        bb_middle = data.get("bb_middle", 0)
        atr = data.get("atr", 0)
        relative_volume = data.get("relative_volume", 1)
        momentum = data.get("momentum", 0)
        macd_hist = data.get("macd_hist", 0)

        if close <= 0 or bb_upper <= 0:
            return self._create_signal(SignalType.HOLD, 0.0, "Yetersiz veri")

        confidence = 0.0
        reasons = []

        # ============ BUY: Breakout Detection ============
        buy_points = 0
        max_points = 5

        # 1. Bollinger Bands üst bandı kırılması
        if close > bb_upper:
            buy_points += 1.5
            reasons.append("BB üst band kırılması")
        elif close > bb_middle and prev_close <= bb_middle:
            buy_points += 0.8
            reasons.append("BB orta band kırılması")

        # 2. Güçlü yukarı momentum
        if momentum > 0 and close > prev_close:
            price_change_pct = ((close - prev_close) / prev_close) * 100
            if price_change_pct > 1.0:
                buy_points += 1
                reasons.append(f"Güçlü hareket (+{price_change_pct:.1f}%)")
            elif price_change_pct > 0.3:
                buy_points += 0.5

        # 3. Hacim patlaması (breakout doğrulama)
        if relative_volume > 2.0:
            buy_points += 1.5
            reasons.append(f"Hacim patlaması ({relative_volume:.1f}x)")
        elif relative_volume > 1.5:
            buy_points += 0.7
            reasons.append(f"Yüksek hacim ({relative_volume:.1f}x)")

        # 4. EMA dizilimi pozitif
        if ema_fast > ema_medium > 0:
            buy_points += 0.5
            reasons.append("EMA trend yukarı")

        # 5. MACD pozitif momentum
        if macd_hist > 0:
            buy_points += 0.3

        # RSI çok yüksekse breakout zayıf olabilir
        if rsi > 80:
            buy_points -= 1
            reasons.append(f"⚠️ RSI çok yüksek ({rsi:.0f})")

        # ============ SELL: Failed Breakout / Exhaustion ============
        sell_points = 0

        # Bollinger alt bandı kırılması (breakdown)
        if close < bb_lower:
            sell_points += 1.5
            reasons.append("BB alt band kırılması")

        # Aşırı uzama sonrası geri çekilme
        if rsi > 75 and close < prev_close:
            sell_points += 1
            reasons.append("Aşırı uzama + geri çekilme")

        # Negatif momentum
        if momentum < 0 and close < ema_fast:
            sell_points += 1
            reasons.append("Negatif momentum")

        # Hacim düşük (zayıf kırılma)
        if relative_volume < 0.8 and close < prev_close:
            sell_points += 0.5

        # EMA altında kalma
        if 0 < close < ema_medium:
            sell_points += 0.5

        # ============ FİNAL KARAR ============
        buy_confidence = buy_points / max_points
        sell_confidence = sell_points / max_points

        if buy_confidence > sell_confidence and buy_confidence >= 0.40:
            reason = " + ".join(reasons) if reasons else "Breakout BUY"
            logger.debug(f"[BREAKOUT] BUY: {reason} (güven: {buy_confidence:.0%})")
            return self._create_signal(
                SignalType.BUY, buy_confidence, reason,
                {"breakout_type": "bullish", "atr": atr},
            )
        elif sell_confidence > buy_confidence and sell_confidence >= 0.40:
            reason = " + ".join(reasons) if reasons else "Breakdown SELL"
            logger.debug(f"[BREAKOUT] SELL: {reason} (güven: {sell_confidence:.0%})")
            return self._create_signal(
                SignalType.SELL, sell_confidence, reason,
                {"breakout_type": "bearish", "atr": atr},
            )
        else:
            return self._create_signal(SignalType.HOLD, 0.0, "Breakout bekleniyor")
