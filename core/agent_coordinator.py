"""
Agent Coordinator — Multi-Agent Karar Mimarisi

5 uzman ajan bağımsız analiz yapar, Coordinator ağırlıklı
oylama ile nihai BUY/SELL/HOLD kararını verir.

Ajanlar:
  1. TechAgent  — Teknik göstergeler (RSI, MACD, Ichimoku...)
  2. FundAgent  — Temel analiz (MCap, Volume, Supply...)
  3. SentAgent  — Duyarlılık (FinBERT + Fear&Greed)
  4. SocialAgent — Sosyal medya (Reddit, X, Trends, Whale)
  5. RiskAgent  — Risk yönetimi (ATR, drawdown, korelasyon)

Kurallar:
  - Çoğunluk: ≥3 ajan aynı yönde olmalı
  - Risk vetosu: RiskAgent SELL → BUY yapılamaz
"""
from typing import Dict, List, Optional
from utils.logger import logger


class AgentVote:
    """Tek bir ajanın oy sonucu."""
    def __init__(self, agent_name: str, signal: str, confidence: float, reasoning: str):
        self.agent_name = agent_name
        self.signal = signal  # BUY, SELL, HOLD
        self.confidence = confidence  # 0-100
        self.reasoning = reasoning

    def to_dict(self):
        return {
            "agent": self.agent_name,
            "signal": self.signal,
            "confidence": round(self.confidence, 1),
            "reasoning": self.reasoning,
        }


class TechAgent:
    """Teknik analiz ajanı — RSI, MACD, Ichimoku, ADX, OBV, Fibonacci, Divergence."""
    
    NAME = "TechAgent"
    
    def analyze(self, tech_data: Dict) -> AgentVote:
        score = tech_data.get("tech_score", 0)
        confidence = min(abs(score) * 1.5, 100)
        
        reasons = []
        
        # RSI
        rsi = tech_data.get("rsi", 50)
        if rsi < 30:
            reasons.append(f"RSI={rsi:.0f} oversold")
        elif rsi > 72:
            reasons.append(f"RSI={rsi:.0f} overbought")
        
        # MACD
        macd_signal = tech_data.get("macd_signal", "NEUTRAL")
        if macd_signal != "NEUTRAL":
            reasons.append(f"MACD={macd_signal}")
        
        # Ichimoku
        ichimoku = tech_data.get("ichimoku_signal", "NEUTRAL")
        if ichimoku != "NEUTRAL":
            reasons.append(f"Ichimoku={ichimoku}")
        
        # ADX
        adx = tech_data.get("adx", 0)
        if adx > 25:
            reasons.append(f"ADX={adx:.0f} güçlü trend")
        
        # Sinyal belirle
        if score >= 15:
            signal = "BUY"
        elif score <= -15:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        return AgentVote(
            self.NAME, signal, confidence,
            " | ".join(reasons) if reasons else "Nötr teknik görünüm"
        )


class FundAgent:
    """Temel analiz ajanı — MCap, Volume, Supply, Momentum."""
    
    NAME = "FundAgent"
    
    def analyze(self, fund_data: Dict) -> AgentVote:
        score = fund_data.get("fundamental_score", 0)
        confidence = min(abs(score) * 2, 100)
        
        reasons = []
        
        mcap_change = fund_data.get("mcap_change_24h", 0)
        if abs(mcap_change) > 5:
            reasons.append(f"MCap 24h:{mcap_change:+.1f}%")
        
        volume_spike = fund_data.get("volume_spike", False)
        if volume_spike:
            reasons.append("Volume spike tespit edildi")
        
        momentum = fund_data.get("price_momentum", {})
        m_7d = momentum.get("7d", 0)
        if abs(m_7d) > 10:
            reasons.append(f"7d momentum:{m_7d:+.1f}%")
        
        if score >= 10:
            signal = "BUY"
        elif score <= -10:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        return AgentVote(
            self.NAME, signal, confidence,
            " | ".join(reasons) if reasons else "Nötr temel görünüm"
        )


class SentAgent:
    """Duyarlılık ajanı — FinBERT/VADER + Fear&Greed + Haberler."""
    
    NAME = "SentAgent"
    
    def analyze(self, sent_data: Dict) -> AgentVote:
        news_score = sent_data.get("news_score", 0)
        fg_value = sent_data.get("fear_greed_value", 50)
        fg_signal = sent_data.get("fear_greed_signal", "NEUTRAL")
        
        confidence = min(abs(news_score) * 1.5, 100)
        
        reasons = []
        
        if fg_value < 25:
            reasons.append(f"Fear&Greed={fg_value} EXTREME FEAR (contrarian BUY)")
        elif fg_value > 75:
            reasons.append(f"Fear&Greed={fg_value} EXTREME GREED (contrarian SELL)")
        
        sentiment_label = sent_data.get("sentiment_label", "NEUTRAL")
        if sentiment_label not in ("NEUTRAL",):
            reasons.append(f"Haber sentiment: {sentiment_label}")
        
        # Contrarian mantık + haber skoru
        combined = news_score
        if fg_signal in ("STRONG_BUY", "BUY"):
            combined += 10
        elif fg_signal in ("STRONG_SELL", "SELL"):
            combined -= 10
        
        if combined >= 12:
            signal = "BUY"
        elif combined <= -12:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        return AgentVote(
            self.NAME, signal, confidence,
            " | ".join(reasons) if reasons else "Nötr sentiment"
        )


