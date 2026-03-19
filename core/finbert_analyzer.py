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
        
        # Kripto-spesifik kelime ağırlıkları (FinBERT sonucunu ayarlar)
        self.crypto_boost = {
            # Güçlü bullish kelimeler
            "moon": 0.15, "ath": 0.12, "surge": 0.10, "breakout": 0.12,
            "rally": 0.10, "adoption": 0.10, "upgrade": 0.08,
            "partnership": 0.08, "accumulate": 0.08, "bullish": 0.10,
            # Güçlü bearish kelimeler
            "crash": -0.15, "rug pull": -0.20, "scam": -0.18,
            "hack": -0.15, "exploit": -0.15, "dump": -0.12,
            "ban": -0.12, "sec lawsuit": -0.15, "ponzi": -0.18,
            "bearish": -0.10, "liquidation": -0.12,
        }
        
        # Model yüklemeyi dene
        self._load_model()
        
        # VADER fallback
        if VADER_AVAILABLE and not self.model_loaded:
            self.vader = SentimentIntensityAnalyzer()
            self._add_crypto_lexicon()
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

    def _add_crypto_lexicon(self):
        """VADER'a kripto kelimeler ekle (fallback için)."""
        if not self.vader:
            return
        crypto_words = {
            "moon": 2.5, "mooning": 3.0, "bullish": 2.0, "bearish": -2.0,
            "pump": 1.5, "dump": -2.0, "rekt": -3.0, "hodl": 1.5,
            "fud": -1.5, "fomo": 1.0, "rally": 2.0, "rug": -3.5,
            "scam": -3.0, "hack": -2.5, "surge": 2.5, "crash": -3.0,
            "ath": 2.0, "accumulate": 1.5, "breakout": 2.5,
            "adoption": 2.0, "partnership": 1.8, "upgrade": 1.5,
        }
        self.vader.lexicon.update(crypto_words)

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
            
            # Kripto boost uygula
            boost = self._get_crypto_boost(text)
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

    def _get_crypto_boost(self, text: str) -> float:
        """Kripto-spesifik kelimeler için ek boost."""
        text_lower = text.lower()
        boost = 0.0
        for word, value in self.crypto_boost.items():
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
