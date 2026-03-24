"""
Multi-Strategy - Tüm aktif stratejileri çalıştırır ve sinyalleri birleştirir.
"""
from typing import Dict, List
from strategies.base_strategy import BaseStrategy
from strategies.rsi_ema_strategy import RSIEMAStrategy
from strategies.vwap_bounce_strategy import VWAPBounceStrategy
from strategies.breakout_strategy import BreakoutStrategy
from core.signal_generator import SignalGenerator, Signal, FinalSignal
from config import STRATEGY_CONFIG
from utils.logger import logger


class MultiStrategy:
    """Çoklu strateji yönetici sınıfı."""

    def __init__(self):
        self.signal_generator = SignalGenerator()
        self.strategies: Dict[str, BaseStrategy] = {}
        self._initialize_strategies()
        logger.info(
            f"MultiStrategy başlatıldı - "
            f"{len(self.strategies)} aktif strateji"
        )

    def _initialize_strategies(self):
        """Aktif stratejileri oluşturur."""
        available = {
            "rsi_ema": RSIEMAStrategy,
            "vwap_bounce": VWAPBounceStrategy,
            "breakout": BreakoutStrategy,
        }

        enabled = STRATEGY_CONFIG.get("enabled_strategies", [])

        for name in enabled:
            if name in available:
                self.strategies[name] = available[name]()
                logger.info(f"  ✅ Strateji aktif: {name}")
            else:
                logger.warning(f"  ⚠️ Bilinmeyen strateji: {name}")

    def analyze(self, signal_data: Dict) -> FinalSignal:
        """
        Tüm stratejilerden sinyal toplar ve final karar verir.

        Args:
            signal_data: TechnicalAnalysis.get_signal_data() çıktısı

        Returns:
            FinalSignal: Birleşik karar (BUY/SELL/HOLD + güven puanı)
        """
        signals: List[Signal] = []

        for name, strategy in self.strategies.items():
            try:
                signal = strategy.analyze(signal_data)
                signals.append(signal)
            except Exception as e:
                logger.error(f"Strateji hatası ({name}): {e}")
                continue

        return self.signal_generator.aggregate_signals(signals)

    def get_strategy_names(self) -> List[str]:
        """Aktif strateji isimlerini döndürür."""
        return list(self.strategies.keys())