class SocialAgent:
    """Sosyal medya ajanı — Reddit, X, CoinGecko Trending, Whale Alert."""
    
    NAME = "SocialAgent"
    
    def analyze(self, social_data: Dict) -> AgentVote:
        score = social_data.get("social_score", 0)
        confidence = min(abs(score) * 2, 100)
        
        reasons = []
        
        reddit_posts = social_data.get("reddit_posts", 0)
        if reddit_posts > 10:
            reasons.append(f"Reddit: {reddit_posts} post")
        
        x_tweets = social_data.get("x_tweets", 0)
        if x_tweets > 5:
            x_sent = social_data.get("x_sentiment", 0)
            reasons.append(f"X: {x_tweets} tweet (sent:{x_sent:.2f})")
        
        if social_data.get("coingecko_trending", False):
            reasons.append("CoinGecko TRENDING")
        
        whale_score = social_data.get("whale_score", 0)
        if whale_score != 0:
            reasons.append(f"Whale skor: {whale_score:+d}")
        
        if social_data.get("social_spike", False):
            reasons.append("⚠️ Sosyal hacim SPIKE!")
        
        if score >= 10:
            signal = "BUY"
        elif score <= -10:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        return AgentVote(
            self.NAME, signal, confidence,
            " | ".join(reasons) if reasons else "Nötr sosyal aktivite"
        )


class RiskAgent:
    """
    Risk yönetim ajanı — ATR, drawdown, pozisyon limiti, korelasyon.
    
    ÖNEMLİ: RiskAgent'ın SELL oyu → BUY'ı veto eder!
    """
    
    NAME = "RiskAgent"
    
    def analyze(self, risk_data: Dict) -> AgentVote:
        reasons = []
        risk_score = 0
        
        # Günlük kayıp kontrolü
        daily_pnl_pct = risk_data.get("daily_pnl_pct", 0)
        if daily_pnl_pct < -2.0:
            risk_score -= 30
            reasons.append(f"⚠️ Günlük kayıp: {daily_pnl_pct:.1f}%")
        
        # Açık pozisyon sayısı
        open_positions = risk_data.get("open_positions", 0)
        max_positions = risk_data.get("max_positions", 2)
        if open_positions >= max_positions:
            risk_score -= 25
            reasons.append(f"Max pozisyon dolu: {open_positions}/{max_positions}")
        
        # ATR volatilite
        atr_pct = risk_data.get("atr_pct", 0)
        if atr_pct > 5:
            risk_score -= 15
            reasons.append(f"Yüksek volatilite ATR={atr_pct:.1f}%")
        
        # Korelasyon riski
        contagion_risk = risk_data.get("contagion_risk_score", 0)
        if contagion_risk > 60:
            risk_score -= 20
            reasons.append(f"Bulaşma riski yüksek: {contagion_risk}")
        
        # ESG riski
        esg_risk = risk_data.get("esg_risk_level", "MEDIUM")
        if esg_risk == "HIGH":
            risk_score -= 10
            reasons.append("ESG risk: YÜKSEK")
        
        # Equity floor kontrolü
        equity_floor_hit = risk_data.get("equity_floor_hit", False)
        if equity_floor_hit:
            risk_score -= 50
            reasons.append("🛑 EQUITY FLOOR! Bot durmalı!")
        
        # Sinyal belirle
        if risk_score <= -30:
            signal = "SELL"  # VETO!
        elif risk_score <= -15:
            signal = "HOLD"
        else:
            signal = "BUY"  # Risk uygun, işlem yapılabilir
        
        confidence = min(abs(risk_score) + 30, 100)
        
        return AgentVote(
            self.NAME, signal, confidence,
            " | ".join(reasons) if reasons else "Risk seviyeleri normal"
        )


