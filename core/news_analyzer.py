"""
Kripto Haber Takip & Gelişmiş Duygu Analizi Modülü
- CryptoPanic API (ücretsiz)
- Fear & Greed Index (ücretsiz)
- Anahtar kelime bazlı duygu analizi
- Multi-timeframe sentiment analizi (YENİ)
- Contrarian sinyaller (YENİ)
- Zaman ağırlıklı haber skoru (YENİ)
"""
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logger import logger
from core.social_sentiment import SocialSentimentAnalyzer


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
        # Duzenleme negatif
        "ban", "crackdown", "lawsuit", "sec sues", "regulation",
        "china ban", "restrict", "illegal", "fraud", "scam",
        # Hack & Guvenlik
        "hack", "exploit", "breach", "stolen", "rug pull",
        "vulnerability", "attack", "compromised",
        # Ekonomi negatif
        "recession", "inflation", "rate hike", "fed hawkish",
        "bankruptcy", "insolvent", "ftx", "terra luna",
        # JEOPOLITIK KRIZ
        "war escalat", "military strike", "missile", "strait of hormuz",
        "oil surge", "oil spike", "sanctions", "embargo",
        "nuclear", "invasion", "bombing", "retaliati",
        "economic collapse", "supply disruption",
        # Dusus (Turkce)
        "dusus", "cokus", "panik", "kayip", "savas",
    ],
    "high_impact_keywords": [
        # Bu kelimeler varsa etki x2
        "breaking", "just in", "urgent", "flash",
        "elon musk", "trump", "sec", "fed", "federal reserve",
        "binance", "coinbase", "blackrock", "grayscale",
        # JEOPOLITIK
        "iran", "israel", "hormuz", "oil price", "crude oil",
        "ceasefire", "ateskes", "peace deal", "war",
        "pentagon", "military", "strait",
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
    "news_cache_minutes": 5,
    "max_news_age_hours": 4,

    # Zaman ağırlığı (YENİ)
    "time_decay": {
        "1h": 1.0,    # Son 1 saat: tam ağırlık
        "4h": 0.5,    # 1-4 saat: yarı ağırlık
        "24h": 0.25,  # 4-24 saat: çeyrek ağırlık
    },
}


