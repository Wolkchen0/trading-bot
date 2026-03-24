"""
Social Sentiment Analyzer — Gelişmiş Sosyal Medya Duygu Analizi
Reddit, X (Twitter), Google Trends, CoinGecko Trending ve Whale Alert.

Kaynaklar:
  1. Reddit (r/cryptocurrency, r/bitcoin, r/altcoin) — Public JSON API
  2. X (Twitter) — ntscraper ile ücretsiz tweet analizi (YENİ)
  3. Google Trends — arama hacmi tespiti
  4. CoinGecko Trending — trend olan coinler
  5. Whale Alert — büyük transfer takibi (ücretsiz tier)
  6. VADER NLP duygu analizi (ücretsiz, hafif)
"""
import os
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import COIN_SEARCH_TERMS
from utils.logger import logger

# VADER sentiment (nltk tabanlı — hafif ve etkili)
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    logger.debug("VADER yuklu degil, basit sentiment kullanilacak")

# X (Twitter) scraper — ntscraper (ücretsiz, API key gerekmez)
try:
    from ntscraper import Nitter
    X_AVAILABLE = True
except ImportError:
    X_AVAILABLE = False
    logger.debug("ntscraper yuklu degil, X/Twitter analizi devre disi")


SOCIAL_CONFIG = {
    # Reddit ayarları (public API — hesap gerekmez)
    "reddit_subs": [
        "cryptocurrency", "bitcoin", "ethereum",
        "altcoin", "CryptoMarkets", "SatoshiStreetBets",
    ],
    "reddit_search_url": "https://www.reddit.com/r/{sub}/search.json",
    "reddit_hot_url": "https://www.reddit.com/r/{sub}/hot.json",

    # Google Trends
    "google_trends_enabled": True,

    # CoinGecko Trending
    "coingecko_trending_url": "https://api.coingecko.com/api/v3/search/trending",

    # Whale Alert (ücretsiz tier)
    "whale_alert_url": "https://api.whale-alert.io/v1/transactions",
    "whale_min_usd": 1000000,  # $1M+ transferler

    # Coin anahtar kelimeleri — merkezi config'den
    "coin_search_terms": COIN_SEARCH_TERMS,

    # Cache
    "cache_minutes": 10,
    "max_posts_per_source": 25,

    # NLP duygu kelimeleri (VADER yoksa fallback)
    "extreme_bullish": [
        "moon", "rocket", "lambo", "to the moon", "diamond hands",
        "all in", "100x", "massive gains", "next bitcoin",
        "bullish af", "lfg", "huge pump", "generational wealth",
        "buy the dip", "accumulate", "undervalued", "breakout",
    ],
    "extreme_bearish": [
        "crash", "rug pull", "scam", "ponzi", "dead coin",
        "going to zero", "sell everything", "bear market",
        "exit scam", "lost everything", "worst investment",
        "paper hands", "bloodbath", "rekt", "dump it",
        "overvalued", "bubble", "collapse",
    ],
}


