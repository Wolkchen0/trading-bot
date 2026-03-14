"""
Kripto Haber Takip & Duygu Analizi Modülü
- CryptoPanic API (ücretsiz)
- Fear & Greed Index (ücretsiz)
- Anahtar kelime bazlı duygu analizi
- Haber skoru trade sinyallerine etki eder
"""
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logger import logger


# ============================================================
# HABER KONFİGÜRASYONU
# ============================================================
NEWS_CONFIG = {
    # Duygu analizi anahtar kelimeleri
    "bullish_keywords": [
        # Genel pozitif
        "surge", "soar", "rally", "pump", "moon", "breakout", "bullish",
        "all-time high", "ath", "record high", "skyrocket", "boom",
        "adoption", "partnership", "institutional", "approval",
        # ETF & Düzenleme pozitif
        "etf approved", "sec approval", "regulation clarity",
        "spot etf", "bitcoin etf",
        # Kurumsal alım
        "tesla buys", "microstrategy", "institutional buy",
        "whale accumulation", "large purchase",
        # Teknoloji pozitif
        "upgrade", "launch", "mainnet", "halving", "burn",
        "staking rewards", "defi growth",
        # Yükseliş (Türkçe)
        "yukselis", "rekor", "artis", "boğa", "patlama",
    ],
    "bearish_keywords": [
        # Genel negatif
        "crash", "dump", "plunge", "collapse", "bearish", "sell-off",
        "liquidation", "fear", "panic", "tumble", "drop", "decline",
        "bloodbath", "capitulation", "correction",
        # Düzenleme negatif
        "ban", "crackdown", "lawsuit", "sec sues", "regulation",
        "china ban", "restrict", "illegal", "fraud", "scam",
        # Hack & Güvenlik
        "hack", "exploit", "breach", "stolen", "rug pull",
        "vulnerability", "attack", "compromised",
        # Ekonomi negatif
        "recession", "inflation", "rate hike", "fed hawkish",
        "bankruptcy", "insolvent", "ftx", "terra luna",
        # Düşüş (Türkçe)
        "dusus", "cokus", "ayı", "panik", "kayip",
    ],
    "high_impact_keywords": [
        # Bu kelimeler varsa etki x2
        "breaking", "just in", "urgent", "flash",
        "elon musk", "trump", "sec", "fed", "federal reserve",
        "binance", "coinbase", "blackrock", "grayscale",
    ],

    # Coin-spesifik haber takibi
    "coin_keywords": {
        "BTC": ["bitcoin", "btc", "satoshi"],
        "ETH": ["ethereum", "eth", "vitalik"],
        "SOL": ["solana", "sol"],
        "XRP": ["ripple", "xrp", "sec lawsuit"],
        "DOGE": ["dogecoin", "doge", "elon", "musk"],
        "SHIB": ["shiba", "shib", "shibarium"],
        "PEPE": ["pepe", "memecoin"],
        "LINK": ["chainlink", "link", "oracle"],
        "AVAX": ["avalanche", "avax"],
        "ADA": ["cardano", "ada"],
        "DOT": ["polkadot", "dot"],
        "TRUMP": ["trump coin", "trump crypto"],
    },

    # API ayarları
    "cryptopanic_url": "https://cryptopanic.com/api/free/v1/posts/",
    "fear_greed_url": "https://api.alternative.me/fng/",
    "news_cache_minutes": 5,        # Her 5 dakikada haber güncelle
    "max_news_age_hours": 4,         # Son 4 saatteki haberler
}


