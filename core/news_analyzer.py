"""
Hisse Senedi Haber Takip & Gelişmiş Duygu Analizi Modülü
- Alpha Vantage News API
- Marketaux API  
- Finviz haber tarama
- Fear & Greed Index (CNN)
- FinBERT + VADER duygu analizi
- Jeopolitik risk takibi (Hürmüz Boğazı, petrol, savaş)
"""
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logger import logger
from config import STOCK_SEARCH_TERMS, GEOPOLITICAL_KEYWORDS

# FinBERT (opsiyonel)
try:
    from core.finbert_analyzer import FinBERTAnalyzer
    FINBERT_AVAILABLE = True
except ImportError:
    FINBERT_AVAILABLE = False

# VADER fallback
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False


# ============================================================
# HABER KONFİGÜRASYONU
# ============================================================
NEWS_CONFIG = {
    # Duygu analizi anahtar kelimeleri
    "bullish_keywords": [
        # Hisse pozitif
        "earnings beat", "revenue growth", "guidance raised", "buyback",
        "stock buyback", "dividend increase", "upgrade", "outperform",
        "strong buy", "price target raised", "record revenue", "beats estimates",
        "exceeded expectations", "upside surprise", "market rally",
        "bull market", "all-time high", "ipo success", "merger", "acquisition",
        "partnership", "contract win", "fda approval", "patent granted",
        # Makro pozitif
        "rate cut", "inflation cools", "jobs growth", "stimulus",
        "fed dovish", "soft landing", "ceasefire", "peace deal",
        "trade deal", "sanctions lifted",
    ],
    "bearish_keywords": [
        # Hisse negatif
        "earnings miss", "revenue decline", "guidance lowered", "downgrade",
        "underperform", "sell rating", "price target cut", "missed estimates",
        "profit warning", "layoffs", "restructuring", "sec investigation",
        "class action lawsuit", "data breach", "product recall", "ceo resign",
        "insider selling", "dilution", "secondary offering",
        # Makro negatif
        "rate hike", "inflation surge", "recession", "unemployment rise",
        "fed hawkish", "default risk", "banking crisis", "yield inversion",
        "bear market", "sell-off", "crash", "panic",
        # Jeopolitik
        "war escalat", "military strike", "missile", "strait of hormuz",
        "oil surge", "oil spike", "sanctions", "embargo", "tariff war",
        "invasion", "bombing", "nuclear", "blockade", "supply disruption",
    ],

    # Cache süresi
    "cache_minutes": 10,  # Haber hızlı eskir

    # API rate limit koruması
    "alpha_vantage_cooldown": 15,  # AV: dakikada 5 istek (ücretsiz)
    "marketaux_cooldown": 10,
}


