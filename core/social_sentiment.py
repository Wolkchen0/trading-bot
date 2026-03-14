"""
Social Sentiment Analyzer — Sosyal Medya Duygu Analizi
Reddit, Google Trends ve web'den kripto sentiment tarar.

Kaynaklar:
  1. Reddit (r/cryptocurrency, r/bitcoin, r/altcoin) — PRAW veya web scraping
  2. Google Trends — pytrends ile arama hacmi tespiti
  3. Kripto-spesifik forum/haber tarama
  4. VADER NLP duygu analizi (ücretsiz, hafif)
"""
import os
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logger import logger

# VADER sentiment (nltk tabanlı — hafif ve etkili)
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    logger.debug("VADER yuklu degil, basit sentiment kullanilacak")


SOCIAL_CONFIG = {
    # Reddit ayarları (pushshift/public API — hesap gerekmez)
    "reddit_subs": [
        "cryptocurrency", "bitcoin", "ethereum",
        "altcoin", "CryptoMarkets", "SatoshiStreetBets",
    ],
    "reddit_search_url": "https://www.reddit.com/r/{sub}/search.json",
    "reddit_hot_url": "https://www.reddit.com/r/{sub}/hot.json",

    # Google Trends
    "google_trends_enabled": True,

    # Coin anahtar kelimeleri
    "coin_search_terms": {
        "BTC": ["bitcoin", "btc"],
        "ETH": ["ethereum", "eth", "vitalik"],
        "SOL": ["solana"],
        "XRP": ["ripple", "xrp"],
        "DOGE": ["dogecoin", "doge"],
        "SHIB": ["shiba inu", "shib"],
        "PEPE": ["pepe coin"],
        "LINK": ["chainlink"],
        "AVAX": ["avalanche"],
        "ADA": ["cardano"],
        "DOT": ["polkadot"],
        "LTC": ["litecoin"],
        "BONK": ["bonk"],
        "ARB": ["arbitrum"],
        "RENDER": ["render token"],
        "TRUMP": ["trump coin", "trump crypto"],
        "ONDO": ["ondo finance"],
        "WIF": ["dogwifhat", "wif"],
        "UNI": ["uniswap"],
        "AAVE": ["aave"],
    },

    # Cache
    "cache_minutes": 10,
    "max_posts_per_source": 25,

    # NLP duygu kelimeleri (VADER yoksa fallback)
    "extreme_bullish": [
        "moon", "rocket", "lambo", "to the moon", "diamond hands",
        "all in", "100x", "massive gains", "next bitcoin",
        "bullish af", "lfg", "huge pump", "generational wealth",
    ],
    "extreme_bearish": [
        "crash", "rug pull", "scam", "ponzi", "dead coin",
        "going to zero", "sell everything", "bear market",
        "exit scam", "lost everything", "worst investment",
        "paper hands", "bloodbath", "rekt",
    ],
}