class AgentCoordinator:
    """
    5 uzman ajanın kararlarını birleştiren koordinatör.
    
    Ağırlıklar:
      TechAgent:   %25
      FundAgent:   %20
      SentAgent:   %20
      SocialAgent: %15
      RiskAgent:   %20
    
    Kurallar:
      1. Çoğunluk: ≥3 ajan aynı yönde → işlem
      2. Risk vetosu: RiskAgent SELL → BUY engellenir
    """

    WEIGHTS = {
        "TechAgent": 0.25,
        "FundAgent": 0.20,
        "SentAgent": 0.20,
        "SocialAgent": 0.15,
        "RiskAgent": 0.20,
    }

    def __init__(self):
        self.tech_agent = TechAgent()
        self.fund_agent = FundAgent()
        self.sent_agent = SentAgent()
        self.social_agent = SocialAgent()
        self.risk_agent = RiskAgent()
        
        self.last_decision = None
        logger.info("Agent Coordinator baslatildi — 5 uzman ajan aktif")

    def decide(self, symbol: str, 
               tech_data: Dict, fund_data: Dict,
               sent_data: Dict, social_data: Dict,
               risk_data: Dict) -> Dict:
        """
        Tüm ajanlardan oy al ve nihai kararı ver.
        
        Returns:
            {
                'signal': 'BUY' | 'SELL' | 'HOLD',
                'confidence': float (0-100),
                'votes': [AgentVote],
                'majority': bool,
                'risk_veto': bool,
                'reasoning': str
            }
        """
        # 1. Her ajandan oy al
        votes = [
            self.tech_agent.analyze(tech_data),
            self.fund_agent.analyze(fund_data),
            self.sent_agent.analyze(sent_data),
            self.social_agent.analyze(social_data),
            self.risk_agent.analyze(risk_data),
        ]
        
        # 2. Oyları say
        buy_count = sum(1 for v in votes if v.signal == "BUY")
        sell_count = sum(1 for v in votes if v.signal == "SELL")
        hold_count = sum(1 for v in votes if v.signal == "HOLD")
        
        # 3. Ağırlıklı skor hesapla
        weighted_score = 0
        total_confidence = 0
        
        for vote in votes:
            weight = self.WEIGHTS.get(vote.agent_name, 0.15)
            signal_value = {"BUY": 1, "SELL": -1, "HOLD": 0}[vote.signal]
            weighted_score += signal_value * weight * vote.confidence
            total_confidence += vote.confidence * weight
        
        # 4. Risk vetosu kontrolü
        risk_vote = votes[4]  # RiskAgent her zaman son
        risk_veto = False
        
        if risk_vote.signal == "SELL":
            risk_veto = True
        
        # 5. Çoğunluk kontrolü
        majority = False
        
        if buy_count >= 3:
            preliminary_signal = "BUY"
            majority = True
        elif sell_count >= 3:
            preliminary_signal = "SELL"
            majority = True
        elif weighted_score > 15:
            preliminary_signal = "BUY"
        elif weighted_score < -15:
            preliminary_signal = "SELL"
        else:
            preliminary_signal = "HOLD"
        
        # 6. Risk vetosu uygula
        final_signal = preliminary_signal
        if risk_veto and preliminary_signal == "BUY":
            final_signal = "HOLD"
            logger.warning(
                f"  ⚠️ {symbol} RiskAgent VETO! BUY -> HOLD "
                f"({risk_vote.reasoning})"
            )
        
        # 7. Güven hesapla
        confidence = total_confidence
        if majority:
            confidence *= 1.2  # Çoğunluk = daha güvenli
        if risk_veto:
            confidence *= 0.5  # Veto = güven düşer
        confidence = min(confidence, 100)
        
        # 8. Gerekçe oluştur
        vote_summary = f"BUY:{buy_count} SELL:{sell_count} HOLD:{hold_count}"
        reasoning_parts = [
            f"Oylama: {vote_summary}",
            f"Ağırlıklı skor: {weighted_score:.1f}",
        ]
        if majority:
            reasoning_parts.append("Çoğunluk sağlandı")
        if risk_veto:
            reasoning_parts.append(f"RİSK VETO: {risk_vote.reasoning}")
        
        result = {
            "signal": final_signal,
            "confidence": round(confidence, 1),
            "weighted_score": round(weighted_score, 1),
            "votes": [v.to_dict() for v in votes],
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
            "majority": majority,
            "risk_veto": risk_veto,
            "reasoning": " | ".join(reasoning_parts),
        }
        
        self.last_decision = result
        
        # Log
        logger.info(
            f"  Coordinator {symbol}: {final_signal} "
            f"(guven:{confidence:.0f}%) "
            f"[{vote_summary}] "
            f"{'COGUNLUK' if majority else 'tekil'} "
            f"{'⚠️VETO' if risk_veto else ''}"
        )
        for v in votes:
            logger.debug(
                f"    {v.agent_name}: {v.signal} "
                f"({v.confidence:.0f}%) — {v.reasoning}"
            )
        
        return result
