"""
RSI + EMA Momentum Strategy
- RSI aşırı alım/satım bölgelerinde sinyal üretir
- EMA crossover ile trend yönünü doğrular
- MACD histogram ile momentum doğrulama
"""
from typing import Dict
from strategies.base_strategy import BaseStrategy
from core.signal_generator import Signal, SignalType
from config import TECHNICAL_CONFIG
from utils.logger import logger


class RSIEMAStrategy(BaseStrategy):
    """RSI + EMA Momentum strateji sınıfı."""

    def __init__(self):
        super().__init__("rsi_ema")
        self.config = TECHNICAL_CONFIG

    def analyze(self, data: Dict) -> Signal:
        """
        RSI + EMA analizi yapar.

        BUY koşulları (tümü karşılanmalı):
        1. RSI < 35 (aşırı satılmış bölgeye yakın)
        2. EMA Fast > EMA Medium (kısa vadeli yükseliş)
        3. MACD histogram pozitif veya yükseliyor
        4. Göreceli hacim > 1.0

        SELL koşulları:
        1. RSI > 65 (aşırı alınmış bölgeye yakın)
        2. EMA Fast < EMA Medium (kısa vadeli düşüş)
        """
        rsi = data.get("rsi", 50)
        ema_fast = data.get("ema_fast", 0)
        ema_medium = data.get("ema_medium", 0)
        ema_slow = data.get("ema_slow", 0)
        macd_hist = data.get("macd_hist", 0)
        prev_macd_hist = data.get("prev_macd_hist", 0)
        prev_rsi = data.get("prev_rsi", 50)
        relative_volume = data.get("relative_volume", 1)
        close = data.get("close", 0)

        # Güven puanı hesaplama
        confidence = 0.0
        reasons = []

        # ============ BUY SİNYALLERİ ============
        buy_points = 0
        max_buy_points = 5

        # RSI aşırı satılmış
        if rsi < self.config["rsi_oversold"]:
            buy_points += 1.5
            reasons.append(f"RSI aşırı satılmış ({rsi:.1f})")
        elif rsi < 40:
            buy_points += 0.5
            reasons.append(f"RSI düşük ({rsi:.1f})")

        # RSI yükseliyor (dip yapıp çıkış)
        if rsi > prev_rsi and rsi < 50:
            buy_points += 0.5
            reasons.append("RSI yükseliyor")

        # EMA trend - fast > medium (yükseliş)
        if ema_fast > ema_medium > 0:
            buy_points += 1
            reasons.append("EMA bullish crossover")

        # Fiyat EMA slow üzerinde (genel trend yukarı)
        if close > ema_slow > 0:
            buy_points += 0.5
            reasons.append("Fiyat EMA50 üzerinde")

        # MACD histogram pozitif veya yükseliyor
        if macd_hist > 0:
            buy_points += 0.5
            reasons.append("MACD pozitif")
        elif macd_hist > prev_macd_hist:
            buy_points += 0.3
            reasons.append("MACD yükseliyor")

        # Hacim desteği
        if relative_volume > 1.5:
            buy_points += 0.5
            reasons.append(f"Güçlü hacim ({relative_volume:.1f}x)")

        # ============ SELL SİNYALLERİ ============
        sell_points = 0
        max_sell_points = 5

        # RSI aşırı alınmış
        if rsi > self.config["rsi_overbought"]:
            sell_points += 1.5
            reasons.append(f"RSI aşırı alınmış ({rsi:.1f})")
        elif rsi > 60:
            sell_points += 0.5

        # RSI düşüyor
        if rsi < prev_rsi and rsi > 50:
            sell_points += 0.5

        # EMA trend - fast < medium (düşüş)
        if 0 < ema_fast < ema_medium:
            sell_points += 1
            reasons.append("EMA bearish crossover")

        # MACD histogram negatif
        if macd_hist < 0:
            sell_points += 0.5

        # Fiyat EMA slow altında
        if 0 < close < ema_slow:
            sell_points += 0.5

        # ============ FİNAL KARAR ============
        buy_confidence = buy_points / max_buy_points
        sell_confidence = sell_points / max_sell_points

        if buy_confidence > sell_confidence and buy_confidence >= 0.4:
            reason = " + ".join(reasons) if reasons else "RSI+EMA BUY"
            logger.debug(f"[RSI_EMA] BUY sinyali: {reason} (güven: {buy_confidence:.0%})")
            return self._create_signal(
                SignalType.BUY,
                buy_confidence,
                reason,
                {"rsi": rsi, "ema_trend": "bullish"},
            )
        elif sell_confidence > buy_confidence and sell_confidence >= 0.4:
            reason = " + ".join(reasons) if reasons else "RSI+EMA SELL"
            logger.debug(f"[RSI_EMA] SELL sinyali: {reason} (güven: {sell_confidence:.0%})")
            return self._create_signal(
                SignalType.SELL,
                sell_confidence,
                reason,
                {"rsi": rsi, "ema_trend": "bearish"},
            )
        else:
            return self._create_signal(
                SignalType.HOLD, 0.0, "RSI+EMA nötr bölgede"
            )
