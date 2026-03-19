"""
Fundamental Analyzer — Kripto Temel Analiz Modülü
CoinGecko ücretsiz API ile market cap, volume, arz analizi.

Kaynaklar:
  1. CoinGecko API (ücretsiz, key gerekmez, 30 req/dk)
  2. Market Cap değişim analizi
  3. Volume spike tespiti
  4. Circulating/Max Supply oranı
"""
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logger import logger


FUNDAMENTAL_CONFIG = {
    # CoinGecko API
    "coingecko_base": "https://api.coingecko.com/api/v3",

    # Coin ID mapping (Alpaca symbol -> CoinGecko ID)
    "coin_ids": {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "XRP": "ripple",
        "DOGE": "dogecoin",
        "SHIB": "shiba-inu",
        "PEPE": "pepe",
        "LINK": "chainlink",
        "AVAX": "avalanche-2",
        "ADA": "cardano",
        "DOT": "polkadot",
        "LTC": "litecoin",
        "BONK": "bonk",
        "ARB": "arbitrum",
        "UNI": "uniswap",
        "AAVE": "aave",
        "RENDER": "render-token",
        "ONDO": "ondo-finance",
    },

    # Cache
    "cache_minutes": 15,  # CoinGecko rate limit korumasi

    # Eşikler
    "volume_spike_threshold": 2.0,    # 2x volume = spike
    "mcap_change_threshold": 5.0,     # %5 market cap degisim = onemli
    "supply_inflation_risk": 0.50,    # Cir/Max < %50 = enflasyon riski
}


