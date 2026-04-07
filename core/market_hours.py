"""
Market Hours — NYSE/NASDAQ Piyasa Saatleri Kontrolü

US Eastern Time bazlı piyasa durumu:
  - Pre-market:  04:00 - 09:30 ET
  - Regular:     09:30 - 16:00 ET
  - After-hours: 16:00 - 20:00 ET
  - Kapalı:      20:00 - 04:00 ET + Hafta sonu + Tatiller
"""
from datetime import datetime, time, date
from typing import Dict, Tuple
import pytz

from utils.logger import logger

# NYSE tatil günleri (2026)
NYSE_HOLIDAYS_2026 = [
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
]

# 2027 tatilleri (ileriye dönük)
NYSE_HOLIDAYS_2027 = [
    date(2027, 1, 1),   # New Year's Day
    date(2027, 1, 18),  # MLK Day
    date(2027, 2, 15),  # Presidents' Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 7, 5),   # Independence Day (observed)
    date(2027, 9, 6),   # Labor Day
    date(2027, 11, 25), # Thanksgiving
    date(2027, 12, 24), # Christmas (observed)
]

ALL_HOLIDAYS = set(NYSE_HOLIDAYS_2026 + NYSE_HOLIDAYS_2027)

ET = pytz.timezone("US/Eastern")


class MarketHours:
    """NYSE/NASDAQ piyasa saatleri kontrolü."""

    # Saat aralıkları (Eastern Time)
    PRE_MARKET_OPEN = time(4, 0)
    MARKET_OPEN = time(9, 30)
    MARKET_CLOSE = time(16, 0)
    AFTER_HOURS_CLOSE = time(20, 0)

    # Trading güvenli bölge (ilk 30dk volatil, son 15dk riskli)
    SAFE_TRADING_START = time(10, 0)
    SAFE_TRADING_END = time(15, 45)

    def __init__(self):
        logger.info("MarketHours baslatildi — NYSE/NASDAQ saatleri aktif")

    def now_et(self) -> datetime:
        """Şu anki zamanı ET olarak döndür."""
        return datetime.now(ET)

    def get_market_status(self) -> Dict:
        """
        Piyasa durumu:
        Returns:
            {
                'status': 'PRE_MARKET' | 'OPEN' | 'AFTER_HOURS' | 'CLOSED',
                'is_trading_allowed': bool,
                'is_safe_zone': bool,  (volatil açılış/kapanış hariç)
                'next_event': str,
                'time_et': str,
            }
        """
        now = self.now_et()
        current_time = now.time()
        current_date = now.date()
        weekday = now.weekday()  # 0=Mon, 6=Sun

        # Hafta sonu
        if weekday >= 5:
            return {
                "status": "CLOSED",
                "is_trading_allowed": False,
                "is_safe_zone": False,
                "reason": "Hafta sonu",
                "next_event": "Pazartesi 09:30 ET açılış",
                "time_et": now.strftime("%H:%M ET"),
            }

        # Tatil kontrolü
        if current_date in ALL_HOLIDAYS:
            return {
                "status": "CLOSED",
                "is_trading_allowed": False,
                "is_safe_zone": False,
                "reason": "NYSE tatili",
                "next_event": "Sonraki iş günü 09:30 ET açılış",
                "time_et": now.strftime("%H:%M ET"),
            }

        # Pre-market
        if self.PRE_MARKET_OPEN <= current_time < self.MARKET_OPEN:
            return {
                "status": "PRE_MARKET",
                "is_trading_allowed": False,  # Normal modda pre-market'te işlem yok
                "is_safe_zone": False,
                "reason": "Pre-market (sadece olağanüstü fırsatlarda)",
                "next_event": f"Açılış {self.MARKET_OPEN.strftime('%H:%M')} ET",
                "time_et": now.strftime("%H:%M ET"),
            }

        # Regular market
        if self.MARKET_OPEN <= current_time < self.MARKET_CLOSE:
            is_safe = self.SAFE_TRADING_START <= current_time < self.SAFE_TRADING_END
            return {
                "status": "OPEN",
                "is_trading_allowed": True,
                "is_safe_zone": is_safe,
                "reason": "Piyasa açık" + (" (güvenli bölge)" if is_safe else " (volatil bölge)"),
                "next_event": f"Kapanış {self.MARKET_CLOSE.strftime('%H:%M')} ET",
                "time_et": now.strftime("%H:%M ET"),
            }

        # After-hours
        if self.MARKET_CLOSE <= current_time < self.AFTER_HOURS_CLOSE:
            return {
                "status": "AFTER_HOURS",
                "is_trading_allowed": False,  # Normal modda after-hours'da işlem yok
                "is_safe_zone": False,
                "reason": "After-hours (sadece olağanüstü fırsatlarda)",
                "next_event": f"Kapanış {self.AFTER_HOURS_CLOSE.strftime('%H:%M')} ET",
                "time_et": now.strftime("%H:%M ET"),
            }

        # Gece — piyasa tamamen kapalı
        return {
            "status": "CLOSED",
            "is_trading_allowed": False,
            "is_safe_zone": False,
            "reason": "Piyasa kapalı",
            "next_event": "Pre-market 04:00 ET",
            "time_et": now.strftime("%H:%M ET"),
        }

    def is_market_open(self) -> bool:
        """Piyasa açık mı?"""
        return self.get_market_status()["status"] == "OPEN"

    def is_safe_to_trade(self) -> bool:
        """Güvenli bölgede miyiz? (10:00-15:45 ET)"""
        status = self.get_market_status()
        return status["is_trading_allowed"] and status["is_safe_zone"]

    def should_allow_extended_hours(self, signal_confidence: float) -> bool:
        """
        Pre/After market'te işlem yapılmalı mı?
        Sadece çok güçlü sinyallerde (confidence >= 80%) izin ver.
        """
        status = self.get_market_status()
        if status["status"] in ("PRE_MARKET", "AFTER_HOURS"):
            if signal_confidence >= 80:
                logger.warning(
                    f"  EXTENDED HOURS: {status['status']} — "
                    f"Güven %{signal_confidence:.0f} ≥ 80%, işleme izin veriliyor"
                )
                return True
        return False

    def seconds_until_open(self) -> int:
        """Piyasa açılışına kaç saniye var?"""
        now = self.now_et()
        if self.is_market_open():
            return 0
        
        # Bugün açılacaksa
        today_open = now.replace(
            hour=self.MARKET_OPEN.hour,
            minute=self.MARKET_OPEN.minute,
            second=0, microsecond=0
        )
        
        if now < today_open and now.weekday() < 5:
            return int((today_open - now).total_seconds())
        
        # Yarın veya sonraki iş günü
        days_ahead = 1
        while True:
            next_day = now + __import__('datetime').timedelta(days=days_ahead)
            if next_day.weekday() < 5 and next_day.date() not in ALL_HOLIDAYS:
                next_open = next_day.replace(
                    hour=self.MARKET_OPEN.hour,
                    minute=self.MARKET_OPEN.minute,
                    second=0, microsecond=0
                )
                return int((next_open - now).total_seconds())
            days_ahead += 1
            if days_ahead > 7:
                return 86400  # fallback: 1 gün
