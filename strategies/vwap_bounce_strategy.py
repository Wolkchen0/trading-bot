"""
VWAP Bounce Strategy
- Fiyat VWAP'a yaklaşıp sıçrama yapınca AL
- Fiyat VWAP altına düşünce SAT
- Gün içi (intraday) strateji
"""
from typing import Dict
from strategies.base_strategy import BaseStrategy
from core.signal_generator import Signal, SignalType
from config import TECHNICAL_CONFIG
from utils.logger import logger


class VWAPBounceStrategy(BaseStrategy):
    """VWAP Bounce strateji sınıfı."""

    def __init__(self):
        super().__init__("vwap_bounce")
        self.config = TECHNICAL_CONFIG

    def analyze(self, data: Dict) -> Signal:
        """
        VWAP Bounce analizi.

        BUY: Fiyat VWAP'a dokunup sıçrama yaptığında + hacim desteği
        SELL: Fiyat VWAP altına düşüp devam ettiğinde
        """
        close = data.get("close", 0)
        prev_close = data.get("prev_close", 0)
        vwap = data.get("vwap", 0)
        rsi = data.get("rsi", 50)
        relative_volume = data.get("relative_volume", 1)
        ema_fast = data.get("ema_fast", 0)
        momentum = data.get("momentum", 0)
        bb_lower = data.get("bb_lower", 0)
        bb_upper = data.get("bb_upper", 0)

        # VWAP verisi yoksa HOLD
        if vwap <= 0 or close <= 0:
            return self._create_signal(SignalType.HOLD, 0.0, "VWAP verisi yok")

        # VWAP'a olan mesafe (yüzde)
        vwap_distance = (close - vwap) / vwap
        threshold = self.config["vwap_bounce_threshold"]

        confidence = 0.0
        reasons = []

        # ============ BUY: VWAP Bounce ============
        buy_points = 0
        max_points = 5

        # Fiyat VWAP'ın hemen üzerinde (bounce yapmış)
        if 0 < vwap_distance < threshold * 3:
            # VWAP'tan sıçrama
            if prev_close <= vwap * 1.001:
                buy_points += 2
                reasons.append(f"VWAP bounce (mesafe: {vwap_distance:.3f})")
            else:
                buy_points += 1
                reasons.append("VWAP üzerinde")

        # Fiyat VWAP'ın hemen altında (potansiyel bounce)
        if -threshold * 2 < vwap_distance < 0:
            if momentum > 0:
                buy_points += 1.5
                reasons.append("VWAP'a yakın + yukarı momentum")

        # RSI desteği (aşırı satılmamış ama düşük)
        if 30 < rsi < 50:
            buy_points += 0.5
            reasons.append(f"RSI uygun ({rsi:.0f})")

        # Hacim artışı
        if relative_volume > 1.2:
            buy_points += 0.5
            reasons.append(f"Hacim ({relative_volume:.1f}x)")

        # Bollinger alt bandına yakın
        if bb_lower > 0 and close < bb_lower * 1.01:
            buy_points += 0.5
            reasons.append("BB alt bandında")

        # ============ SELL: VWAP Kırılma ============
        sell_points = 0

        # Fiyat VWAP'ın altında ve düşüyor
        if vwap_distance < -threshold:
            sell_points += 1.5
            reasons.append(f"VWAP altında ({vwap_distance:.3f})")

            if prev_close > vwap:
                sell_points += 1
                reasons.append("VWAP kırıldı (yukarıdan aşağı)")

        # RSI yüksek
        if rsi > 65:
            sell_points += 0.5

        # Momentum negatif
        if momentum < 0 and close < vwap:
            sell_points += 0.5

        # Bollinger üst bandı
        if bb_upper > 0 and close > bb_upper * 0.99:
            sell_points += 0.5
            reasons.append("BB üst bandında")

        # ============ FİNAL KARAR ============
        buy_confidence = buy_points / max_points
        sell_confidence = sell_points / max_points

        if buy_confidence > sell_confidence and buy_confidence >= 0.35:
            reason = " + ".join(reasons) if reasons else "VWAP Bounce BUY"
            logger.debug(f"[VWAP] BUY: {reason} (güven: {buy_confidence:.0%})")
            return self._create_signal(
                SignalType.BUY, buy_confidence, reason,
                {"vwap": vwap, "vwap_distance": round(vwap_distance, 4)},
            )
        elif sell_confidence > buy_confidence and sell_confidence >= 0.35:
            reason = " + ".join(reasons) if reasons else "VWAP Breakdown"
            logger.debug(f"[VWAP] SELL: {reason} (güven: {sell_confidence:.0%})")
            return self._create_signal(
                SignalType.SELL, sell_confidence, reason,
                {"vwap": vwap, "vwap_distance": round(vwap_distance, 4)},
            )
        else:
            return self._create_signal(SignalType.HOLD, 0.0, "VWAP nötr")