class StockNewsAnalyzer:
    """Hisse senedi haberleri analizi — Alpha Vantage + Marketaux."""

    def __init__(self):
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_KEY", "")
        self.marketaux_token = os.getenv("MARKETAUX_TOKEN", "")
        self.cache = {}
        self.last_fetch = {}
        self.finbert = None
        self.vader = None

        # FinBERT veya VADER başlat
        if FINBERT_AVAILABLE:
            try:
                self.finbert = FinBERTAnalyzer()
                logger.info("StockNewsAnalyzer: FinBERT aktif")
            except Exception:
                pass

        if self.finbert is None and VADER_AVAILABLE:
            self.vader = SentimentIntensityAnalyzer()
            logger.info("StockNewsAnalyzer: VADER fallback aktif")

        sources = []
        if self.alpha_vantage_key:
            sources.append("Alpha Vantage")
        if self.marketaux_token:
            sources.append("Marketaux")
        logger.info(f"StockNewsAnalyzer baslatildi — Kaynaklar: {', '.join(sources) or 'YOK'}")

    # ============================================================
    # 1. ANA ANALİZ FONKSİYONU
    # ============================================================

    def analyze_stock_news(self, symbol: str) -> Dict:
        """
        Hisse bazlı haber analizi.
        
        Returns:
            {
                'news_score': int (-100 ile +100),
                'signal': 'BULLISH' | 'BEARISH' | 'NEUTRAL',
                'article_count': int,
                'top_headlines': list,
                'geopolitical_risk': str,
            }
        """
        cache_key = f"news_{symbol}"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        articles = []

        # Alpha Vantage'den haber çek
        if self.alpha_vantage_key:
            av_articles = self._fetch_alpha_vantage_news(symbol)
            articles.extend(av_articles)

        # Marketaux'den haber çek
        if self.marketaux_token:
            mx_articles = self._fetch_marketaux_news(symbol)
            articles.extend(mx_articles)

        # Analiz et
        if not articles:
            result = {
                "news_score": 0,
                "signal": "NEUTRAL",
                "article_count": 0,
                "top_headlines": [],
                "geopolitical_risk": "UNKNOWN",
            }
        else:
            score, sentiments = self._analyze_articles(articles, symbol)
            geo_risk = self._check_geopolitical_risk(articles)

            if score >= 15:
                signal = "BULLISH"
            elif score <= -15:
                signal = "BEARISH"
            else:
                signal = "NEUTRAL"

            result = {
                "news_score": score,
                "signal": signal,
                "article_count": len(articles),
                "top_headlines": [a.get("title", "")[:80] for a in articles[:3]],
                "geopolitical_risk": geo_risk,
                "sentiments": sentiments,
            }

        self.cache[cache_key] = result
        self.last_fetch[cache_key] = datetime.now()

        logger.info(
            f"  Haber {symbol}: {result['article_count']} haber, "
            f"skor={result['news_score']}, sinyal={result['signal']}, "
            f"jeopolitik={result['geopolitical_risk']}"
        )
        return result

    # ============================================================
    # 2. ALPHA VANTAGE NEWS
    # ============================================================

    def _fetch_alpha_vantage_news(self, symbol: str) -> List[Dict]:
        """Alpha Vantage News Sentiment API."""
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "NEWS_SENTIMENT",
                "tickers": symbol,
                "limit": 10,
                "apikey": self.alpha_vantage_key,
            }
            response = requests.get(url, params=params, timeout=15)
            time.sleep(NEWS_CONFIG["alpha_vantage_cooldown"])

            if response.status_code == 200:
                data = response.json()
                feed = data.get("feed", [])
                articles = []
                for item in feed[:10]:
                    articles.append({
                        "title": item.get("title", ""),
                        "summary": item.get("summary", ""),
                        "source": item.get("source", ""),
                        "published": item.get("time_published", ""),
                        "sentiment_score": float(item.get("overall_sentiment_score", 0)),
                        "sentiment_label": item.get("overall_sentiment_label", "Neutral"),
                        "api": "alpha_vantage",
                    })
                return articles
        except Exception as e:
            logger.debug(f"Alpha Vantage haber hatası {symbol}: {e}")
        return []

    # ============================================================
    # 3. MARKETAUX NEWS
    # ============================================================

    def _fetch_marketaux_news(self, symbol: str) -> List[Dict]:
        """Marketaux News API."""
        try:
            url = "https://api.marketaux.com/v1/news/all"
            params = {
                "symbols": symbol,
                "filter_entities": "true",
                "language": "en",
                "limit": 10,
                "api_token": self.marketaux_token,
            }
            response = requests.get(url, params=params, timeout=15)
            time.sleep(NEWS_CONFIG["marketaux_cooldown"])

            if response.status_code == 200:
                data = response.json()
                articles = []
                for item in data.get("data", [])[:10]:
                    articles.append({
                        "title": item.get("title", ""),
                        "summary": item.get("description", ""),
                        "source": item.get("source", ""),
                        "published": item.get("published_at", ""),
                        "sentiment_score": 0,  # Kendi analiz edeceğiz
                        "api": "marketaux",
                    })
                return articles
        except Exception as e:
            logger.debug(f"Marketaux haber hatası {symbol}: {e}")
        return []

    # ============================================================
    # 4. DUYGU ANALİZİ
    # ============================================================

    def _analyze_articles(self, articles: List[Dict], symbol: str) -> tuple:
        """Haber duygu analizi — FinBERT/VADER + keyword."""
        total_score = 0
        sentiments = []

        for article in articles:
            text = f"{article.get('title', '')} {article.get('summary', '')}"
            if not text.strip():
                continue

            # API'den gelen sentiment skoru (Alpha Vantage)
            api_score = article.get("sentiment_score", 0)

            # Keyword analizi
            keyword_score = self._keyword_score(text)

            # NLP analizi (FinBERT veya VADER)
            nlp_score = 0
            if self.finbert:
                try:
                    result = self.finbert.analyze(text[:512])
                    if result["label"] == "positive":
                        nlp_score = result["score"] * 30
                    elif result["label"] == "negative":
                        nlp_score = -result["score"] * 30
                except Exception:
                    pass
            elif self.vader:
                scores = self.vader.polarity_scores(text)
                nlp_score = scores["compound"] * 25

            # Birleşik skor (ağırlıklı)
            article_score = int(
                api_score * 20 * 0.3 +    # API skoru %30
                keyword_score * 0.3 +       # Keyword %30
                nlp_score * 0.4             # NLP %40
            )

            # Zaman ağırlığı (yeni haberler daha önemli)
            time_weight = self._get_time_weight(article.get("published", ""))
            article_score = int(article_score * time_weight)

            total_score += article_score
            sentiments.append({
                "title": article.get("title", "")[:60],
                "score": article_score,
                "source": article.get("api", "unknown"),
            })

        # Normalize (-100 ile +100 arası)
        if len(articles) > 0:
            total_score = max(min(total_score, 100), -100)

        return total_score, sentiments

    def _keyword_score(self, text: str) -> float:
        """Anahtar kelime bazlı skor."""
        text_lower = text.lower()
        score = 0

        for keyword in NEWS_CONFIG["bullish_keywords"]:
            if keyword in text_lower:
                score += 10
        for keyword in NEWS_CONFIG["bearish_keywords"]:
            if keyword in text_lower:
                score -= 10

        return max(min(score, 50), -50)

    def _get_time_weight(self, published: str) -> float:
        """Yeni haberler daha ağırlıklı."""
        try:
            if not published:
                return 0.5
            # Çeşitli format desteği
            for fmt in ["%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    pub_dt = datetime.strptime(published[:19], fmt)
                    hours_ago = (datetime.now() - pub_dt).total_seconds() / 3600
                    if hours_ago < 1:
                        return 1.0
                    elif hours_ago < 6:
                        return 0.8
                    elif hours_ago < 24:
                        return 0.5
                    else:
                        return 0.3
                except ValueError:
                    continue
        except Exception:
            pass
        return 0.5

    # ============================================================
    # 5. JEOPOLİTİK RİSK TAKİBİ
    # ============================================================

    def _check_geopolitical_risk(self, articles: List[Dict]) -> str:
        """
        Haberlerde jeopolitik risk var mı?
        Hürmüz Boğazı, petrol krizi, savaş vs.
        """
        all_text = " ".join(
            f"{a.get('title', '')} {a.get('summary', '')}" for a in articles
        ).lower()

        risk_count = 0
        for keyword in GEOPOLITICAL_KEYWORDS["bearish"]:
            if keyword in all_text:
                risk_count += 1

        safe_count = 0
        for keyword in GEOPOLITICAL_KEYWORDS["bullish"]:
            if keyword in all_text:
                safe_count += 1

        if risk_count >= 3:
            return "HIGH"
        elif risk_count >= 1:
            return "ELEVATED"
        elif safe_count >= 2:
            return "LOW"
        return "NORMAL"

    def get_market_sentiment(self) -> Dict:
        """
        Genel piyasa duyarlılığı — SPY/QQQ haberleri + Fear & Greed.
        """
        spy_news = self.analyze_stock_news("SPY")
        qqq_news = self.analyze_stock_news("QQQ")

        # CNN Fear & Greed Index (ücretsiz endpoint)
        fear_greed = self._get_fear_greed_index()

        combined_score = int(
            spy_news["news_score"] * 0.4 +
            qqq_news["news_score"] * 0.3 +
            fear_greed.get("score", 50) * 0.3 - 15  # normalize (0-100 → -15 ile +15)
        )

        return {
            "market_sentiment": combined_score,
            "spy_sentiment": spy_news["signal"],
            "qqq_sentiment": qqq_news["signal"],
            "fear_greed": fear_greed,
            "geopolitical_risk": spy_news.get("geopolitical_risk", "UNKNOWN"),
        }

    def _get_fear_greed_index(self) -> Dict:
        """CNN Fear & Greed Index."""
        cache_key = "fear_greed"
        if self._is_cached(cache_key):
            return self.cache[cache_key]

        try:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                score = data.get("fear_and_greed", {}).get("score", 50)
                rating = data.get("fear_and_greed", {}).get("rating", "Neutral")
                result = {"score": score, "rating": rating}
                self.cache[cache_key] = result
                self.last_fetch[cache_key] = datetime.now()
                return result
        except Exception as e:
            logger.debug(f"Fear & Greed hatası: {e}")
        return {"score": 50, "rating": "Neutral"}

    # ============================================================
    # CACHE
    # ============================================================

    def _is_cached(self, key: str) -> bool:
        if key not in self.cache or key not in self.last_fetch:
            return False
        elapsed = (datetime.now() - self.last_fetch[key]).total_seconds()
        return elapsed < NEWS_CONFIG["cache_minutes"] * 60
