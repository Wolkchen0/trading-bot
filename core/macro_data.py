"""
Macro Data Module — Makroekonomik Veri Entegrasyonu
FRED API + Fed takvimi + Ekonomik göstergeler

Takip edilen veriler:
  1. Federal Funds Rate (faiz orani)
  2. CPI (tuketici fiyat endeksi — enflasyon)
  3. DXY/USD Index (dolar gucunu etkiler)
  4. 10-Year Treasury Yield
  5. Fed konusma/toplanti takvimi
"""
import os
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logger import logger


MACRO_CONFIG = {
    # FRED API (ucretsiz — fred.stlouisfed.org'dan key alinir)
    "fred_base_url": "https://api.stlouisfed.org/fred/series/observations",

    # Takip edilen FRED serileri
    "series": {
        "FEDFUNDS": {
            "name": "Federal Funds Rate",
            "impact": "Faiz artisi -> Kripto BEARISH, Faiz dususu -> BULLISH",
        },
        "CPIAUCSL": {
            "name": "CPI (Enflasyon)",
            "impact": "Yuksek enflasyon -> Fed sikilasmasi -> BEARISH",
        },
        "DGS10": {
            "name": "10-Yillik Tahvil Getirisi",
            "impact": "Yukselis -> Riskli varliklar duser -> BEARISH",
        },
        "UNRATE": {
            "name": "Issizlik Orani",
            "impact": "Yuksek issizlik -> Fed gevsetir -> BULLISH",
        },
    },

    # Cache
    "cache_hours": 6,  # Makro veri yavas degisir

    # Etki esikleri
    "rate_change_threshold": 0.25,  # %0.25 faiz degisimi onemli
    "cpi_change_threshold": 0.3,    # CPI %0.3 degisimi onemli
}