class SocialSentimentAnalyzer:
    """Gelişmiş sosyal medya duygu analizi — Reddit, X, Trends, CoinGecko, Whale Alert."""

    def __init__(self):
        self.cache = {}
        self.last_fetch = {}
        self.trending_cache = None
        self.trending_cache_time = None

        # X (Twitter) scraper
        self.x_scraper = None
        if X_AVAILABLE:
            try:
                self.x_scraper = Nitter(log_level=0)
                logger.info("X/Twitter scraper baslatildi")
            except Exception as e:
                logger.debug(f"X scraper baslatma hatasi: {e}")

        # VADER NLP başlat
        if VADER_AVAILABLE:
            self.vader = SentimentIntensityAnalyzer()
            # Kripto-spesifik kelimeler ekle
            self._add_crypto_lexicon()
            x_status = 'X aktif' if self.x_scraper else 'X devre disi'
            logger.info(f"SocialSentiment baslatildi - VADER NLP + {x_status} + CoinGecko + Whale")
        else:
            self.vader = None
            logger.info("SocialSentiment baslatildi - Basit NLP modu")

    def _add_crypto_lexicon(self):
        """VADER'a kripto-spesifik kelimeler ekle."""
        if not self.vader:
            return

        crypto_words = {
            "moon": 2.5, "mooning": 3.0, "bullish": 2.0, "bearish": -2.0,
            "pump": 1.5, "dump": -2.0, "rekt": -3.0, "hodl": 1.5,
            "fud": -1.5, "fomo": 1.0, "dip": -0.5, "rally": 2.0,
            "rug": -3.5, "scam": -3.0, "hack": -2.5, "exploit": -2.5,
            "adoption": 2.0, "partnership": 1.8, "upgrade": 1.5,
            "breakout": 2.5, "crash": -3.0, "surge": 2.5,
            "ath": 2.0, "accumulate": 1.5, "whale": 0.5,
            "lambo": 2.0, "diamond": 1.5,
        }
        self.vader.lexicon.update(crypto_words)

    # ============================================================
    # 1. REDDİT ANALİZİ
    # ============================================================

    def fetch_reddit_posts(self, coin: str) -> List[Dict]:
        """Reddit'ten coin ile ilgili postları çeker."""
        cache_key = f"reddit_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        posts = []
        search_terms = SOCIAL_CONFIG["coin_search_terms"].get(coin, [coin.lower()])

        headers = {
            "User-Agent": "CryptoBot/2.0 (Advanced Trading Analysis)",
        }

        for sub in SOCIAL_CONFIG["reddit_subs"][:3]:
            for term in search_terms[:1]:
                try:
                    url = f"https://www.reddit.com/r/{sub}/search.json"
                    params = {
                        "q": term,
                        "sort": "new",
                        "limit": 10,
                        "t": "day",
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
        """Google Trends arama hacmi değişimini kontrol eder."""
        cache_key = f"trends_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        result = {"score": 0, "signal": "NEUTRAL", "trending": False}

        if not SOCIAL_CONFIG["google_trends_enabled"]:
            return result

        try:
            search_terms = SOCIAL_CONFIG["coin_search_terms"].get(coin, [coin])
            term = search_terms[0]

            url = "https://trends.google.com/trends/api/dailytrends"
            params = {"hl": "en-US", "geo": "US", "ns": 15}

            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
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
    # 3. COİNGECKO TRENDING (YENİ)
    # ============================================================

    def get_coingecko_trending(self) -> Dict:
        """CoinGecko'da trend olan coinleri çeker."""
        # 15 dakika cache
        if (self.trending_cache_time and
            (datetime.now() - self.trending_cache_time).total_seconds() < 900):
            return self.trending_cache or {}

        try:
            response = requests.get(
                SOCIAL_CONFIG["coingecko_trending_url"],
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                trending_coins = {}

                for coin_data in data.get("coins", []):
                    item = coin_data.get("item", {})
                    symbol = item.get("symbol", "").upper()
                    trending_coins[symbol] = {
                        "name": item.get("name", ""),
                        "rank": item.get("market_cap_rank"),
                        "score": item.get("score", 0),
                        "price_btc": item.get("price_btc", 0),
                    }

                self.trending_cache = trending_coins
                self.trending_cache_time = datetime.now()

                if trending_coins:
                    names = [v["name"] for v in list(trending_coins.values())[:5]]
                    logger.info(f"  CoinGecko Trending: {', '.join(names)}")

                return trending_coins

        except Exception as e:
            logger.debug(f"CoinGecko trending hatasi: {e}")

        return {}

    def is_coin_trending(self, coin: str) -> Dict:
        """Belirli bir coinin CoinGecko'da trend olup olmadığını kontrol et."""
        trending = self.get_coingecko_trending()
        is_trending = coin in trending

        return {
            "trending": is_trending,
            "score": 15 if is_trending else 0,
            "signal": "BULLISH" if is_trending else "NEUTRAL",
            "rank": trending.get(coin, {}).get("rank"),
        }

    # ============================================================
    # 4. WHALE ALERT (YENİ)
    # ============================================================

    def check_whale_activity(self, coin: str) -> Dict:
        """
        Büyük kripto transferlerini kontrol et.
        Exchange'e giriş = satış baskısı → BEARISH
        Exchange'den çıkış = hodl → BULLISH
        """
        cache_key = f"whale_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        result = {
            "score": 0,
            "signal": "NEUTRAL",
            "large_transfers": 0,
            "exchange_inflow": 0,
            "exchange_outflow": 0,
        }

        whale_api_key = os.getenv("WHALE_ALERT_KEY", "")
        if not whale_api_key:
            # API key yoksa alternatif: CoinGecko data'dan çıkar
            self.cache[cache_key] = result
            self.last_fetch[cache_key] = datetime.now()
            return result

        try:
            # Coin symbol -> blockchain mapping
            blockchain_map = {
                "BTC": "bitcoin", "ETH": "ethereum",
                "SOL": "solana", "XRP": "ripple",
                "DOGE": "dogecoin", "LTC": "litecoin",
            }
            blockchain = blockchain_map.get(coin)
            if not blockchain:
                return result

            params = {
                "api_key": whale_api_key,
                "min_value": SOCIAL_CONFIG["whale_min_usd"],
                "currency": coin.lower(),
                "start": int((datetime.now() - timedelta(hours=24)).timestamp()),
            }
            response = requests.get(
                SOCIAL_CONFIG["whale_alert_url"],
                params=params,
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                transactions = data.get("transactions", [])
                result["large_transfers"] = len(transactions)

                exchange_inflow = 0
                exchange_outflow = 0

                for tx in transactions:
                    amount_usd = tx.get("amount_usd", 0)
                    to_owner = tx.get("to", {}).get("owner_type", "")
                    from_owner = tx.get("from", {}).get("owner_type", "")

                    if to_owner == "exchange":
                        exchange_inflow += amount_usd
                    if from_owner == "exchange":
                        exchange_outflow += amount_usd

                result["exchange_inflow"] = exchange_inflow
                result["exchange_outflow"] = exchange_outflow

                # Skor: outflow > inflow = BULLISH
                if exchange_outflow > exchange_inflow * 1.5 and exchange_outflow > 5_000_000:
                    result["score"] = 15
                    result["signal"] = "BULLISH"
                elif exchange_inflow > exchange_outflow * 1.5 and exchange_inflow > 5_000_000:
                    result["score"] = -15
                    result["signal"] = "BEARISH"

        except Exception as e:
            logger.debug(f"Whale Alert {coin} hatasi: {e}")

        self.cache[cache_key] = result
        self.last_fetch[cache_key] = datetime.now()
        return result

    # ============================================================
    # 5. X (TWITTER) ANALİZİ (YENİ)
    # ============================================================

    def fetch_x_posts(self, coin: str) -> Dict:
        """
        X (Twitter) üzerinden kripto tweet'leri çek ve analiz et.
        ntscraper kullanır — API key gerekmez, ücretsiz.
        """
        cache_key = f"x_{coin}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        result = {
            "score": 0,
            "signal": "NEUTRAL",
            "tweet_count": 0,
            "avg_sentiment": 0,
            "top_tweets": [],
        }

        if not self.x_scraper:
            return result

        try:
            # Coin'e göre arama terimleri
            search_terms = SOCIAL_CONFIG["coin_search_terms"].get(
                coin, [coin.lower()]
            )
            search_query = f"${coin} OR {' OR '.join(search_terms)} crypto"

            # ntscraper ile tweet çek
            tweets_data = self.x_scraper.get_tweets(
                search_query,
                mode="term",
                number=15,
            )

            tweets = tweets_data.get("tweets", [])
            if not tweets:
                self.cache[cache_key] = result
                self.last_fetch[cache_key] = datetime.now()
                return result

            result["tweet_count"] = len(tweets)

            # Her tweet'i analiz et
            sentiments = []
            top_tweets = []

            for tweet in tweets[:15]:
                text = tweet.get("text", "")
                if not text:
                    continue

                sent = self.analyze_text_sentiment(text)
                sentiments.append(sent["compound"])

                # Etkileşim metrikleri
                likes = tweet.get("stats", {}).get("likes", 0)
                retweets = tweet.get("stats", {}).get("retweets", 0)
                engagement = likes + retweets * 2

                top_tweets.append({
                    "text": text[:100],
                    "sentiment": sent["label"],
                    "score": sent["compound"],
                    "engagement": engagement,
                })

            if sentiments:
                # Engagement-weighted sentiment
                total_engagement = sum(t["engagement"] for t in top_tweets) or 1
                weighted_sent = sum(
                    t["score"] * (t["engagement"] / total_engagement)
                    for t in top_tweets
                )

                avg_sent = sum(sentiments) / len(sentiments)
                # Weighted ve simple ortalamanın karışımı
                combined = avg_sent * 0.4 + weighted_sent * 0.6

                result["avg_sentiment"] = round(combined, 3)
                result["top_tweets"] = sorted(
                    top_tweets, key=lambda x: x["engagement"], reverse=True
                )[:5]

                # Skor
                x_score = int(combined * 40)  # -40 ile +40 arası
                x_score = max(-30, min(30, x_score))
                result["score"] = x_score

                if x_score >= 15:
                    result["signal"] = "BULLISH"
                elif x_score >= 5:
                    result["signal"] = "SLIGHTLY_BULLISH"
                elif x_score <= -15:
                    result["signal"] = "BEARISH"
                elif x_score <= -5:
                    result["signal"] = "SLIGHTLY_BEARISH"

                logger.info(
                    f"  X/Twitter {coin}: {len(tweets)} tweet, "
                    f"sentiment:{combined:.3f} -> skor:{x_score} {result['signal']}"
                )

        except Exception as e:
            logger.debug(f"X/Twitter {coin} hatasi: {e}")

        self.cache[cache_key] = result
        self.last_fetch[cache_key] = datetime.now()
        return result

    # ============================================================
    # 6. NLP DUYGU ANALİZİ (İYİLEŞTİRİLMİŞ)
    # ============================================================

    def analyze_text_sentiment(self, text: str) -> Dict:
        """
        Gelişmiş metin duygu analizi — VADER NLP + kripto lexicon.
        """
        if not text:
            return {"compound": 0, "label": "NEUTRAL"}

        if self.vader:
            scores = self.vader.polarity_scores(text)
            compound = scores["compound"]
        else:
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
    # 6. SOSYAL HACIM ANALİZİ (Pump/Dump Tespiti)
    # ============================================================

    def detect_social_volume_spike(self, posts: List[Dict]) -> Dict:
        """Sosyal medya hacminde ani artış tespiti."""
        if len(posts) < 3:
            return {"spike": False, "score": 0, "signal": "NEUTRAL"}

        now = datetime.now().timestamp()
        recent_1h = sum(1 for p in posts if now - p.get("created", 0) < 3600)
        total = len(posts)

        avg_hourly = total / 24

        spike = False
        score = 0
        signal = "NEUTRAL"

        if avg_hourly > 0 and recent_1h > avg_hourly * 3:
            spike = True
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
    # 8. BİRLEŞTİRİLMİŞ SOSYAL SKOR (GELİŞTİRİLMİŞ + X)
    # ============================================================

    def get_social_score(self, symbol: str) -> Dict:
        """
        Gelişmiş sosyal skor — tüm kaynaklar birleştirilmiş.

        Ağırlıklar (X dahil):
          Reddit sentiment: %25
          X (Twitter):      %20
          Google Trends:    %10
          CoinGecko Trend:  %18
          Whale Alert:      %14
          Sosyal hacim:     %13
        """
        coin = symbol.replace("/USD", "").replace("USD", "")

        # 1. Reddit
        posts = self.fetch_reddit_posts(coin)
        reddit_score = 0
        reddit_sentiments = []

        for post in posts[:SOCIAL_CONFIG["max_posts_per_source"]]:
            text = post.get("title", "") + " " + post.get("text", "")
            sent = self.analyze_text_sentiment(text)
            reddit_sentiments.append(sent["compound"])

            weight = min(post.get("score", 1) / 100, 3)
            reddit_score += sent["compound"] * weight

        if reddit_sentiments:
            avg_reddit = sum(reddit_sentiments) / len(reddit_sentiments)
            reddit_score = int(avg_reddit * 50)
        else:
            reddit_score = 0

        # 2. X (Twitter) — YENİ
        x_data = self.fetch_x_posts(coin)
        x_score = x_data["score"]

        # 3. Google Trends
        trends = self.get_google_trends_score(coin)
        trends_score = trends["score"]

        # 4. CoinGecko Trending
        cg_trending = self.is_coin_trending(coin)
        trending_score = cg_trending["score"]

        # 5. Whale Alert
        whale = self.check_whale_activity(coin)
        whale_score = whale["score"]

        # 6. Sosyal hacim spike
        spike = self.detect_social_volume_spike(posts)
        spike_score = spike["score"]

        # Birleştirilmiş skor (X dahil)
        final_score = int(
            reddit_score * 0.25 +
            x_score * 0.20 +
            trends_score * 0.10 +
            trending_score * 0.18 +
            whale_score * 0.14 +
            spike_score * 0.13
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
            "x_score": x_score,
            "x_tweets": x_data.get("tweet_count", 0),
            "x_sentiment": x_data.get("avg_sentiment", 0),
            "google_trending": trends.get("trending", False),
            "coingecko_trending": cg_trending["trending"],
            "whale_score": whale_score,
            "whale_large_transfers": whale.get("large_transfers", 0),
            "social_spike": spike["spike"],
            "spike_posts_1h": spike.get("posts_1h", 0),
        }

        if posts or x_data["tweet_count"] or trends.get("trending") or cg_trending["trending"]:
            logger.info(
                f"  Sosyal {coin}: Reddit({len(posts)} post, skor:{reddit_score}) | "
                f"X({x_data['tweet_count']} tweet, skor:{x_score}) | "
                f"CGTrend:{'EVET' if cg_trending['trending'] else 'hayir'} | "
                f"Whale:{whale_score} | "
                f"Spike:{'EVET' if spike['spike'] else 'hayir'} | "
                f"Toplam:{final_score} -> {signal}"
            )

        return result

    # ============================================================
    # CACHE YÖNETİMİ
    # ============================================================

    def _is_cached(self, key: str) -> bool:
        if key not in self.cache or key not in self.last_fetch:
            return False
        elapsed = (datetime.now() - self.last_fetch[key]).total_seconds()
        return elapsed < SOCIAL_CONFIG["cache_minutes"] * 60
