"""
Sektör Rotasyonu — VIX Bazlı Dinamik Sektör Ağırlıklandırma

VIX seviyesine göre hangi sektörlerin favori olduğunu belirler:
  - Düşük VIX (<15): Agresif sektörler (Semiconductors, EV, CryptoMining)
  - Normal VIX (15-25): Dengeli (Technology, Fintech, E-Commerce)
  - Yüksek VIX (25-35): Defansif (Technology, Data_AI)
  - Çok Yüksek VIX (>35): Nakit ağırlıklı, az pozisyon

Kullanım:
    rotator = SectorRotator()
    tier = rotator.get_sector_tier("NVDA", vix=18.5)
    # → "aggressive" veya "neutral" veya "defensive"
"""
from typing import Dict, Optional
from utils.logger import logger


# VIX seviyeleri → favori sektörler
VIX_SECTORS = {
    "low": {  # VIX < 15: Risk-on
        "threshold": 15,
        "preferred": ["Semiconductors", "EV", "CryptoMining", "Fintech"],
        "neutral": ["Technology", "E-Commerce", "Data_AI"],
        "avoid": [],
        "max_positions": 4,
        "weight_boost": 1.2,  # Tercih edilen sektörlere %20 fazla
    },
    "normal": {  # VIX 15-25: Dengeli
        "threshold": 25,
        "preferred": ["Technology", "Data_AI", "E-Commerce"],
        "neutral": ["Semiconductors", "Fintech", "Cybersecurity"],
        "avoid": ["EV", "CryptoMining"],
        "max_positions": 3,
        "weight_boost": 1.1,
    },
    "high": {  # VIX 25-35: Defansif
        "threshold": 35,
        "preferred": ["Technology"],  # Sadece büyük teknoloji
        "neutral": ["Data_AI", "Cybersecurity"],
        "avoid": ["EV", "CryptoMining", "Fintech", "Semiconductors"],
        "max_positions": 2,
        "weight_boost": 1.0,
    },
    "extreme": {  # VIX > 35: Nakit kral
        "threshold": 100,
        "preferred": [],
        "neutral": ["Technology"],
        "avoid": ["Semiconductors", "EV", "CryptoMining", "Fintech", "E-Commerce"],
        "max_positions": 1,
        "weight_boost": 0.5,  # Çok küçük pozisyonlar
    },
}


class SectorRotator:
    """VIX bazlı sektör rotasyonu motoru."""

    def __init__(self):
        self._last_vix = None
        self._current_regime = "normal"
        logger.info("SectorRotator başlatıldı")

    def update_vix(self, vix: float):
        """VIX değerini güncelle ve rejimi belirle."""
        self._last_vix = vix

        if vix < VIX_SECTORS["low"]["threshold"]:
            self._current_regime = "low"
        elif vix < VIX_SECTORS["normal"]["threshold"]:
            self._current_regime = "normal"
        elif vix < VIX_SECTORS["high"]["threshold"]:
            self._current_regime = "high"
        else:
            self._current_regime = "extreme"

    @property
    def current_regime(self) -> str:
        return self._current_regime

    @property
    def regime_config(self) -> Dict:
        return VIX_SECTORS.get(self._current_regime, VIX_SECTORS["normal"])

    def get_sector_tier(self, symbol: str, sector: str = None,
                        vix: float = None) -> str:
        """
        Hissenin sektörüne göre tier belirle.

        Returns: "preferred" | "neutral" | "avoid"
        """
        if vix is not None:
            self.update_vix(vix)

        if sector is None:
            from config import SECTOR_MAP
            sector = SECTOR_MAP.get(symbol, "Unknown")

        cfg = self.regime_config
        if sector in cfg["preferred"]:
            return "preferred"
        elif sector in cfg["avoid"]:
            return "avoid"
        else:
            return "neutral"

    def get_weight_multiplier(self, symbol: str, sector: str = None) -> float:
        """Sektör bazlı pozisyon ağırlık çarpanı."""
        tier = self.get_sector_tier(symbol, sector)
        cfg = self.regime_config

        if tier == "preferred":
            return cfg["weight_boost"]
        elif tier == "avoid":
            return 0.0  # Avoid = alım yok
        else:
            return 1.0

    def get_max_positions(self) -> int:
        """Mevcut rejime göre max pozisyon sayısı."""
        return self.regime_config["max_positions"]

    def should_buy(self, symbol: str, sector: str = None) -> bool:
        """Bu sektör mevcut rejimde alınabilir mi?"""
        tier = self.get_sector_tier(symbol, sector)
        return tier != "avoid"

    def get_status(self) -> Dict:
        """Mevcut rejim durumu."""
        cfg = self.regime_config
        return {
            "vix": self._last_vix,
            "regime": self._current_regime,
            "max_positions": cfg["max_positions"],
            "preferred_sectors": cfg["preferred"],
            "avoid_sectors": cfg["avoid"],
            "weight_boost": cfg["weight_boost"],
        }