class MacroDataAnalyzer:
    """Makroekonomik veri analizi — kripto piyasasina etki."""

    def __init__(self):
        self.fred_api_key = os.getenv("FRED_API_KEY", "")
        self.cache = {}
        self.last_fetch = {}

        if self.fred_api_key:
            logger.info("MacroData baslatildi - FRED API aktif")
        else:
            logger.info("MacroData baslatildi - FRED key yok, alternatif kaynaklar")

    # ============================================================
    # 1. FRED VERİ ÇEKME
    # ============================================================

    def get_fred_series(self, series_id: str, limit: int = 5) -> List[Dict]:
        """FRED'den ekonomik seri verisi ceker."""
        cache_key = f"fred_{series_id}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        if not self.fred_api_key:
            return self._get_fallback_data(series_id)

        try:
            params = {
                "series_id": series_id,
                "api_key": self.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            }
            response = requests.get(
                MACRO_CONFIG["fred_base_url"],
                params=params,
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                observations = []
                for obs in data.get("observations", []):
                    try:
                        observations.append({
                            "date": obs["date"],
                            "value": float(obs["value"]),
                        })
                    except (ValueError, KeyError):
                        continue

                self.cache[cache_key] = observations
                self.last_fetch[cache_key] = datetime.now()
                return observations

        except Exception as e:
            logger.debug(f"FRED {series_id} hatasi: {e}")

        return []

    def _get_fallback_data(self, series_id: str) -> List[Dict]:
        """FRED API key yoksa alternatif kaynaklardan veri."""
        cache_key = f"fallback_{series_id}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        try:
            # Alpha Vantage veya diger ucretsiz kaynaklar
            # Treasury Yield alternatif endpoint
            if series_id == "DGS10":
                url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates"
                params = {"sort": "-record_date", "page[size]": "5"}
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    for item in data.get("data", [])[:5]:
                        results.append({
                            "date": item.get("record_date", ""),
                            "value": float(item.get("avg_interest_rate_amt", 0)),
                        })
                    self.cache[cache_key] = results
                    self.last_fetch[cache_key] = datetime.now()
                    return results

        except Exception as e:
            logger.debug(f"Fallback veri hatasi: {e}")

        return []

    # ============================================================
    # 2. FAİZ ANALİZİ
    # ============================================================

    def analyze_interest_rates(self) -> Dict:
        """
        Fed faiz orani analizi.
        Faiz artisi → kripto BEARISH
        Faiz dususu → kripto BULLISH
        """
        data = self.get_fred_series("FEDFUNDS", limit=3)

        if len(data) < 2:
            return {"signal": "NEUTRAL", "score": 0, "rate": None, "change": 0}

        current = data[0]["value"]
        previous = data[1]["value"]
        change = current - previous

        score = 0
        signal = "NEUTRAL"

        if change > MACRO_CONFIG["rate_change_threshold"]:
            # Faiz yukseldi — kripto icin olumsuz
            score = -20
            signal = "BEARISH"
        elif change < -MACRO_CONFIG["rate_change_threshold"]:
            # Faiz dustu — kripto icin olumlu
            score = 20
            signal = "BULLISH"
        elif current > 5.0:
            # Genel yuksek faiz ortami
            score = -10
            signal = "SLIGHTLY_BEARISH"
        elif current < 2.0:
            # Dusuk faiz ortami — risk istahi artar
            score = 10
            signal = "SLIGHTLY_BULLISH"

        return {
            "signal": signal,
            "score": score,
            "rate": current,
            "previous_rate": previous,
            "change": round(change, 3),
            "description": f"Fed Funds Rate: {current}% (degisim: {change:+.3f}%)",
        }

    # ============================================================
    # 3. ENFLASYON ANALİZİ
    # ============================================================

    def analyze_inflation(self) -> Dict:
        """
        CPI / Enflasyon analizi.
        Yuksek enflasyon → Fed sikilasmasi → kripto BEARISH
        Dusen enflasyon → Fed gevsetmesi → kripto BULLISH
        """
        data = self.get_fred_series("CPIAUCSL", limit=3)

        if len(data) < 2:
            return {"signal": "NEUTRAL", "score": 0}

        current = data[0]["value"]
        previous = data[1]["value"]
        change_pct = ((current - previous) / previous) * 100

        score = 0
        signal = "NEUTRAL"

        if change_pct > MACRO_CONFIG["cpi_change_threshold"]:
            score = -15
            signal = "BEARISH"
        elif change_pct < 0:
            score = 15
            signal = "BULLISH"

        return {
            "signal": signal,
            "score": score,
            "cpi": current,
            "change_pct": round(change_pct, 2),
            "description": f"CPI: {current} (degisim: {change_pct:+.2f}%)",
        }

    # ============================================================
    # 4. DOLAR GUCU
    # ============================================================

    def analyze_dollar_strength(self) -> Dict:
        """
        DXY/Dolar gucunu tahmin et.
        Guclu dolar → kripto BEARISH
        Zayif dolar → kripto BULLISH
        """
        data = self.get_fred_series("DGS10", limit=5)

        if len(data) < 2:
            return {"signal": "NEUTRAL", "score": 0}

        current = data[0]["value"]
        previous = data[1]["value"]
        change = current - previous

        score = 0
        signal = "NEUTRAL"

        if change > 0.1:
            score = -10  # Tahvil getirisi artiyor → dolar gucleniyor
            signal = "SLIGHTLY_BEARISH"
        elif change < -0.1:
            score = 10
            signal = "SLIGHTLY_BULLISH"

        return {
            "signal": signal,
            "score": score,
            "yield_10y": current,
            "change": round(change, 3),
            "description": f"10Y Yield: {current}% (degisim: {change:+.3f}%)",
        }

    # ============================================================
    # 5. BİRLEŞTİRİLMİŞ MAKRO SKOR
    # ============================================================

    def get_macro_score(self) -> Dict:
        """
        Tum makroekonomik gostergeleri birlestir.
        Agirliklar: Faiz %40 + Enflasyon %30 + Dolar %30
        """
        rates = self.analyze_interest_rates()
        inflation = self.analyze_inflation()
        dollar = self.analyze_dollar_strength()

        # Agirlikli skor
        total_score = int(
            rates["score"] * 0.40 +
            inflation["score"] * 0.30 +
            dollar["score"] * 0.30
        )

        if total_score >= 15:
            signal = "BULLISH"
        elif total_score >= 5:
            signal = "SLIGHTLY_BULLISH"
        elif total_score <= -15:
            signal = "BEARISH"
        elif total_score <= -5:
            signal = "SLIGHTLY_BEARISH"
        else:
            signal = "NEUTRAL"

        result = {
            "macro_score": total_score,
            "macro_signal": signal,
            "interest_rate": rates,
            "inflation": inflation,
            "dollar": dollar,
        }

        logger.info(
            f"  Makro: Faiz({rates['score']}) "
            f"Enflasyon({inflation['score']}) "
            f"Dolar({dollar['score']}) "
            f"-> Toplam:{total_score} {signal}"
        )

        return result

    # ============================================================
    # CACHE YÖNETİMİ
    # ============================================================

    def _is_cached(self, key: str) -> bool:
        if key not in self.cache or key not in self.last_fetch:
            return False
        elapsed = (datetime.now() - self.last_fetch[key]).total_seconds()
        return elapsed < MACRO_CONFIG["cache_hours"] * 3600