class NewsAnalyzer:
    """Kripto haber takip ve duygu analizi."""

    def __init__(self):
        self.cache = {}
        self.last_fetch_time = None
        self.fear_greed_cache = None
        self.fear_greed_time = None
        logger.info("NewsAnalyzer baslatildi - Haber takibi aktif")

    # ============================================================
    # FEAR & GREED INDEX
    # ============================================================

    def get_fear_greed_index(self) -> Dict:
        """
        Kripto Fear & Greed Index (0-100)
        0-24:  Extreme Fear (aşırı korku → alım fırsatı olabilir)
        25-49: Fear (korku)
        50:    Neutral
        51-74: Greed (açgözlülük)
        75-100: Extreme Greed (aşırı açgözlülük → satış sinyali)
        """
        # Cache kontrolü (saatte 1 güncelle)
        if (self.fear_greed_time and
            (datetime.now() - self.fear_greed_time).total_seconds() < 3600):
            return self.fear_greed_cache

        try:
            response = requests.get(
                NEWS_CONFIG["fear_greed_url"],
                timeout=10
            )
            data = response.json()

            if data.get("data"):
                fg = data["data"][0]
                result = {
                    "value": int(fg["value"]),
                    "label": fg["value_classification"],
                    "timestamp": fg.get("timestamp", ""),
                }

                # Sinyal üret
                value = result["value"]
                if value <= 20:
                    result["signal"] = "STRONG_BUY"
                    result["score"] = 40  # Aşırı korku = alım fırsatı
                elif value <= 35:
                    result["signal"] = "BUY"
                    result["score"] = 20
                elif value <= 65:
                    result["signal"] = "NEUTRAL"
                    result["score"] = 0
                elif value <= 80:
                    result["signal"] = "SELL"
                    result["score"] = -20
                else:
                    result["signal"] = "STRONG_SELL"
                    result["score"] = -40  # Aşırı açgözlülük = satış sinyali

                self.fear_greed_cache = result
                self.fear_greed_time = datetime.now()

                logger.info(
                    f"  Fear&Greed: {value} ({result['label']}) "
                    f"-> {result['signal']}"
                )
                return result

        except Exception as e:
            logger.error(f"Fear&Greed alinamadi: {e}")

        return {"value": 50, "label": "Neutral", "signal": "NEUTRAL", "score": 0}

    # ============================================================
    # HABER ÇEKME
    # ============================================================

    def fetch_news(self) -> List[Dict]:
        """CryptoPanic'ten ücretsiz haber çek."""
        # Cache kontrolü
        if (self.last_fetch_time and
            (datetime.now() - self.last_fetch_time).total_seconds()
            < NEWS_CONFIG["news_cache_minutes"] * 60):
            return self.cache.get("news", [])

        news_items = []

        # Kaynak 1: CryptoPanic (ücretsiz, auth_token gerekmez)
        try:
            response = requests.get(
                NEWS_CONFIG["cryptopanic_url"],
                params={"auth_token": "free", "public": "true"},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                for item in data.get("results", [])[:20]:
                    news_items.append({
                        "title": item.get("title", ""),
                        "source": item.get("source", {}).get("title", "unknown"),
                        "url": item.get("url", ""),
                        "published": item.get("published_at", ""),
                        "currencies": [
                            c.get("code", "") for c in item.get("currencies", [])
                        ] if item.get("currencies") else [],
                        "votes": item.get("votes", {}),
                    })
        except Exception as e:
            logger.debug(f"CryptoPanic haberleri alinamadi: {e}")

        # Kaynak 2: CoinGecko Status Updates (ücretsiz)
        try:
            cg_response = requests.get(
                "https://api.coingecko.com/api/v3/search/trending",
                timeout=10
            )
            if cg_response.status_code == 200:
                trending = cg_response.json()
                for coin in trending.get("coins", [])[:7]:
                    item = coin.get("item", {})
                    news_items.append({
                        "title": f"Trending: {item.get('name', '')} ({item.get('symbol', '')}) - "
                                 f"Rank #{item.get('market_cap_rank', 'N/A')}",
                        "source": "CoinGecko Trending",
                        "url": "",
                        "published": datetime.now().isoformat(),
                        "currencies": [item.get("symbol", "").upper()],
                        "votes": {},
                    })
        except Exception as e:
            logger.debug(f"CoinGecko trending alinamadi: {e}")

        self.cache["news"] = news_items
        self.last_fetch_time = datetime.now()

        if news_items:
            logger.info(f"  Haberler: {len(news_items)} haber alindi")

        return news_items

    # ============================================================
    # DUYGU ANALİZİ
    # ============================================================

    def analyze_sentiment(self, text: str) -> Dict:
        """
        Metin bazlı duygu analizi.
        Her habere -100 (çok negatif) ile +100 (çok pozitif) arası skor verir.
        """
        text_lower = text.lower()
        score = 0
        matched_keywords = []
        is_high_impact = False

        # Yüksek etki kontrolü
        for keyword in NEWS_CONFIG["high_impact_keywords"]:
            if keyword in text_lower:
                is_high_impact = True
                break

        # Pozitif kelime kontrolü
        for keyword in NEWS_CONFIG["bullish_keywords"]:
            if keyword in text_lower:
                score += 15
                matched_keywords.append(f"+{keyword}")

        # Negatif kelime kontrolü
        for keyword in NEWS_CONFIG["bearish_keywords"]:
            if keyword in text_lower:
                score -= 15
                matched_keywords.append(f"-{keyword}")

        # Yüksek etkili haberlerde skoru 2x yap
        if is_high_impact and score != 0:
            score *= 2

        # Skoru -100 ile +100 arasında sınırla
        score = max(-100, min(100, score))

        if score > 20:
            sentiment = "BULLISH"
        elif score > 0:
            sentiment = "SLIGHTLY_BULLISH"
        elif score < -20:
            sentiment = "BEARISH"
        elif score < 0:
            sentiment = "SLIGHTLY_BEARISH"
        else:
            sentiment = "NEUTRAL"

        return {
            "score": score,
            "sentiment": sentiment,
            "keywords": matched_keywords,
            "high_impact": is_high_impact,
        }

    # ============================================================
    # COİN-SPESİFİK ANALİZ
    # ============================================================

    def get_coin_sentiment(self, symbol: str) -> Dict:
        """
        Belirli bir coin için haber duygu analizi.
        Trading sinyaline eklenir.
        """
        # Coin sembolünü çıkar (BTC/USD -> BTC)
        coin = symbol.replace("/USD", "").replace("USD", "")

        # Fear & Greed (genel piyasa)
        fg = self.get_fear_greed_index()

        # Haberler
        news = self.fetch_news()

        # Coin ile ilgili haberleri filtrele
        coin_keywords = NEWS_CONFIG["coin_keywords"].get(coin, [coin.lower()])
        relevant_news = []
        total_score = 0

        for item in news:
            title = item["title"].lower()
            currencies = [c.upper() for c in item.get("currencies", [])]

            # Bu coin ile ilgili mi?
            is_relevant = (
                coin in currencies or
                any(kw in title for kw in coin_keywords)
            )

            if is_relevant:
                sentiment = self.analyze_sentiment(item["title"])
                relevant_news.append({
                    "title": item["title"][:80],
                    "source": item["source"],
                    "sentiment": sentiment["sentiment"],
                    "score": sentiment["score"],
                })
                total_score += sentiment["score"]

        # Genel piyasa haberleri (coin-spesifik değil)
        general_score = 0
        for item in news[:10]:  # İlk 10 haber genel etki
            sentiment = self.analyze_sentiment(item["title"])
            general_score += sentiment["score"]
        general_score = general_score // max(len(news[:10]), 1)

        # Toplam haber skoru hesapla
        # = Coin-spesifik haberler (%60) + Genel piyasa (%20) + Fear&Greed (%20)
        if relevant_news:
            coin_avg = total_score // len(relevant_news)
        else:
            coin_avg = 0

        final_score = int(
            coin_avg * 0.6 +
            general_score * 0.2 +
            fg["score"] * 0.2
        )

        # Sinyal üret
        if final_score >= 30:
            signal = "STRONG_BUY"
        elif final_score >= 10:
            signal = "BUY"
        elif final_score <= -30:
            signal = "STRONG_SELL"
        elif final_score <= -10:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        result = {
            "coin": coin,
            "news_score": final_score,
            "news_signal": signal,
            "fear_greed": fg["value"],
            "fear_greed_label": fg["label"],
            "relevant_news_count": len(relevant_news),
            "relevant_news": relevant_news[:5],  # En fazla 5 haber göster
            "general_market_score": general_score,
        }

        if relevant_news:
            logger.info(
                f"  Haber {coin}: {len(relevant_news)} haber, "
                f"Skor: {final_score}, Sinyal: {signal} | "
                f"F&G: {fg['value']} ({fg['label']})"
            )

        return result

    # ============================================================
    # TÜM PİYASA ÖZETİ
    # ============================================================

    def get_market_summary(self) -> Dict:
        """Genel piyasa duygu durumu özeti."""
        fg = self.get_fear_greed_index()
        news = self.fetch_news()

        # Tüm haberler üzerinde duygu analizi
        total_bullish = 0
        total_bearish = 0
        total_neutral = 0

        for item in news:
            sentiment = self.analyze_sentiment(item["title"])
            if sentiment["score"] > 0:
                total_bullish += 1
            elif sentiment["score"] < 0:
                total_bearish += 1
            else:
                total_neutral += 1

        total = max(len(news), 1)

        return {
            "fear_greed": fg,
            "news_count": len(news),
            "bullish_pct": round(total_bullish / total * 100, 1),
            "bearish_pct": round(total_bearish / total * 100, 1),
            "neutral_pct": round(total_neutral / total * 100, 1),
            "overall": "BULLISH" if total_bullish > total_bearish else
                       "BEARISH" if total_bearish > total_bullish else "NEUTRAL",
        }
