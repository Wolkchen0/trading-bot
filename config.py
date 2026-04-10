"""
AI Trading Bot - Configuration
Hisse senedi odaklı al-sat stratejisi.
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

# Haber & Veri API'leri
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
MARKETAUX_TOKEN = os.getenv("MARKETAUX_TOKEN", "")

# Alpaca base URLs
ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_URL = "https://api.alpaca.markets"

def get_base_url():
    return ALPACA_PAPER_URL if TRADING_MODE == "paper" else ALPACA_LIVE_URL

# ============================================================
# HİSSE TANIMI — STOCK_IDS (tüm modüller buradan import eder)
# ============================================================
STOCK_IDS = {
    # Mega Cap
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "NVDA": "NVIDIA Corp.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    # Growth
    "AMD": "Advanced Micro Devices",
    "SOFI": "SoFi Technologies",
    "PLTR": "Palantir Technologies",
    "COIN": "Coinbase Global",
    "SQ": "Block Inc.",
    "SHOP": "Shopify Inc.",
    "CRWD": "CrowdStrike Holdings",
    # Momentum
    "RIVN": "Rivian Automotive",
    "NIO": "NIO Inc.",
    "LCID": "Lucid Group",
    "MARA": "Marathon Digital",
    "RIOT": "Riot Platforms",
    "SMCI": "Super Micro Computer",
}

# Hisse arama terimleri (haber & sosyal medya)
STOCK_SEARCH_TERMS = {
    "AAPL": ["apple", "iphone", "tim cook", "apple earnings"],
    "MSFT": ["microsoft", "azure", "satya nadella", "windows", "copilot"],
    "GOOGL": ["google", "alphabet", "youtube", "gemini ai", "search"],
    "AMZN": ["amazon", "aws", "prime", "bezos", "jassy"],
    "NVDA": ["nvidia", "gpu", "jensen huang", "ai chips", "cuda"],
    "META": ["meta", "facebook", "instagram", "zuckerberg", "metaverse"],
    "TSLA": ["tesla", "elon musk", "ev", "cybertruck", "autopilot"],
    "AMD": ["amd", "ryzen", "radeon", "lisa su", "epyc"],
    "SOFI": ["sofi", "student loans", "fintech", "noto"],
    "PLTR": ["palantir", "data analytics", "karp", "government contract"],
    "COIN": ["coinbase", "crypto exchange", "sec coinbase"],
    "SQ": ["block", "square", "cash app", "dorsey"],
    "SHOP": ["shopify", "ecommerce", "tobi lutke"],
    "CRWD": ["crowdstrike", "cybersecurity", "george kurtz"],
    "RIVN": ["rivian", "electric truck", "r1t", "r1s"],
    "NIO": ["nio", "chinese ev", "william li"],
    "LCID": ["lucid", "lucid air", "ev sedan"],
    "MARA": ["marathon digital", "bitcoin mining"],
    "RIOT": ["riot platforms", "crypto mining"],
    "SMCI": ["super micro", "supermicro", "ai server"],
}

# Jeopolitik anahtar kelimeler (tüm modüller kullanır)
# Her kelime = (keyword, severity_weight) — ağırlıklı etki
GEOPOLITICAL_KEYWORDS = {
    "bearish": [
        # === SAVAŞ / ÇATIŞMA ===
        "war escalat", "military strike", "missile", "airstrike",
        "bombing", "invasion", "retaliati", "ground offensive",
        "drone attack", "drone strike", "artillery", "shelling",
        "ceasefire violat", "ceasefire collapse", "truce broken",
        "ceasefire ended", "resumed attack", "resumed fighting",
        "resumed hostil", "broke ceasefire", "conflict resum",
        # === ORTA DOĞU ===
        "iran attack", "iran strike", "iran retali", "houthi",
        "strait of hormuz", "red sea attack", "hezbollah",
        "gaza escalat", "west bank", "lebanon strike",
        "gulf tension", "iran israel", "iran nuclear",
        # === ÇİN / ASYA ===
        "china taiwan", "taiwan strait", "south china sea",
        "north korea", "korean peninsula", "china sanction",
        # === UKRAYNA / RUSYA ===
        "ukraine escalat", "russia attack", "nato escalat",
        "nuclear threat", "nuclear weapon", "tactical nuke",
        # === ENERJİ ===
        "oil surge", "oil spike", "oil supply cut", "opec cut",
        "pipeline attack", "energy crisis", "gas shortage",
        "supply disruption", "blockade", "embargo",
        # === EKONOMİK SAVAŞ ===
        "sanctions", "tariff", "trade war", "export ban",
        "chip ban", "tech ban", "economic warfare",
        # === FİNANSAL KRİZ ===
        "recession", "debt default", "bank failure", "credit crisis",
        "sovereign default", "debt ceiling", "systemic risk",
        "contagion", "bank run", "liquidity crisis",
        # === TERORİZM ===
        "terror attack", "terrorist", "mass casualt", "hostage",
    ],
    "bullish": [
        "ceasefire", "ceasefire agreed", "ceasefire hold",
        "peace deal", "peace agreement", "peace talks progress",
        "trade agreement", "trade deal", "sanctions lifted",
        "sanctions eased", "diplomati", "negotiations resume",
        "de-escalat", "troops withdraw", "withdrawal",
        "rate cut", "stimulus", "infrastructure bill",
        "oil drop", "oil price fall", "opec increase",
        "ceasefire extended", "hostage release", "prisoner swap",
    ],
}

# ============================================================
# SEKTÖR HARİTASI (korelasyon koruması için)
# ============================================================
SECTOR_MAP = {
    # Teknoloji
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "META": "Technology", "NVDA": "Semiconductors", "AMD": "Semiconductors",
    "SMCI": "Semiconductors", "CRWD": "Cybersecurity",
    # E-Ticaret / İnternet
    "AMZN": "E-Commerce", "SHOP": "E-Commerce",
    # Fintech
    "SOFI": "Fintech", "SQ": "Fintech", "COIN": "Fintech",
    # EV / Otomotiv
    "TSLA": "EV", "RIVN": "EV", "NIO": "EV", "LCID": "EV",
    # Kripto Madenciliği
    "MARA": "CryptoMining", "RIOT": "CryptoMining",
    # Data / AI
    "PLTR": "Data_AI",
}

# ============================================================
# RİSK YÖNETİMİ AYARLARI
# ============================================================
RISK_CONFIG = {
    "max_risk_per_trade_pct": 0.02,     # Tek işlemde max %2 risk
    "max_daily_loss_pct": 0.03,          # Günlük max %3 kayıp
    "max_position_size_pct": 0.30,       # Tek pozisyon max %30 sermaye
    "max_open_positions": 3,             # Max 3 açık pozisyon
    "risk_reward_ratio": 2.0,            # Min risk/ödül oranı (1:2)
    "trailing_stop_pct": 0.03,           # Trailing stop %3
    "min_confidence_score": 50,          # Min sinyal güven puanı (%50)
}

# ============================================================
# KOMİSYON / FEE AYARLARI
# ============================================================
COMMISSION_CONFIG = {
    # Alpaca hisse senedi: komisyon YOK!
    "stock_commission_per_share": 0.0,
    "stock_commission_pct": 0.0,
    "stock_min_commission": 0.0,

    # Düzenleyici ücretler (çok küçük — sadece satışta)
    "sec_fee_per_dollar": 0.0000278,
    "finra_taf_per_share": 0.000166,

    # Slippage tahmini
    "estimated_slippage_pct": 0.001,

    # Minimum kâr eşiği
    "min_profit_after_fees": True,
}

# ============================================================
# TEKNİK ANALİZ AYARLARI
# ============================================================
TECHNICAL_CONFIG = {
    # RSI
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    
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
    "atr_multiplier": 1.5,
    
    # VWAP
    "vwap_bounce_threshold": 0.005,
}

# ============================================================
# STOCK BOT ANA KONFİGÜRASYON
# ============================================================
STOCK_CONFIG = {
    # === HİSSE HAVUZU ===
    "symbols": list(STOCK_IDS.keys()),

    # === Pozisyon ağırlıkları (tier bazlı) ===
    "tier_weights": {
        # Mega cap — %40
        "AAPL": 0.40, "MSFT": 0.40, "GOOGL": 0.40, "AMZN": 0.40,
        "NVDA": 0.40, "META": 0.40, "TSLA": 0.35,
        # Growth — %35
        "AMD": 0.35, "SOFI": 0.30, "PLTR": 0.30, "COIN": 0.30,
        "SQ": 0.30, "SHOP": 0.30, "CRWD": 0.30,
        # Momentum — %25
        "RIVN": 0.25, "NIO": 0.25, "LCID": 0.25,
        "MARA": 0.25, "RIOT": 0.25, "SMCI": 0.25,
    },
    "default_tier_weight": 0.20,

    # === RISK YÖNETİMİ ===
    "max_risk_per_trade_pct": 0.02,
    "max_position_pct": 0.30,
    "max_position_usd": 200,               # Küçük hesap: max $200/trade
    "live_max_position_usd": 200,
    "max_open_positions": 3,
    "cash_reserve_pct": 0.15,               # %15 nakit rezerv
    "equity_floor_pct": 0.85,               # Hesap %85'ine düşerse dur

    # === STOP/PROFIT HEDEFLERİ ===
    "stop_loss_pct": 0.03,                  # %3 stop-loss
    "stop_loss_max_pct": 0.05,              # %5 max stop
    "atr_stop_multiplier": 1.5,
    "take_profit_pct": 0.06,                # %6 take-profit (2:1 R:R)
    "trailing_stop_pct": 0.03,              # %3 trailing stop
    "partial_profit_pct": 0.04,             # %4'de yarısını sat

    # === SINYAL EŞİKLERİ ===
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "min_volume_ratio": 1.3,
    "trend_ema_period": 50,

    # === GATE FİLTRELERİ ===
    "ema200_trend_gate": True,
    "time_filter_enabled": True,            # Piyasa saatleri kontrolü
    "earnings_gate_enabled": True,          # Earnings koruma
    "volatility_filter_enabled": True,
    "max_atr_pct": 0.05,                    # ATR > %5 ise alım yapma
    "bb_proximity_pct": 0.01,               # BB bant yakınlık eşiği (%1)

    # === SEKTÖR KORELASYON KORUMASI ===
    "max_positions_per_sector": 2,           # Aynı sektörde max 2 pozisyon

    # === KAYIP SERİSİ KORUYUCU ===
    "loss_streak_enabled": True,
    "loss_streak_warn": 2,                  # 2 ardışık zarar → güven yükselt
    "loss_streak_halt": 4,                  # 4 ardışık zarar → 1 gün alım yasağı
    "loss_streak_halt_hours": 24,
    "loss_streak_elevated_conf": 70,
    "coin_filter_enabled": True,            # Hisse bazlı ardışık zarar filtresi
    "coin_max_consecutive_losses": 3,

    # === R:R GATE ===
    "rr_gate_enabled": True,
    "min_rr_ratio": 2.0,

    # === MULTI-TIMEFRAME ===
    "multi_tf_enabled": True,

    # === BREAK-EVEN STOP ===
    "breakeven_enabled": True,
    "breakeven_trigger_pct": 0.025,
    "breakeven_offset_pct": 0.003,

    # === PDT AYARLARI ===
    "max_day_trades_per_week": 2,
    "pdt_equity_threshold": 25000,

    # === ZAMANLAMA ===
    "scan_interval_seconds": 30,            # Her 30 saniyede tara
    "min_interval_high_conf": 10,           # %65+ güven: 10dk
    "min_interval_med_conf": 20,            # %55-64 güven: 20dk
    "min_interval_low_conf": 30,            # %50-54 güven: 30dk
    "sell_cooldown_seconds": 300,            # 5 dakika satış cooldown (swing trade)

    # === KILL SWITCH ===
    "max_daily_loss_pct": 0.03,             # %3 günlük max kayıp
    "max_consecutive_errors": 5,

    # === ZAMANLAMA SABİTLERİ ===
    "error_retry_sleep": 30,
    "heartbeat_interval": 30,
    "status_report_interval": 5,
    "min_position_close_usd": 5.0,

    # === KOMİSYON (HİSSE = $0) ===
    "commission_pct": 0.0,
    "min_trade_value": 10.0,
}

# ============================================================
# ZAMANLAMA AYARLARI (US Eastern Time)
# ============================================================
SCHEDULE_CONFIG = {
    "market_open": "09:30",
    "market_close": "16:00",
    "scan_interval_seconds": 30,
    "pre_market_scan": "09:00",
    "stop_trading_time": "15:45",
    "timezone": "US/Eastern",
}

# ============================================================
# LOGLAMA AYARLARI
# ============================================================
LOG_CONFIG = {
    "log_dir": "logs",
    "log_level": "INFO",
    "trade_history_file": "trade_history.json",
    "max_log_files": 30,
}

# ============================================================
# KILL SWITCH (ACİL DURUM) AYARLARI
# ============================================================
KILL_SWITCH_CONFIG = {
    "max_consecutive_api_errors": 3,
    "max_daily_loss_pct": 0.05,
    "auto_close_positions": True,
    "kill_state_file": "kill_switch.json",
}

# ============================================================
# EMİR TİPİ AYARLARI
# ============================================================
ORDER_CONFIG = {
    "prefer_limit_orders": True,
    "limit_order_slippage_pct": 0.005,
    "min_volume_for_market_order": 100_000,
    "limit_order_timeout_minutes": 5,
}

# ============================================================
# VERİ KALİTESİ
# ============================================================
DATA_CONFIG = {
    "require_realtime_data": True,
    "max_acceptable_delay_seconds": 5,
    "warn_on_delayed_data": True,
}