class NewsAnalyzer:
    """Gelişmiş kripto haber takip ve duygu analizi."""

    def __init__(self):
        self.cache = {}
        self.last_fetch_time = None
        self.fear_greed_cache = None
        self.fear_greed_time = None
        self.social = SocialSentimentAnalyzer()
        logger.info("NewsAnalyzer baslatildi - Haber + Sosyal + Contrarian aktif")

    # ============================================================
    # FEAR & GREED INDEX (GELİŞTİRİLMİŞ — CONTRARİAN SİNYAL)
    # ============================================================

    def get_fear_greed_index(self) -> Dict:
        """
        Kripto Fear & Greed Index (0-100)
        CONTRARIAN STRATEJİ:
          0-15:  Extreme Fear → STRONG_BUY (herkes satarken al!)
          16-25: Fear → BUY (korku = fırsat)
          26-45: Mild Fear → SLIGHTLY_BULLISH
          46-55: Neutral
          56-74: Greed → SLIGHTLY_BEARISH
          75-85: High Greed → SELL
          86-100: Extreme Greed → STRONG_SELL (herkes alırken sat!)
        """
        if (self.fear_greed_time and
            (datetime.now() - self.fear_greed_time).total_seconds() < 3600):
            return self.fear_greed_cache

        try:
            # Son 7 günlük F&G verisi (trend için)
            response = requests.get(
                NEWS_CONFIG["fear_greed_url"],
                params={"limit": 7},
                timeout=10
            )
            data = response.json()

            if data.get("data"):
                fg = data["data"][0]
                value = int(fg["value"])

                # Son 7 gün trendi
                fg_values = [int(d["value"]) for d in data["data"][:7]]
                fg_avg_7d = sum(fg_values) / len(fg_values) if fg_values else value
                fg_trend = value - fg_avg_7d  # Pozitif = iyileşme, negatif = kötüleşme

                result = {
                    "value": value,
                    "label": fg["value_classification"],
                    "timestamp": fg.get("timestamp", ""),
                    "avg_7d": round(fg_avg_7d, 1),
                    "trend": round(fg_trend, 1),
                }

                # GELİŞTİRİLMİŞ CONTRARIAN SİNYAL
                if value <= 15:
                    result["signal"] = "STRONG_BUY"
                    result["score"] = 40  # Extreme Fear = büyük alım fırsatı
                elif value <= 25:
                    result["signal"] = "BUY"
                    result["score"] = 25
                elif value <= 45:
                    result["signal"] = "SLIGHTLY_BULLISH"
                    result["score"] = 10
                elif value <= 55:
                    result["signal"] = "NEUTRAL"
                    result["score"] = 0
                elif value <= 74:
                    result["signal"] = "SLIGHTLY_BEARISH"
                    result["score"] = -10
                elif value <= 85:
                    result["signal"] = "SELL"
                    result["score"] = -25
                else:
                    result["signal"] = "STRONG_SELL"
                    result["score"] = -40

                # Trend bonusu: F&G iyileşiyorsa ekstra puan
                if fg_trend > 10:
                    result["score"] += 5
                    result["trend_signal"] = "IMPROVING"
                elif fg_trend < -10:
                    result["score"] -= 5
                    result["trend_signal"] = "WORSENING"
                else:
                    result["trend_signal"] = "STABLE"

                self.fear_greed_cache = result
                self.fear_greed_time = datetime.now()

                logger.info(
                    f"  Fear&Greed: {value} ({result['label']}) "
                    f"7d_avg:{fg_avg_7d:.0f} trend:{fg_trend:+.0f} "
                    f"-> {result['signal']} (skor:{result['score']})"
                )
                return result

        except Exception as e:
            logger.error(f"Fear&Greed alinamadi: {e}")

        return {"value": 50, "label": "Neutral", "signal": "NEUTRAL", "score": 0,
                "avg_7d": 50, "trend": 0, "trend_signal": "STABLE"}

    # ============================================================
    # HABER ÇEKME
    # ============================================================

    def fetch_news(self) -> List[Dict]:
        """CryptoPanic + CoinGecko'dan haber çek."""
        if (self.last_fetch_time and
            (datetime.now() - self.last_fetch_time).total_seconds()
            < NEWS_CONFIG["news_cache_minutes"] * 60):
            return self.cache.get("news", [])

        news_items = []

        # Kaynak 1: CryptoPanic
        try:
            response = requests.get(
                NEWS_CONFIG["cryptopanic_url"],
                params={"auth_token": "free", "public": "true"},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                for item in data.get("results", [])[:20]:
                    published = item.get("published_at", "")
                    news_items.append({
                        "title": item.get("title", ""),
                        "source": item.get("source", {}).get("title", "unknown"),
                        "url": item.get("url", ""),
                        "published": published,
                        "published_dt": self._parse_datetime(published),
                        "currencies": [
                            c.get("code", "") for c in item.get("currencies", [])
                        ] if item.get("currencies") else [],
                        "votes": item.get("votes", {}),
                    })
        except Exception as e:
            logger.debug(f"CryptoPanic haberleri alinamadi: {e}")

        # Kaynak 2: CoinGecko Trending
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
                        "published_dt": datetime.now(),
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
    # DUYGU ANALİZİ (ZAMAN AĞIRLIKLI)
    # ============================================================

    def analyze_sentiment(self, text: str, published_dt: Optional[datetime] = None) -> Dict:
        """
        Zaman ağırlıklı duygu analizi.
        Taze haberler daha etkili, eski haberler azalan ağırlığa sahip.
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

        # Yüksek etkili haberlerde skoru 2x
        if is_high_impact and score != 0:
            score *= 2

        # ZAMAN AĞIRLIĞI (YENİ)
        time_weight = 1.0
        if published_dt:
            try:
                age_hours = (datetime.now() - published_dt).total_seconds() / 3600
                if age_hours <= 1:
                    time_weight = NEWS_CONFIG["time_decay"]["1h"]
                elif age_hours <= 4:
                    time_weight = NEWS_CONFIG["time_decay"]["4h"]
                else:
                    time_weight = NEWS_CONFIG["time_decay"]["24h"]
            except Exception:
                pass

        score = int(score * time_weight)
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
            "time_weight": time_weight,
        }

    # ============================================================
    # MULTI-TIMEFRAME SENTIMENT (YENİ)
    # ============================================================

    def get_multi_timeframe_sentiment(self, news: List[Dict], coin_keywords: List[str]) -> Dict:
        """
        Farklı zaman dilimlerinde sentiment analizi.
        Kısa vade sentiment uzun vadeden farklıysa → momentum değişimi.
        """
        now = datetime.now()
        sentiments = {"1h": [], "4h": [], "24h": []}

        for item in news:
            title = item["title"].lower()

            # Genel piyasa haberi mi yoksa coin-spesifik mi?
            is_relevant = any(kw in title for kw in coin_keywords) or not coin_keywords

            if not is_relevant:
                continue

            published_dt = item.get("published_dt")
            if not published_dt:
                continue

            try:
                age_hours = (now - published_dt).total_seconds() / 3600
            except Exception:
                continue

            sent = self.analyze_sentiment(item["title"], published_dt)

            if age_hours <= 1:
                sentiments["1h"].append(sent["score"])
            if age_hours <= 4:
                sentiments["4h"].append(sent["score"])
            if age_hours <= 24:
                sentiments["24h"].append(sent["score"])

        # Ortalama hesapla
        result = {}
        for tf, scores in sentiments.items():
            if scores:
                avg = sum(scores) / len(scores)
                result[f"sentiment_{tf}"] = round(avg, 1)
                result[f"count_{tf}"] = len(scores)
            else:
                result[f"sentiment_{tf}"] = 0
                result[f"count_{tf}"] = 0

        # Momentum değişimi tespiti
        s1h = result.get("sentiment_1h", 0)
        s4h = result.get("sentiment_4h", 0)
        s24h = result.get("sentiment_24h", 0)

        if s1h > s4h + 10 and s1h > 0:
            result["momentum_shift"] = "IMPROVING"
            result["shift_score"] = 10
        elif s1h < s4h - 10 and s1h < 0:
            result["momentum_shift"] = "DETERIORATING"
            result["shift_score"] = -10
        else:
            result["momentum_shift"] = "STABLE"
            result["shift_score"] = 0

        return result

    # ============================================================
    # COİN-SPESİFİK ANALİZ (GELİŞTİRİLMİŞ)
    # ============================================================

    def get_coin_sentiment(self, symbol: str) -> Dict:
        """Gelişmiş coin sentiment analizi — multi-timeframe + contrarian."""
        coin = symbol.replace("/USD", "").replace("USD", "")

        # Fear & Greed (contrarian)
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

            is_relevant = (
                coin in currencies or
                any(kw in title for kw in coin_keywords)
            )

            if is_relevant:
                sentiment = self.analyze_sentiment(
                    item["title"],
                    item.get("published_dt")
                )
                relevant_news.append({
                    "title": item["title"][:80],
                    "source": item["source"],
                    "sentiment": sentiment["sentiment"],
                    "score": sentiment["score"],
                    "time_weight": sentiment["time_weight"],
                })
                total_score += sentiment["score"]

        # Genel piyasa haberleri
        general_score = 0
        for item in news[:10]:
            sentiment = self.analyze_sentiment(item["title"], item.get("published_dt"))
            general_score += sentiment["score"]
        general_score = general_score // max(len(news[:10]), 1)

        # Multi-timeframe sentiment (YENİ)
        mt_sentiment = self.get_multi_timeframe_sentiment(news, coin_keywords)

        # Sosyal medya analizi
        try:
            social_data = self.social.get_social_score(symbol)
            social_score = social_data["social_score"]
        except Exception as e:
            logger.debug(f"Sosyal analiz hatasi: {e}")
            social_data = {"social_score": 0, "social_signal": "NEUTRAL"}
            social_score = 0

        # GELİŞTİRİLMİŞ TOPLAM SKOR
        # = Coin haberler %30 + Sosyal medya %25 + Genel piyasa %10
        # + F&G Contrarian %20 + Multi-timeframe momentum %15
        if relevant_news:
            coin_avg = total_score // len(relevant_news)
        else:
            coin_avg = 0

        mt_shift_score = mt_sentiment.get("shift_score", 0)

        final_score = int(
            coin_avg * 0.30 +
            social_score * 0.25 +
            general_score * 0.10 +
            fg["score"] * 0.20 +
            mt_shift_score * 0.15
        )

        # Sinyal
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
            "fg_trend": fg.get("trend", 0),
            "fg_contrarian_score": fg["score"],
            "relevant_news_count": len(relevant_news),
            "relevant_news": relevant_news[:5],
            "general_market_score": general_score,
            "social_score": social_score,
            "social_signal": social_data.get("social_signal", "NEUTRAL"),
            "reddit_posts": social_data.get("reddit_posts", 0),
            "coingecko_trending": social_data.get("coingecko_trending", False),
            # Multi-timeframe (YENİ)
            "sentiment_1h": mt_sentiment.get("sentiment_1h", 0),
            "sentiment_4h": mt_sentiment.get("sentiment_4h", 0),
            "sentiment_24h": mt_sentiment.get("sentiment_24h", 0),
            "momentum_shift": mt_sentiment.get("momentum_shift", "STABLE"),
        }

        if relevant_news or social_score != 0:
            logger.info(
                f"  Analiz {coin}: Haber({len(relevant_news)}) "
                f"Sosyal(skor:{social_score}) "
                f"F&G:{fg['value']}({fg.get('trend_signal','?')}) "
                f"Shift:{mt_sentiment.get('momentum_shift','?')} "
                f"-> Toplam:{final_score} {signal}"
            )

        return result

    # ============================================================
    # TÜM PİYASA ÖZETİ
    # ============================================================

    def get_market_summary(self) -> Dict:
        """Genel piyasa duygu durumu özeti."""
        fg = self.get_fear_greed_index()
        news = self.fetch_news()

        total_bullish = 0
        total_bearish = 0
        total_neutral = 0

        for item in news:
            sentiment = self.analyze_sentiment(item["title"], item.get("published_dt"))
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

    # ============================================================
    # YARDIMCI
    # ============================================================

    def _parse_datetime(self, dt_string: str) -> Optional[datetime]:
        """ISO datetime string'i parse et."""
        if not dt_string:
            return None
        try:
            # ISO format: 2026-03-19T06:30:00Z
            dt_string = dt_string.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_string.replace("+00:00", ""))
        except Exception:
            return None
