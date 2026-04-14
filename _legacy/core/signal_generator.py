"""
Signal Generator - Stratejilerden gelen sinyalleri toplar ve final karar verir.
Çoklu strateji oylama sistemi.
"""
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass
from config import STRATEGY_CONFIG
from utils.logger import logger


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Tek bir strateji sinyali."""
    signal_type: SignalType
    confidence: float  # 0.0 - 1.0
    strategy_name: str
    reason: str
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class FinalSignal:
    """Tüm stratejilerden birleşik final sinyal."""
    signal_type: SignalType
    confidence: float
    signals: List[Signal]
    summary: str


class SignalGenerator:
    """Sinyal birleştirme ve oylama sistemi."""

    def __init__(self):
        self.config = STRATEGY_CONFIG
        self.weights = self.config["strategy_weights"]
        logger.info("SignalGenerator başlatıldı")

    def aggregate_signals(self, signals: List[Signal]) -> FinalSignal:
        """
        Birden fazla strateji sinyalini birleştirir.
        Ağırlıklı oylama ile final karar verir.
        """
        if not signals:
            return FinalSignal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                signals=[],
                summary="Sinyal yok",
            )

        buy_score = 0.0
        sell_score = 0.0
        total_weight = 0.0
        reasons = []

        for signal in signals:
            weight = self.weights.get(signal.strategy_name, 0.25)
            total_weight += weight

            if signal.signal_type == SignalType.BUY:
                buy_score += weight * signal.confidence
                reasons.append(f"✅ {signal.strategy_name}: {signal.reason}")
            elif signal.signal_type == SignalType.SELL:
                sell_score += weight * signal.confidence
                reasons.append(f"🔴 {signal.strategy_name}: {signal.reason}")
            else:
                reasons.append(f"⚪ {signal.strategy_name}: HOLD")

        # Normalize
        if total_weight > 0:
            buy_score /= total_weight
            sell_score /= total_weight

        # Final karar
        min_buy = self.config["min_buy_weight"]
        min_sell = self.config["min_sell_weight"]

        if buy_score >= min_buy and buy_score > sell_score:
            final_type = SignalType.BUY
            final_confidence = buy_score
            emoji = "🟢"
        elif sell_score >= min_sell and sell_score > buy_score:
            final_type = SignalType.SELL
            final_confidence = sell_score
            emoji = "🔴"
        else:
            final_type = SignalType.HOLD
            final_confidence = max(buy_score, sell_score)
            emoji = "⚪"

        summary = (
            f"{emoji} {final_type.value} (güven: {final_confidence:.0%}) | "
            + " | ".join(reasons)
        )

        logger.info(f"📊 Final Sinyal: {summary}")

        return FinalSignal(
            signal_type=final_type,
            confidence=final_confidence,
            signals=signals,
            summary=summary,
        )