class SocialSentimentAnalyzer:
    """Sosyal medya duygu analizi — Reddit, Google Trends, NLP."""

    def __init__(self):
        self.cache = {}
        self.last_fetch = {}

        # VADER NLP başlat
        if VADER_AVAILABLE:
            self.vader = SentimentIntensityAnalyzer()
            logger.info("SocialSentiment baslatildi - VADER NLP aktif")
        else:
            self.vader = None
            logger.info("SocialSentiment baslatildi - Basit NLP modu")

    # ============================================================
    # 1. REDDİT ANALİZİ
    # ============================================================

    def fetch_reddit_posts(self, coin: str) -> List[Dict]:
        """
        Reddit'ten coin ile ilgili postları çeker.
        Public JSON API kullanır — hesap gerekmez.
        """
        cache_key = f"reddit_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        posts = []
        search_terms = SOCIAL_CONFIG["coin_search_terms"].get(coin, [coin.lower()])

        headers = {
            "User-Agent": "CryptoBot/1.0 (Trading Analysis)",
        }

        for sub in SOCIAL_CONFIG["reddit_subs"][:3]:  # İlk 3 subreddit
            for term in search_terms[:1]:  # İlk arama terimi
                try:
                    url = f"https://www.reddit.com/r/{sub}/search.json"
                    params = {
                        "q": term,
                        "sort": "new",
                        "limit": 10,
                        "t": "day",  # Son 24 saat
                        "restrict_sr": "true",
                    }
                    response = requests.get(
                        url, params=params, headers=headers, timeout=10
                    )
                    if response.status_code == 200:
                        data = response.json()
                        for child in data.get("data", {}).get("children", []):
                            post = child.get("data", {})
                            posts.append({
                                "title": post.get("title", ""),
                                "text": post.get("selftext", "")[:200],
                                "score": post.get("score", 0),
                                "upvote_ratio": post.get("upvote_ratio", 0.5),
                                "num_comments": post.get("num_comments", 0),
                                "subreddit": sub,
                                "created": post.get("created_utc", 0),
                            })

                    # Rate limiting
                    time.sleep(1)

                except Exception as e:
                    logger.debug(f"Reddit {sub} hatasi: {e}")
                    continue

        self.cache[cache_key] = posts
        self.last_fetch[cache_key] = datetime.now()
        return posts

    # ============================================================
    # 2. GOOGLE TRENDS
    # ============================================================

    def get_google_trends_score(self, coin: str) -> Dict:
        """
        Google Trends arama hacmi değişimini kontrol eder.
        Arama hacmi artıyorsa → ilgi artıyor → potansiyel fiyat hareketi.
        """
        cache_key = f"trends_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        result = {"score": 0, "signal": "NEUTRAL", "trending": False}

        if not SOCIAL_CONFIG["google_trends_enabled"]:
            return result

        try:
            # SerpAPI veya basit Google Trends proxy
            search_terms = SOCIAL_CONFIG["coin_search_terms"].get(coin, [coin])
            term = search_terms[0]

            # Google Trends daily API (ücretsiz)
            url = f"https://trends.google.com/trends/api/dailytrends"
            params = {"hl": "en-US", "geo": "US", "ns": 15}

            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                # Google Trends JSON'ı ")]}" ile başlar, temizle
                text = response.text
                if text.startswith(")]}'"):
                    text = text[5:]

                data = json.loads(text)
                trending_searches = data.get("default", {}).get(
                    "trendingSearchesDays", []
                )

                for day in trending_searches[:1]:
                    for search in day.get("trendingSearches", []):
                        title = search.get("title", {}).get("query", "").lower()
                        if any(t in title for t in [term, coin.lower()]):
                            result["trending"] = True
                            result["score"] = 20
                            result["signal"] = "BUY"
                            result["trending_title"] = title

        except Exception as e:
            logger.debug(f"Google Trends hatasi: {e}")

        self.cache[cache_key] = result
        self.last_fetch[cache_key] = datetime.now()
        return result

    # ============================================================
    # 3. NLP DUYGU ANALİZİ
    # ============================================================

    def analyze_text_sentiment(self, text: str) -> Dict:
        """
        Metin duygu analizi — VADER NLP veya fallback.
        
        Returns:
            compound: -1 (çok negatif) ile +1 (çok pozitif) arası skor
            label: BULLISH, BEARISH, NEUTRAL
        """
        if not text:
            return {"compound": 0, "label": "NEUTRAL"}

        # VADER NLP (daha doğru)
        if self.vader:
            scores = self.vader.polarity_scores(text)
            compound = scores["compound"]
        else:
            # Fallback: Basit kelime sayma
            text_lower = text.lower()
            bullish_count = sum(
                1 for w in SOCIAL_CONFIG["extreme_bullish"] if w in text_lower
            )
            bearish_count = sum(
                1 for w in SOCIAL_CONFIG["extreme_bearish"] if w in text_lower
            )
            compound = (bullish_count - bearish_count) * 0.2
            compound = max(-1, min(1, compound))

        if compound >= 0.3:
            label = "BULLISH"
        elif compound >= 0.1:
            label = "SLIGHTLY_BULLISH"
        elif compound <= -0.3:
            label = "BEARISH"
        elif compound <= -0.1:
            label = "SLIGHTLY_BEARISH"
        else:
            label = "NEUTRAL"

        return {"compound": round(compound, 3), "label": label}

    # ============================================================
    # 4. SOSYAL HACIM ANALİZİ (Pump/Dump Tespiti)
    # ============================================================

    def detect_social_volume_spike(self, posts: List[Dict]) -> Dict:
        """
        Sosyal medya hacminde ani artış tespiti.
        Kısa sürede çok fazla post → pump veya dump habercisi olabilir.
        """
        if len(posts) < 3:
            return {"spike": False, "score": 0, "signal": "NEUTRAL"}

        # Son 1 saat vs son 24 saat
        now = datetime.now().timestamp()
        recent_1h = sum(1 for p in posts if now - p.get("created", 0) < 3600)
        total = len(posts)

        # Ortalama saatlik post (24 saat varsayarak)
        avg_hourly = total / 24

        spike = False
        score = 0
        signal = "NEUTRAL"

        if avg_hourly > 0 and recent_1h > avg_hourly * 3:
            spike = True
            # Spike'ın yönünü analiz et
            recent_sentiments = []
            for p in posts:
                if now - p.get("created", 0) < 3600:
                    sent = self.analyze_text_sentiment(p.get("title", ""))
                    recent_sentiments.append(sent["compound"])

            if recent_sentiments:
                avg_sentiment = sum(recent_sentiments) / len(recent_sentiments)
                if avg_sentiment > 0.1:
                    score = 15
                    signal = "BUY"
                elif avg_sentiment < -0.1:
                    score = -15
                    signal = "SELL"

        return {
            "spike": spike,
            "score": score,
            "signal": signal,
            "posts_1h": recent_1h,
            "avg_hourly": round(avg_hourly, 1),
        }

    # ============================================================
    # 5. BİRLEŞTİRİLMİŞ SOSYAL SKOR
    # ============================================================

    def get_social_score(self, symbol: str) -> Dict:
        """
        Bir coin için tüm sosyal kaynakları birleştirerek skor üretir.
        Bu fonksiyon news_analyzer.py tarafından çağrılır.
        
        Ağırlıklar:
          Reddit sentiment: %50
          Google Trends: %20
          Sosyal hacim spike: %30
        """
        coin = symbol.replace("/USD", "").replace("USD", "")

        # Reddit
        posts = self.fetch_reddit_posts(coin)
        reddit_score = 0
        reddit_sentiments = []

        for post in posts[:SOCIAL_CONFIG["max_posts_per_source"]]:
            text = post.get("title", "") + " " + post.get("text", "")
            sent = self.analyze_text_sentiment(text)
            reddit_sentiments.append(sent["compound"])

            # Upvote ağırlığı: çok beğenilen postlar daha etkili
            weight = min(post.get("score", 1) / 100, 3)  # Max 3x ağırlık
            reddit_score += sent["compound"] * weight

        if reddit_sentiments:
            avg_reddit = sum(reddit_sentiments) / len(reddit_sentiments)
            reddit_score = int(avg_reddit * 50)  # -50 ile +50 arası
        else:
            reddit_score = 0

        # Google Trends
        trends = self.get_google_trends_score(coin)
        trends_score = trends["score"]

        # Sosyal hacim spike
        spike = self.detect_social_volume_spike(posts)
        spike_score = spike["score"]

        # Birleştirilmiş skor
        # Reddit %50 + Trends %20 + Spike %30
        final_score = int(
            reddit_score * 0.5 +
            trends_score * 0.2 +
            spike_score * 0.3
        )

        # Sinyal
        if final_score >= 20:
            signal = "STRONG_BUY"
        elif final_score >= 8:
            signal = "BUY"
        elif final_score <= -20:
            signal = "STRONG_SELL"
        elif final_score <= -8:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        result = {
            "social_score": final_score,
            "social_signal": signal,
            "reddit_score": reddit_score,
            "reddit_posts": len(posts),
            "reddit_avg_sentiment": round(
                sum(reddit_sentiments) / max(len(reddit_sentiments), 1), 3
            ),
            "google_trending": trends.get("trending", False),
            "social_spike": spike["spike"],
            "spike_posts_1h": spike.get("posts_1h", 0),
        }

        if posts or trends.get("trending"):
            logger.info(
                f"  Sosyal {coin}: Reddit({len(posts)} post, "
                f"skor:{reddit_score}) | "
                f"Trend:{'EVET' if trends.get('trending') else 'hayir'} | "
                f"Spike:{'EVET' if spike['spike'] else 'hayir'} | "
                f"Toplam:{final_score} -> {signal}"
            )

        return result

    # ============================================================
    # CACHE YÖNETİMİ
    # ============================================================

    def _is_cached(self, key: str) -> bool:
        """Cache geçerliliğini kontrol et."""
        if key not in self.cache or key not in self.last_fetch:
            return False
        elapsed = (datetime.now() - self.last_fetch[key]).total_seconds()
        return elapsed < SOCIAL_CONFIG["cache_minutes"] * 60