class FundamentalAnalyzer:
    """Kripto temel analiz — CoinGecko verileri."""

    def __init__(self):
        self.cache = {}
        self.last_fetch = {}
        self.global_cache = None
        self.global_cache_time = None
        logger.info("FundamentalAnalyzer baslatildi - CoinGecko API aktif")

    # ============================================================
    # 1. COİN VERİSİ ÇEKME
    # ============================================================

    def get_coin_data(self, coin: str) -> Optional[Dict]:
        """CoinGecko'dan coin detay verisi çeker."""
        cache_key = f"coin_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        coin_id = FUNDAMENTAL_CONFIG["coin_ids"].get(coin)
        if not coin_id:
            return None

        try:
            url = f"{FUNDAMENTAL_CONFIG['coingecko_base']}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "true",
                "developer_data": "false",
                "sparkline": "false",
            }
            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                self.cache[cache_key] = data
                self.last_fetch[cache_key] = datetime.now()
                return data
            elif response.status_code == 429:
                logger.debug("CoinGecko rate limit — bekleniyor")
                time.sleep(30)
            else:
                logger.debug(f"CoinGecko {coin} hatasi: HTTP {response.status_code}")

        except Exception as e:
            logger.debug(f"CoinGecko {coin} veri hatasi: {e}")

        return None

    # ============================================================
    # 2. MARKET CAP ANALİZİ
    # ============================================================

    def analyze_market_cap(self, data: Dict) -> Dict:
        """Market cap değişim analizi."""
        result = {"score": 0, "signal": "NEUTRAL", "mcap": 0, "mcap_change_24h": 0}

        try:
            market = data.get("market_data", {})
            mcap = market.get("market_cap", {}).get("usd", 0)
            mcap_change = market.get("market_cap_change_percentage_24h", 0)

            result["mcap"] = mcap
            result["mcap_change_24h"] = round(mcap_change, 2) if mcap_change else 0

            threshold = FUNDAMENTAL_CONFIG["mcap_change_threshold"]

            if mcap_change and mcap_change > threshold:
                result["score"] = 10
                result["signal"] = "BULLISH"
            elif mcap_change and mcap_change > 0:
                result["score"] = 5
                result["signal"] = "SLIGHTLY_BULLISH"
            elif mcap_change and mcap_change < -threshold:
                result["score"] = -10
                result["signal"] = "BEARISH"
            elif mcap_change and mcap_change < 0:
                result["score"] = -5
                result["signal"] = "SLIGHTLY_BEARISH"

        except Exception as e:
            logger.debug(f"Market cap analiz hatasi: {e}")

        return result

    # ============================================================
    # 3. VOLUME ANALİZİ
    # ============================================================

    def analyze_volume(self, data: Dict) -> Dict:
        """24h volume değişimi ve spike tespiti."""
        result = {"score": 0, "signal": "NEUTRAL", "volume_24h": 0, "volume_spike": False}

        try:
            market = data.get("market_data", {})
            volume = market.get("total_volume", {}).get("usd", 0)
            mcap = market.get("market_cap", {}).get("usd", 1)

            # Volume/Market Cap oranı — yüksek oran = aktif trade
            vol_mcap_ratio = volume / mcap if mcap > 0 else 0

            result["volume_24h"] = volume
            result["vol_mcap_ratio"] = round(vol_mcap_ratio, 4)

            # Volume spike: oran > %20 = çok aktif
            if vol_mcap_ratio > 0.20:
                result["volume_spike"] = True
                result["score"] = 15
                result["signal"] = "HIGH_ACTIVITY"
            elif vol_mcap_ratio > 0.10:
                result["score"] = 5
                result["signal"] = "ACTIVE"
            elif vol_mcap_ratio < 0.02:
                result["score"] = -5
                result["signal"] = "LOW_ACTIVITY"

        except Exception as e:
            logger.debug(f"Volume analiz hatasi: {e}")

        return result

    # ============================================================
    # 4. ARZ ANALİZİ (TOKENOMICS)
    # ============================================================

    def analyze_supply(self, data: Dict) -> Dict:
        """Circulating supply / Max supply analizi."""
        result = {
            "score": 0, "signal": "NEUTRAL",
            "circulating": 0, "max_supply": 0,
            "supply_ratio": 0, "inflation_risk": False,
        }

        try:
            market = data.get("market_data", {})
            circulating = market.get("circulating_supply", 0)
            max_supply = market.get("max_supply")
            total_supply = market.get("total_supply", 0)

            result["circulating"] = circulating

            if max_supply and max_supply > 0:
                ratio = circulating / max_supply
                result["max_supply"] = max_supply
                result["supply_ratio"] = round(ratio, 4)

                # Yüksek dolaşım oranı = düşük enflasyon riski
                if ratio > 0.90:
                    result["score"] = 10
                    result["signal"] = "DEFLATIONARY"
                elif ratio > 0.70:
                    result["score"] = 5
                    result["signal"] = "HEALTHY"
                elif ratio < FUNDAMENTAL_CONFIG["supply_inflation_risk"]:
                    result["inflation_risk"] = True
                    result["score"] = -10
                    result["signal"] = "INFLATION_RISK"
            elif total_supply and total_supply > 0:
                # Max supply yok (sonsuz) ama total var
                result["max_supply"] = None
                result["supply_ratio"] = 0
                result["score"] = -5
                result["signal"] = "UNLIMITED_SUPPLY"

        except Exception as e:
            logger.debug(f"Arz analiz hatasi: {e}")

        return result

    # ============================================================
    # 5. FİYAT DEĞİŞİM ANALİZİ
    # ============================================================

    def analyze_price_momentum(self, data: Dict) -> Dict:
        """Multi-timeframe fiyat değişim analizi."""
        result = {"score": 0, "signal": "NEUTRAL", "changes": {}}

        try:
            market = data.get("market_data", {})

            changes = {
                "1h": market.get("price_change_percentage_1h_in_currency", {}).get("usd", 0),
                "24h": market.get("price_change_percentage_24h", 0),
                "7d": market.get("price_change_percentage_7d", 0),
                "30d": market.get("price_change_percentage_30d", 0),
            }
            result["changes"] = {k: round(v, 2) if v else 0 for k, v in changes.items()}

            # Kısa vade pozitif + uzun vade pozitif = güçlü momentum
            short_term = (changes.get("1h") or 0) + (changes.get("24h") or 0)
            long_term = (changes.get("7d") or 0) + (changes.get("30d") or 0)

            if short_term > 3 and long_term > 5:
                result["score"] = 15
                result["signal"] = "STRONG_MOMENTUM"
            elif short_term > 1 and long_term > 0:
                result["score"] = 8
                result["signal"] = "POSITIVE_MOMENTUM"
            elif short_term < -3 and long_term < -5:
                result["score"] = -15
                result["signal"] = "NEGATIVE_MOMENTUM"
            elif short_term < -1 and long_term < 0:
                result["score"] = -8
                result["signal"] = "WEAK_MOMENTUM"
            # Contrarian: kısa vade düşüş ama uzun vade yükseliş = dip alımı
            elif short_term < -2 and long_term > 5:
                result["score"] = 10
                result["signal"] = "DIP_OPPORTUNITY"

        except Exception as e:
            logger.debug(f"Fiyat momentum hatasi: {e}")

        return result

    # ============================================================
    # 6. TOPLAM PIYASA VERİSİ
    # ============================================================

    def get_global_data(self) -> Dict:
        """Genel kripto piyasa verileri."""
        if (self.global_cache_time and
            (datetime.now() - self.global_cache_time).total_seconds() < 900):
            return self.global_cache or {}

        try:
            url = f"{FUNDAMENTAL_CONFIG['coingecko_base']}/global"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json().get("data", {})
                result = {
                    "total_market_cap": data.get("total_market_cap", {}).get("usd", 0),
                    "total_volume": data.get("total_volume", {}).get("usd", 0),
                    "market_cap_change_24h": data.get("market_cap_change_percentage_24h_usd", 0),
                    "btc_dominance": data.get("market_cap_percentage", {}).get("btc", 0),
                    "eth_dominance": data.get("market_cap_percentage", {}).get("eth", 0),
                    "active_cryptos": data.get("active_cryptocurrencies", 0),
                }
                self.global_cache = result
                self.global_cache_time = datetime.now()
                return result

        except Exception as e:
            logger.debug(f"Global veri hatasi: {e}")

        return {}

    # ============================================================
    # 7. BİRLEŞTİRİLMİŞ FUNDAMENTAL SKOR
    # ============================================================

    def get_fundamental_score(self, symbol: str) -> Dict:
        """
        Bir coin için tüm fundamental metrikleri birleştir.

        Ağırlıklar:
          Market Cap değişim: %25
          Volume analiz: %20
          Arz analizi: %15
          Fiyat momentum: %25
          Global piyasa: %15
        """
        coin = symbol.replace("/USD", "").replace("USD", "")

        # CoinGecko verisi çek
        data = self.get_coin_data(coin)
        if not data:
            return {
                "fundamental_score": 0,
                "fundamental_signal": "NEUTRAL",
                "details": "Veri alinamadi",
            }

        # Alt analizler
        mcap = self.analyze_market_cap(data)
        volume = self.analyze_volume(data)
        supply = self.analyze_supply(data)
        momentum = self.analyze_price_momentum(data)
        global_data = self.get_global_data()

        # Global piyasa skoru
        global_score = 0
        global_change = global_data.get("market_cap_change_24h", 0)
        if global_change:
            if global_change > 3:
                global_score = 10
            elif global_change > 0:
                global_score = 5
            elif global_change < -3:
                global_score = -10
            elif global_change < 0:
                global_score = -5

        # Ağırlıklı toplam skor
        total_score = int(
            mcap["score"] * 0.25 +
            volume["score"] * 0.20 +
            supply["score"] * 0.15 +
            momentum["score"] * 0.25 +
            global_score * 0.15
        )

        # Sinyal
        if total_score >= 10:
            signal = "STRONG_BUY"
        elif total_score >= 5:
            signal = "BUY"
        elif total_score <= -10:
            signal = "STRONG_SELL"
        elif total_score <= -5:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        result = {
            "fundamental_score": total_score,
            "fundamental_signal": signal,
            "mcap_score": mcap["score"],
            "mcap_change_24h": mcap["mcap_change_24h"],
            "volume_score": volume["score"],
            "volume_spike": volume.get("volume_spike", False),
            "supply_score": supply["score"],
            "supply_ratio": supply.get("supply_ratio", 0),
            "inflation_risk": supply.get("inflation_risk", False),
            "momentum_score": momentum["score"],
            "momentum_signal": momentum.get("signal", "NEUTRAL"),
            "price_changes": momentum.get("changes", {}),
            "global_score": global_score,
            "btc_dominance": global_data.get("btc_dominance", 0),
        }

        logger.info(
            f"  Fundamental {coin}: MCap({mcap['score']}) "
            f"Vol({volume['score']}) Arz({supply['score']}) "
            f"Mom({momentum['score']}) Global({global_score}) "
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
        return elapsed < FUNDAMENTAL_CONFIG["cache_minutes"] * 60
