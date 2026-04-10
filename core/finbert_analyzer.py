"""
FinBERT Analyzer — Finansal Domain NLP Sentiment Analizi

HuggingFace ProsusAI/finbert modeli ile finansal metinlerin
duygu analizini yapar. VADER'dan ~%20 daha doğru.

Fallback: FinBERT yüklenemezse → VADER kullanılır.
"""
import time
from typing import Dict, List, Optional
from utils.logger import logger

# FinBERT model yükleme (opsiyonel — yoksa VADER'a düş)
FINBERT_AVAILABLE = False
_finbert_pipeline = None

try:
    from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
    FINBERT_AVAILABLE = True
except ImportError:
    logger.info("transformers yuklu degil, VADER fallback kullanilacak")

# VADER fallback
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False


class FinBERTAnalyzer:
    """
    FinBERT tabanlı finansal metin duygu analizi.
    
    Kullanım:
        fb = FinBERTAnalyzer()
        result = fb.analyze("Bitcoin surges to new all-time high")
        # {'label': 'positive', 'score': 0.95, 'confidence': 0.95}
    """

    MODEL_NAME = "ProsusAI/finbert"
    
    def __init__(self):
        self.pipeline = None
        self.vader = None
        self.model_loaded = False
        self._load_attempts = 0
        self._max_load_attempts = 2
        
        # Hisse senedi-spesifik kelime ağırlıkları (FinBERT sonucunu ayarlar)
        self.stock_boost = {
            # Güçlü bullish kelimeler
            "upgrade": 0.12, "outperform": 0.10, "buy rating": 0.12,
            "beat estimate": 0.15, "earnings beat": 0.15, "revenue beat": 0.12,
            "raised guidance": 0.15, "strong buy": 0.12, "bullish": 0.10,
            "fda approv": 0.15, "acquisition": 0.08, "buyback": 0.10,
            "dividend increase": 0.10, "all-time high": 0.08,
            "breakout": 0.10, "rally": 0.10, "surge": 0.10,
            # Güçlü bearish kelimeler
            "downgrade": -0.12, "sell rating": -0.12, "underperform": -0.10,
            "earnings miss": -0.15, "revenue miss": -0.12,
            "lowered guidance": -0.15, "restructur": -0.10,
            "layoff": -0.10, "recall": -0.12, "lawsuit": -0.10,
            "sec investig": -0.15, "fraud": -0.18, "bankruptcy": -0.20,
            "tariff": -0.10, "sanctions": -0.12, "crash": -0.15,
            "bearish": -0.10, "default": -0.15,
        }
        
        # Model yüklemeyi dene
        self._load_model()
        
        # VADER fallback
        if VADER_AVAILABLE and not self.model_loaded:
            self.vader = SentimentIntensityAnalyzer()
            self._add_stock_lexicon()
            logger.info("FinBERT yuklenemedi, VADER fallback aktif")

    def _load_model(self):
        """FinBERT modelini yükle (lazy loading)."""
        if not FINBERT_AVAILABLE:
            return
        
        if self._load_attempts >= self._max_load_attempts:
            return
            
        self._load_attempts += 1
        
        try:
            logger.info(f"FinBERT modeli yukleniyor ({self.MODEL_NAME})...")
            start = time.time()
            
            self.pipeline = pipeline(
                "sentiment-analysis",
                model=self.MODEL_NAME,
                tokenizer=self.MODEL_NAME,
                device=-1,  # CPU (GPU yoksa)
                truncation=True,
                max_length=512,
            )
            
            elapsed = time.time() - start
            self.model_loaded = True
            logger.info(f"FinBERT basariyla yuklendi ({elapsed:.1f}sn)")
            
        except Exception as e:
            logger.warning(f"FinBERT yukleme hatasi: {e}")
            self.model_loaded = False

    def _add_stock_lexicon(self):
        """VADER'a hisse senedi kelimeleri ekle (fallback için)."""
        if not self.vader:
            return
        stock_words = {
            "upgrade": 2.5, "downgrade": -2.5, "outperform": 2.0,
            "underperform": -2.0, "overweight": 1.5, "underweight": -1.5,
            "bullish": 2.0, "bearish": -2.0, "rally": 2.0, "surge": 2.5,
            "crash": -3.0, "plunge": -2.5, "tumble": -2.0,
            "buyback": 1.5, "dividend": 1.5, "guidance": 1.0,
            "beat": 2.0, "miss": -2.0, "layoff": -2.0, "restructuring": -1.5,
            "acquisition": 1.5, "merger": 1.0, "bankruptcy": -3.5,
            "fda": 1.0, "approved": 2.0, "rejected": -2.5,
            "breakout": 2.5, "selloff": -2.5, "correction": -1.5,
            "momentum": 1.5, "overbought": -1.0, "oversold": 1.0,
        }
        self.vader.lexicon.update(stock_words)

    def analyze(self, text: str) -> Dict:
        """
        Metni analiz et — FinBERT veya VADER ile.
        
        Returns:
            {
                'label': 'positive' | 'negative' | 'neutral',
                'score': float (-1.0 to 1.0),
                'confidence': float (0.0 to 1.0),
                'source': 'finbert' | 'vader'
            }
        """
        if not text or not text.strip():
            return {
                "label": "neutral",
                "score": 0.0,
                "confidence": 0.0,
                "source": "none",
            }

        # FinBERT ile analiz
        if self.model_loaded and self.pipeline:
            return self._analyze_finbert(text)
        
        # VADER fallback
        if self.vader:
            return self._analyze_vader(text)
        
        # Hiçbiri yoksa basit analiz
        return self._analyze_simple(text)

    def _analyze_finbert(self, text: str) -> Dict:
        """FinBERT ile derin duygu analizi."""
        try:
            # FinBERT tahmin
            result = self.pipeline(text[:512])[0]
            
            label = result["label"].lower()
            raw_score = result["score"]
            
            # Label → score dönüşümü
            if label == "positive":
                score = raw_score
            elif label == "negative":
                score = -raw_score
            else:
                score = 0.0
            
            # Hisse senedi boost uygula
            boost = self._get_stock_boost(text)
            score = max(-1.0, min(1.0, score + boost))
            
            # Boost sonrası label güncelle
            if score > 0.1:
                label = "positive"
            elif score < -0.1:
                label = "negative"
            else:
                label = "neutral"
            
            return {
                "label": label,
                "score": round(score, 4),
                "confidence": round(raw_score, 4),
                "source": "finbert",
            }
            
        except Exception as e:
            logger.debug(f"FinBERT analiz hatasi: {e}")
            # Fallback to VADER
            if self.vader:
                return self._analyze_vader(text)
            return self._analyze_simple(text)

    def _analyze_vader(self, text: str) -> Dict:
        """VADER ile kural tabanlı duygu analizi (fallback)."""
        scores = self.vader.polarity_scores(text)
        compound = scores["compound"]
        
        if compound >= 0.15:
            label = "positive"
        elif compound <= -0.15:
            label = "negative"
        else:
            label = "neutral"
        
        return {
            "label": label,
            "score": round(compound, 4),
            "confidence": round(abs(compound), 4),
            "source": "vader",
        }

    def _analyze_simple(self, text: str) -> Dict:
        """En basit kelime sayma analizi (son çare)."""
        text_lower = text.lower()
        
        bullish = ["surge", "rally", "moon", "bullish", "breakout", "ath",
                    "adoption", "upgrade", "pump", "accumulate", "buy"]
        bearish = ["crash", "dump", "scam", "rug", "hack", "bearish",
                    "ban", "liquidation", "sell", "collapse", "fear"]
        
        bull_count = sum(1 for w in bullish if w in text_lower)
        bear_count = sum(1 for w in bearish if w in text_lower)
        
        score = (bull_count - bear_count) * 0.2
        score = max(-1.0, min(1.0, score))
        
        if score > 0.1:
            label = "positive"
        elif score < -0.1:
            label = "negative"
        else:
            label = "neutral"
        
        return {
            "label": label,
            "score": round(score, 4),
            "confidence": round(abs(score), 4),
            "source": "simple",
        }

    def _get_stock_boost(self, text: str) -> float:
        """Hisse senedi-spesifik kelimeler için ek boost."""
        text_lower = text.lower()
        boost = 0.0
        for word, value in self.stock_boost.items():
            if word in text_lower:
                boost += value
        return max(-0.3, min(0.3, boost))

    def analyze_batch(self, texts: List[str]) -> List[Dict]:
        """Birden fazla metni toplu analiz et."""
        return [self.analyze(text) for text in texts if text]

    def is_available(self) -> bool:
        """FinBERT modeli yüklü mü?"""
        return self.model_loaded

    def get_status(self) -> Dict:
        """Analyzer durumunu döndür."""
        return {
            "finbert_loaded": self.model_loaded,
            "vader_available": self.vader is not None,
            "active_source": "finbert" if self.model_loaded else ("vader" if self.vader else "simple"),
        }
