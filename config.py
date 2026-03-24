"""
AI Trading Bot - Configuration
Tüm ayarlar bu dosyada merkezi olarak yönetilir.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# ALPACA API AYARLARI
# ============================================================
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # "paper" veya "live"

# Alpaca base URLs
ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_URL = "https://api.alpaca.markets"

def get_base_url():
    return ALPACA_PAPER_URL if TRADING_MODE == "paper" else ALPACA_LIVE_URL

# ============================================================
# RİSK YÖNETİMİ AYARLARI
# ============================================================
RISK_CONFIG = {
    "max_risk_per_trade_pct": 0.01,     # Tek işlemde max %1 risk
    "max_daily_loss_pct": 0.03,          # Günlük max %3 kayıp
    "max_position_size_pct": 0.20,       # Tek pozisyon max %20 sermaye
    "max_open_positions": 5,             # Max açık pozisyon sayısı
    "risk_reward_ratio": 2.0,            # Min risk/ödül oranı (1:2)
    "trailing_stop_pct": 0.02,           # Trailing stop %2
    "min_confidence_score": 0.6,         # Min sinyal güven puanı (%60)
}

# ============================================================
# KOMİSYON / FEE AYARLARI
# ============================================================
COMMISSION_CONFIG = {
    # Alpaca (hisse senedi): komisyon yok
    "stock_commission_per_share": 0.0,    # Alpaca = $0
    "stock_commission_pct": 0.0,          # Yüzde bazlı komisyon (bazı brokerlar)
    "stock_min_commission": 0.0,          # Min komisyon/trade

    # Kripto komisyonları
    "crypto_commission_pct": 0.0025,      # Alpaca kripto = %0.25
    "crypto_maker_fee_pct": 0.001,        # Maker fee (limit orders) %0.1
    "crypto_taker_fee_pct": 0.0025,       # Taker fee (market orders) %0.25

    # Düzenleyici ücretler (ABD hisse senedi — çok küçük ama hesaplanmalı)
    "sec_fee_per_dollar": 0.0000278,      # SEC fee (sadece satışta)
    "finra_taf_per_share": 0.000166,      # FINRA TAF (sadece satışta, max $8.30)

    # Slippage tahmini (fiyat kayması)
    "estimated_slippage_pct": 0.001,      # Tahmini %0.1 slippage

    # Minimum kâr eşiği: trade'in beklenen kârı, gidiş-dönüş
    # komisyonu geçemezse işlem yapma
    "min_profit_after_fees": True,        # Komisyon kontrolü aktif
}

# ============================================================
# HİSSE TARAMA (SCANNER) AYARLARI
# ============================================================
SCANNER_CONFIG = {
    "min_price": 2.0,                    # Min hisse fiyatı $2
    "max_price": 20.0,                   # Max hisse fiyatı $20
    "min_volume": 500_000,               # Min günlük hacim 500K
    "min_relative_volume": 1.5,          # Min göreceli hacim 1.5x
    "min_change_pct": 3.0,               # Min günlük değişim %3
    "max_float": 50_000_000,             # Max float 50M (opsiyonel)
    "top_n_results": 10,                 # En iyi N hisse göster
}

# ============================================================
# TEKNİK ANALİZ AYARLARI
# ============================================================
TECHNICAL_CONFIG = {
    # RSI
    "rsi_period": 14,
    "rsi_oversold": 30,                  # RSI < 30 → aşırı satılmış
    "rsi_overbought": 70,                # RSI > 70 → aşırı alınmış
    
    # EMA
    "ema_fast": 9,
    "ema_medium": 21,
    "ema_slow": 50,
    
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    
    # Bollinger Bands
    "bb_period": 20,
    "bb_std_dev": 2.0,
    
    # ATR (stop-loss hesabı için)
    "atr_period": 14,
    "atr_multiplier": 1.5,               # Stop-loss = fiyat - (ATR * 1.5)
    
    # VWAP
    "vwap_bounce_threshold": 0.005,      # VWAP'tan %0.5 sapma
}

# ============================================================
# STRATEJİ AYARLARI
# ============================================================
STRATEGY_CONFIG = {
    "enabled_strategies": [
        "rsi_ema",
        "vwap_bounce",
        "breakout",
    ],
    
    # Strateji ağırlıkları (oylama için)
    "strategy_weights": {
        "rsi_ema": 0.35,
        "vwap_bounce": 0.35,
        "breakout": 0.30,
    },
    
    # Minimum onay — en az bu ağırlık toplamında AL sinyali gerekli
    "min_buy_weight": 0.50,
    "min_sell_weight": 0.50,
}

# ============================================================
# ZAMANLAMA AYARLARI (US Eastern Time)
# ============================================================
SCHEDULE_CONFIG = {
    "market_open": "09:30",              # ET
    "market_close": "16:00",             # ET
    "scan_interval_seconds": 60,          # Her 60 saniyede tara
    "pre_market_scan": "09:00",          # Pre-market tarama başla
    "stop_trading_time": "15:45",        # Son 15 dakikada işlem yapma
    "timezone": "US/Eastern",
}

# ============================================================
# LOGLAMA AYARLARI
# ============================================================
LOG_CONFIG = {
    "log_dir": "logs",
    "log_level": "INFO",
    "trade_history_file": "trade_history.json",
    "max_log_files": 30,                  # Max 30 günlük log
}

# ============================================================
# DASHBOARD AYARLARI
# ============================================================
DASHBOARD_CONFIG = {
    "refresh_interval_seconds": 5,
    "port": 8501,
    "theme": "dark",
}

# ============================================================
# KILL SWITCH (ACİL DURUM) AYARLARI
# ============================================================
KILL_SWITCH_CONFIG = {
    "max_consecutive_api_errors": 3,     # 3 ardışık hata → tüm pozisyonları kapat
    "max_daily_loss_pct": 0.05,          # Günlük %5 kayıp → acil kapanış
    "auto_close_positions": True,        # Kill'de pozisyonları otomatik kapat
    "kill_state_file": "kill_switch.json",
}

# ============================================================
# EMİR TİPİ AYARLARI
# ============================================================
ORDER_CONFIG = {
    # Market order yerine Limit order tercih et (slippage koruması)
    "prefer_limit_orders": True,
    "limit_order_slippage_pct": 0.005,   # Limit fiyatı = fiyat × (1 + 0.5%)

    # Minimum hacim kontrolü (sığ hisselerde market order tehlikeli)
    "min_volume_for_market_order": 100_000,

    # Order timeout (dakika) — limit order dolmazsa iptal et
    "limit_order_timeout_minutes": 5,
}

# ============================================================
# VERİ KALİTESİ UYARILARI
# ============================================================
# ⚠️ ÖNEMLİ: Günlük al-sat (day trading/scalping) için GERÇEK ZAMANLI
# veri gereklidir. Ücretsiz API'lerin çoğu 15 DAKİKA GECİKMELİ veri verir!
#
# Çözümler:
# - Alpaca: Paper trading'de gerçek zamanlı veri verir
# - Alpaca Pro: Canlıda SIP (gerçek zamanlı NBBO) verisi
# - Polygon.io: Starter planı ($29/ay) ile gerçek zamanlı veri
# - "Non-Professional" veri sözleşmesi imzalamayı unutmayın
#
# Bot canlıya geçmeden ÖNCE veri gecikmesini mutlaka test edin!
DATA_CONFIG = {
    "require_realtime_data": True,       # Gerçek zamanlı veri zorunlu mu?
    "max_acceptable_delay_seconds": 5,   # Max kabul edilebilir gecikme
    "warn_on_delayed_data": True,        # Gecikmeli veri uyarısı
}

# ============================================================
# MERKEZİ COİN TANIMLARI (TÜM MODÜLLER BURADAN IMPORT EDER)
# ============================================================
# Alpaca symbol -> CoinGecko ID mapping
COIN_IDS = {
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
    "TRUMP": "trump-coin",
    "WIF": "dogwifhat",
}

# Coin anahtar kelimeleri (haber & sosyal medya arama)
COIN_SEARCH_TERMS = {
    "BTC": ["bitcoin", "btc", "satoshi"],
    "ETH": ["ethereum", "eth", "vitalik"],
    "SOL": ["solana", "sol"],
    "XRP": ["ripple", "xrp", "sec lawsuit"],
    "DOGE": ["dogecoin", "doge", "elon", "musk"],
    "SHIB": ["shiba inu", "shib", "shibarium"],
    "PEPE": ["pepe", "memecoin"],
    "LINK": ["chainlink", "link", "oracle"],
    "AVAX": ["avalanche", "avax"],
    "ADA": ["cardano", "ada"],
    "DOT": ["polkadot", "dot"],
    "LTC": ["litecoin"],
    "BONK": ["bonk"],
    "ARB": ["arbitrum"],
    "RENDER": ["render token"],
    "TRUMP": ["trump coin", "trump crypto"],
    "ONDO": ["ondo finance"],
    "WIF": ["dogwifhat", "wif"],
    "UNI": ["uniswap"],
    "AAVE": ["aave"],
}
