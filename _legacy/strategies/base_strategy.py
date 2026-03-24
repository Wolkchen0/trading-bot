"""
Base Strategy - Tüm stratejiler için temel abstract sınıf.
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional
from core.signal_generator import Signal, SignalType


class BaseStrategy(ABC):
    """Strateji temel sınıfı. Tüm stratejiler bu sınıftan türer."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, signal_data: Dict) -> Signal:
        """
        Teknik analiz verilerini alır, al/sat/hold sinyali döndürür.

        Args:
            signal_data: TechnicalAnalysis.get_signal_data() çıktısı

        Returns:
            Signal: BUY, SELL veya HOLD sinyali + güven puanı
        """
        pass

    def _create_signal(
        self, signal_type: SignalType, confidence: float, reason: str, metadata: Dict = None
    ) -> Signal:
        """Yardımcı: Signal objesi oluşturur."""
        return Signal(
            signal_type=signal_type,
            confidence=min(max(confidence, 0.0), 1.0),  # 0-1 arasında tut
            strategy_name=self.name,
            reason=reason,
            metadata=metadata or {},
        )
