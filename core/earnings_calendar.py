"""
Earnings Calendar — Kazanç Takvimi Takibi

Earnings (kazanç raporu) çevresinde hisse fiyatları çok volatil olur.
Bu modül:
  1. Yaklaşan earnings raporlarını takip eder
  2. Earnings öncesi 2 gün → yeni pozisyon açmayı engeller
  3. Earnings sonrası gap analizi yapar
  4. Alpha Vantage veya Yahoo Finance'den veri çeker
"""
import os
import requests
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from utils.logger import logger


class EarningsCalendar:
    """Earnings takvimi takibi ve earnings-aware trading."""

    def __init__(self):
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_KEY", "")
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 3600 * 12  # 12 saat cache (earnings nadiren değişir)
        
        if self.alpha_vantage_key:
            logger.info("EarningsCalendar baslatildi — Alpha Vantage API aktif")
        else:
            logger.info("EarningsCalendar baslatildi — API key yok, temel mod")

    def get_upcoming_earnings(self, symbol: str) -> Optional[Dict]:
        """
        Hissenin yaklaşan earnings raporunu kontrol et.
        
        Returns:
            {
                'date': str,  # earnings tarihi
                'days_until': int,
                'estimate_eps': float,  # beklenen EPS
                'is_near': bool,  # 2 gün içinde mi
            }
            veya None (veri yok)
        """
        cache_key = f"earnings_{symbol}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        result = None

        # Alpha Vantage ile dene
        if self.alpha_vantage_key:
            result = self._fetch_alpha_vantage(symbol)

        # Fallback: Yahoo Finance
        if result is None:
            result = self._fetch_yahoo_fallback(symbol)

        if result:
            self.cache[cache_key] = result
            self.cache_time[cache_key] = datetime.now()

        return result

    def _fetch_alpha_vantage(self, symbol: str) -> Optional[Dict]:
        """Alpha Vantage Earnings Calendar endpoint."""
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "EARNINGS",
                "symbol": symbol,
                "apikey": self.alpha_vantage_key,
            }
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # Quarterly earnings
                quarterly = data.get("quarterlyEarnings", [])
                if not quarterly:
                    return None

                # Bir sonraki beklenen tarihi tahmin et
                # (Alpha Vantage geçmiş veriyor, bir sonraki çeyrek ~90 gün sonra)
                last_date = quarterly[0].get("reportedDate", "")
                if last_date:
                    last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
                    next_dt = last_dt + timedelta(days=90)  # tahmini
                    days_until = (next_dt - date.today()).days

                    return {
                        "date": next_dt.isoformat(),
                        "days_until": max(days_until, 0),
                        "estimate_eps": float(quarterly[0].get("estimatedEPS", 0) or 0),
                        "actual_eps": float(quarterly[0].get("reportedEPS", 0) or 0),
                        "surprise_pct": float(quarterly[0].get("surprisePercentage", 0) or 0),
                        "is_near": 0 <= days_until <= 2,
                        "source": "alpha_vantage",
                    }

        except Exception as e:
            logger.debug(f"Alpha Vantage earnings hatası {symbol}: {e}")
        return None

    def _fetch_yahoo_fallback(self, symbol: str) -> Optional[Dict]:
        """Yahoo Finance earnings fallback (sayfa scraping)."""
        try:
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
            params = {"modules": "calendarEvents"}
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                events = data.get("quoteSummary", {}).get("result", [{}])[0]
                calendar = events.get("calendarEvents", {}).get("earnings", {})
                
                earnings_date_raw = calendar.get("earningsDate", [{}])
                if earnings_date_raw:
                    ts = earnings_date_raw[0].get("raw", 0)
                    if ts > 0:
                        earnings_dt = datetime.fromtimestamp(ts).date()
                        days_until = (earnings_dt - date.today()).days
                        
                        return {
                            "date": earnings_dt.isoformat(),
                            "days_until": max(days_until, 0),
                            "estimate_eps": calendar.get("earningsAverage", {}).get("raw", 0),
                            "is_near": 0 <= days_until <= 2,
                            "source": "yahoo",
                        }
        except Exception as e:
            logger.debug(f"Yahoo earnings hatası {symbol}: {e}")
        return None

    def should_avoid_trading(self, symbol: str) -> tuple:
        """
        Earnings yakınsa trading'den kaçınılmalı mı?
        
        Returns:
            (should_avoid: bool, reason: str)
        """
        earnings = self.get_upcoming_earnings(symbol)
        
        if earnings is None:
            return False, "Earnings verisi bulunamadı, trading serbest"
        
        days = earnings.get("days_until", 999)
        
        if days <= 0:
            return True, f"EARNINGS BUGÜN! {symbol} — çok volatil, trading durduruldu"
        elif days <= 1:
            return True, f"Earnings YARIN! {symbol} — yeni pozisyon açma"
        elif days <= 2:
            return True, f"Earnings {days} gün içinde! {symbol} — dikkatli ol"
        
        return False, f"Earnings {days} gün sonra, trading serbest"

    def _is_cached(self, key: str) -> bool:
        if key not in self.cache or key not in self.cache_time:
            return False
        elapsed = (datetime.now() - self.cache_time[key]).total_seconds()
        return elapsed < self.cache_duration
