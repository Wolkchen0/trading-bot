"""
Kripto Trading Bot - $100 Bütçe ile 7/24 Otomatik Al-Sat
Alpaca Paper Trading API üzerinden çalışır.

Kullanım:
    python crypto_bot.py              # Paper trading (varsayılan)
    python crypto_bot.py --live       # Gerçek para (dikkat!)

Desteklenen coinler: BTC/USD, ETH/USD, DOGE/USD, SOL/USD, AVAX/USD
"""
import os
import sys
import time
import json
import argparse
import atexit
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# Proje kök dizinini ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, StopLimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from utils.logger import logger
from core.news_analyzer import NewsAnalyzer
from core.pattern_detector import PatternDetector
from core.macro_data import MacroDataAnalyzer
from core.ml_predictor import MLPredictor
from core.fundamental_analyzer import FundamentalAnalyzer
from core.finbert_analyzer import FinBERTAnalyzer
from core.agent_coordinator import AgentCoordinator
from core.esg_analyzer import ESGAnalyzer
from core.correlation_network import CorrelationNetwork
from core.analyzer import TechnicalAnalyzer
from core.executor import OrderExecutor
from core.position_manager import PositionManager
from core.trade_gates import TradeGates

# ============================================================
# KONFİGÜRASYON — $500-1000 GERCEK HESAP + KRIZ STRATEJISI
# ============================================================
#
# STRATEJI: Hibrit — Scalp + Swing + Kriz
# -----------------------------------------------
# 1. SCALP: Hizli al-sat, %1.5-2 kar hedefi, cok islem
# 2. SWING: Guclu sinyalde %4-6 kar hedefi, uzun tut
# 3. KRIZ: Jeopolitik haber ile dip alimi
#
# $500 ile gunluk hedef: $5-15 (%1-3)
# $1000 ile gunluk hedef: $10-30 (%1-3)
#
# LIVE GUVENLIK KATMANLARI:
# 1. .env TRADING_MODE=live secece live calisir
# 2. max_position_usd yerine live_max_position_usd kullanilir (daha dusuk)
# 3. equity_floor: hesap bu seviyenin altina duserse bot durur
# Aylik bilesik: %30-90 potansiyel (agresif)
# -----------------------------------------------
CRYPTO_CONFIG = {
    # ============================================================
    # KUCUK HESAP ($500-1000) GUNLUK KAZANC MODU
    # ============================================================
    # Backtest sonucu: $1000 ile 30 gunde 24 islem, -$28.82
    # Sorun: Komisyon ($29) > Gercek kayip ($0) → az ama kaliteli islem!
    # Hedef: Gunluk $3-10 net kazanc ($500 hesap = %0.6-2/gun)
    # ============================================================

    # Coin secimi: OPTIMIZED — sadece kârli coinler (ADA/DOT/AVAX/LTC çıkarıldı)
    # Backtest Q1 2026: ADA -$16, DOT -$18, AVAX -$5, LTC -$5 → toplam -$44 zarar
    "symbols": [
        # TIER 1 — En iyi performans
        "BTC/USD", "SOL/USD", "ETH/USD",
        # TIER 2 — İyi likidite + volatilite
        "XRP/USD", "LINK/USD", "DOGE/USD",
        # TIER 3 — Yüksek volatilite (fırsatçı)
        "PEPE/USD", "SHIB/USD",
    ],

    # Pozisyon ağırlıkları — daraltılmış havuz, daha büyük ağırlıklar
    "tier_weights": {
        "BTC/USD": 0.45, "SOL/USD": 0.45, "ETH/USD": 0.40,
        "XRP/USD": 0.40, "LINK/USD": 0.40, "DOGE/USD": 0.35,
        "PEPE/USD": 0.25, "SHIB/USD": 0.25,
    },
    "default_tier_weight": 0.25,

    # === RISK YONETIMI ($500-1000 GERCEK HESAP) ===
    "max_risk_per_trade_pct": 0.02,     # %2 risk per trade ($500 = max $10 kayip)
    "max_position_pct": 0.45,           # Tek pozisyon max %45 ($500 = $225)
    "max_position_usd": 300,            # MUTLAK LIMIT: paper'da max $300
    "live_max_position_usd": 300,       # LIVE LIMIT: gercek parada max $300 (komisyon etkisini minimize et)
    "max_open_positions": 2,            # Max 2 pozisyon ($500'de yogunlastir)
    "cash_reserve_pct": 0.10,           # %10 nakit rezerv ($500 = $50 yedek)
    "micro_account_threshold": 600,     # $600 altinda ekstra koruma
    "equity_floor_pct": 0.80,           # LIVE: hesap baslangicin %80'ine duserse DUR ($500=%400)

    # === SCALP HEDEFLERI (KUCUK HESAP OPTIMIZE) ===
    # Komisyon gidis-donus: %0.5 → kari en az %1.0 olmali
    # Risk/Odul: 1:2.3 (iyi oran)
    "stop_loss_pct": 0.025,             # %2.5 MINIMUM stop (ATR adaptif alt sinir — kripto volatilitesine uygun)
    "stop_loss_max_pct": 0.04,           # %4 MAKSIMUM stop (ATR adaptif ust sinir)
    "atr_stop_multiplier": 1.5,          # ATR carpani: stop = 1.5 * ATR%
    "take_profit_pct": 0.050,           # %5.0 take-profit (2:1 R:R korunur)
    "trailing_stop_pct": 0.020,         # %2.0 trailing stop (erken çıkışı önle)
    "partial_profit_pct": 0.030,        # %3.0'de yarisini sat (kârı büyüt)

    # === SINYAL (KALITE ODAKLI — AZ AMA ISABETLI) ===
    "rsi_oversold": 30,                 # RSI 30 = gercek dip (daha secici)
    "rsi_overbought": 72,               # RSI 72 = tepe
    "bb_proximity_pct": 0.012,          # BB alt bant %1.2 yakinlik
    "min_volume_ratio": 1.3,            # Volume 1.3x (biraz daha secici)
    "trend_ema_period": 50,

    # === TREND FİLTRESİ ===
    "ema200_trend_gate": True,          # EMA200 alti = BUY engelle

    # === ZAMAN FİLTRESİ ===
    "time_filter_enabled": True,        # Dusuk likidite saatlerinde alim yapma
    "time_filter_start_utc": 0,         # 00:00 UTC
    "time_filter_end_utc": 6,           # 06:00 UTC

    # === KAYIP SERİSİ KORUYUCU ===
    "loss_streak_enabled": True,
    "loss_streak_warn": 3,              # 3 ardisik zarar → guven %70'e yukselt
    "loss_streak_halt": 5,              # 5 ardisik zarar → 6 saat alim yasagi
    "loss_streak_halt_hours": 6,
    "loss_streak_elevated_conf": 70,

    # === COIN FILTRELEME ===
    "coin_filter_enabled": True,
    "coin_max_consecutive_losses": 3,   # 3 ardisik zararda coin devre disi

    # === R:R GATE (Risk/Ödül Oranı) ===
    "rr_gate_enabled": True,
    "min_rr_ratio": 2.0,                # Min 2:1 risk/ödül oranı

    # === MULTI-TIMEFRAME ONAY ===
    "multi_tf_enabled": True,
    "multi_tf_4h_required": True,       # 4h trend onayı gerekli

    # === BREAK-EVEN STOP ===
    "breakeven_enabled": True,
    "breakeven_trigger_pct": 0.020,     # %2.0 karda break-even aktif (dalgalanma payı)
    "breakeven_offset_pct": 0.002,      # Giris fiyatinin %0.2 ustune koy (komisyon)

    # === VOLATİLİTE FİLTRESİ ===
    "volatility_filter_enabled": True,
    "max_atr_pct": 0.06,                # ATR > %6 ise alım yapma (flash crash riski)

    # === SUPPORT/RESISTANCE ===
    "sr_enabled": True,
    "sr_lookback_bars": 50,             # S/R için son 50 bar
    "sr_proximity_pct": 0.015,          # Fiyat S/R'ye %1.5 yakınsa aksiyon al

    # === KOMISYON FARKINDALIGI ===
    "commission_pct": 0.0025,           # Alpaca %0.25
    "min_trade_value": 10.0,            # Min $10 islem (komisyon etkisi icin)

    # === ZAMANLAMA (DINAMIK — GUCLU SINYAL = HIZLI ISLEM) ===
    "scan_interval_seconds": 10,        # Her 10 saniyede tara (hizli tepki)
    # Dinamik trade araligi: guclu sinyal hizli gir, zayif sinyal bekle
    "min_interval_high_conf": 5,        # %65+ guven: 5dk (guclu firsat, kacirma)
    "min_interval_med_conf": 10,        # %55-64 guven: 10dk
    "min_interval_low_conf": 20,        # %50-54 guven: 20dk (zayif sinyal, bekle)

    # === KILL SWITCH (KUCUK HESAP KORUMASI) ===
    "max_daily_loss_pct": 0.025,        # %2.5 gunluk kayip ($500 = $12.5 max)
    "max_consecutive_errors": 5,

    # === GÜNLÜK MİNİMUM İŞLEM ===
    "min_daily_trades": 1,              # Günde en az 1 işlem hedefi
    "min_daily_trade_relax_hour_utc": 12, # 12:00 UTC'den sonra eşik düşür
    "min_daily_trade_confidence": 50,    # Relaxed confidence (normal: 60)

    # === ZAMANLAMA SABİTLERİ ===
    "error_retry_sleep": 30,            # Hata sonrası bekleme (saniye)
    "heartbeat_interval": 30,           # Her N döngüde heartbeat logla
    "status_report_interval": 5,        # Her N döngüde durum raporu
    "min_position_close_usd": 5.0,      # Bu değerin altındaki pozisyonları kapa
}


# Lock file ile çift instance koruması
LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".crypto_bot.lock")

def _acquire_lock():
    """Lock file oluşturarak çift instance'ı engelle."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # PID hala çalışıyor mu kontrol et
            try:
                os.kill(old_pid, 0)  # Sinyal göndermez, sadece varlık kontrolü
                logger.error(
                    f"UYARI: Baska bir CryptoBot instance'i zaten calisiyor (PID: {old_pid})!\n"
                    f"  Eger eski instance kapandiysa, '{LOCK_FILE}' dosyasini silin."
                )
                sys.exit(1)
            except (OSError, ProcessLookupError):
                # Eski PID artık çalışmıyor, lock'u temizle
                logger.warning(f"Eski lock temizlendi (PID {old_pid} artik calismiyor)")
                os.remove(LOCK_FILE)
        except (ValueError, IOError):
            os.remove(LOCK_FILE)

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(_release_lock)

def _release_lock():
    """Bot kapanınca lock file'ı sil."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


class CryptoBot:
    """$500-1000 gercek hesap icin optimize edilmis kripto trading botu."""

    def __init__(self, live: bool = False):
        # Çift instance koruması
        _acquire_lock()
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")

        if not self.api_key or not self.secret_key:
            logger.error("API key bulunamadi! .env dosyasini kontrol edin.")
            sys.exit(1)

        # === LIVE MOD GUVENLIK KONTROLU ===
        env_mode = os.getenv("TRADING_MODE", "paper").lower()
        if live and env_mode != "live":
            logger.error(
                "GUVENLIK: --live parametresi verildi ama .env'de TRADING_MODE=live degil!\n"
                "  Gercek para icin .env dosyasinda TRADING_MODE=live yapmaniz gerekiyor."
            )
            sys.exit(1)

        self.is_paper = not live
        self.client = TradingClient(
            self.api_key, self.secret_key, paper=self.is_paper
        )
        self.crypto_data = CryptoHistoricalDataClient()

        # Hesap bilgisi
        account = self.client.get_account()
        self.equity = float(account.equity)
        self.starting_equity = self.equity
        self.cash = float(account.cash)

        # LIVE: Equity floor — bu seviyenin altina duserse bot DURUR
        floor_pct = CRYPTO_CONFIG.get("equity_floor_pct", 0.80)
        self.equity_floor = self.starting_equity * floor_pct if not self.is_paper else 0

        # LIVE: Pozisyon limiti (paper'dan daha dusuk)
        if not self.is_paper:
            self.max_pos_usd = CRYPTO_CONFIG.get("live_max_position_usd", 150)
        else:
            self.max_pos_usd = CRYPTO_CONFIG.get("max_position_usd", 300)

        # Durum
        self.running = True
        self.consecutive_errors = 0
        self.daily_pnl = 0.0
        self.trades_today = []
        self.last_trade_time = {}
        self.positions = {}
        self.sell_cooldown = {}  # BUG FIX: satis dongusu onleme
        self.cycle_count = 0
        self._last_fg_value = 50  # Fear & Greed cache (varsayilan: notr)
        self._daily_buys_count = 0  # Günlük alım sayacı
        self._last_buy_date = None  # Son alım tarihi (sıfırlama için)

        # Haber analiz modülü
        self.news = NewsAnalyzer()

        # Desen tanıma modülü
        self.patterns = PatternDetector()

        # Makro ekonomik veri
        self.macro = MacroDataAnalyzer()
        self.macro_cache = None
        self.macro_last_check = None

        # Kayıp serisi ve coin filtresi takibi
        self._consecutive_losses = 0
        self._loss_halt_until = None
        self._coin_consecutive_losses = {}  # {symbol: ardisik_zarar_sayisi}

        # ML Tahmin modeli
        self.ml = MLPredictor()

        # Fundamental analiz
        self.fundamental = FundamentalAnalyzer()
        self.fundamental_cache = {}
        self.fundamental_last_check = {}

        # === FAZ 2 MODÜLLERİ ===
        # FinBERT NLP (VADER yerine derin öğrenme)
        self.finbert = FinBERTAnalyzer()
        finbert_status = self.finbert.get_status()
        
        # Multi-Agent Koordinatör (5 uzman ajan)
        self.coordinator = AgentCoordinator()
        
        # ESG Analiz (kripto sürdürülebilirlik)
        self.esg = ESGAnalyzer()
        
        # Korelasyon Ağı (bulaşma riski)
        self.correlation = CorrelationNetwork()
        self.correlation_last_update = None

        # === MODÜLER YAPI ===
        self.analyzer = TechnicalAnalyzer(self)
        self.executor = OrderExecutor(self)
        self.position_mgr = PositionManager(self)
        self.gates = TradeGates(self)

        # Loglama
        mode = "PAPER" if self.is_paper else "*** LIVE ***"
        logger.info("=" * 60)
        logger.info(f"  KRIPTO TRADING BOT BASLATILDI [{mode}]")
        logger.info(f"  Bakiye: ${self.equity:,.2f}")
        logger.info(f"  Max pozisyon: ${self.max_pos_usd} per trade")
        logger.info(f"  Coinler: {', '.join(CRYPTO_CONFIG['symbols'])}")
        logger.info(f"  Stop-loss: {CRYPTO_CONFIG['stop_loss_pct']:.0%}")
        logger.info(f"  Take-profit: {CRYPTO_CONFIG['take_profit_pct']:.0%}")
        logger.info(f"  NLP: {finbert_status['active_source'].upper()}")
        logger.info(f"  Moduller: Teknik+Desen+Haber+Sosyal+Makro+ML+Fund+ESG+GNN+MultiAgent")
        if not self.is_paper:
            logger.info(f"  Equity Floor: ${self.equity_floor:,.2f} (altina duserse DUR)")
        logger.info("=" * 60)

        if not self.is_paper:
            logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            logger.warning("!!! GERCEK PARA MODU AKTIF !!!")
            logger.warning(f"!!! Bakiye: ${self.equity:,.2f} !!!")
            logger.warning(f"!!! Max pozisyon: ${self.max_pos_usd} !!!")
            logger.warning(f"!!! Equity floor: ${self.equity_floor:,.2f} !!!")
            logger.warning("!!! 15 saniye icinde basliyor... !!!")
            logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            time.sleep(15)

    # ============================================================
    # VERİ ÇEKME
    # ============================================================

    def get_crypto_bars(self, symbol: str, days: int = 30, timeframe=None) -> pd.DataFrame:
        """Alpaca'dan kripto bar verisi çeker."""
        try:
            tf = timeframe if timeframe else TimeFrame.Hour
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=datetime.now() - timedelta(days=days),
            )
            bars = self.crypto_data.get_crypto_bars(request)
            df = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.droplevel("symbol")
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            logger.error(f"{symbol} veri cekilemedi: {e}")
            return pd.DataFrame()

    # ============================================================
    # TEKNİK ANALİZ (analyzer modülüne delege)
    # ============================================================

    def analyze(self, df: pd.DataFrame) -> Dict:
        """Teknik analiz — analyzer modülüne delege eder."""
        return self.analyzer.analyze(df, CRYPTO_CONFIG)

    def analyze_with_news(self, df, symbol: str) -> Dict:
        """Hibrit analiz — analyzer modülüne delege eder."""
        return self.analyzer.analyze_with_news(df, symbol, CRYPTO_CONFIG)

    # ============================================================
    # EMİR YÖNETIMI (executor modülüne delege)
    # ============================================================

    def execute_buy(self, symbol: str, analysis: Dict) -> bool:
        """Alış emri — executor modülüne delege eder."""
        return self.executor.execute_buy(symbol, analysis, CRYPTO_CONFIG)

    def execute_sell(self, symbol: str, reason: str) -> bool:
        """Satış emri — executor modülüne delege eder."""
        return self.executor.execute_sell(symbol, reason)

    # ============================================================
    # POZİSYON YÖNETİMİ (position_manager modülüne delege)
    # ============================================================

    def manage_positions(self):
        """Pozisyon yönetimi — position_manager modülüne delege eder."""
        self.position_mgr.manage_positions(CRYPTO_CONFIG)

    # ============================================================
    # ANA DÖNGÜ
    # ============================================================

    def run(self):
        """Ana trading döngüsü — 7/24 çalışır."""
        logger.info(f"\nBot calisma moduna gecti... (PID: {os.getpid()})\n")

        while self.running:
            try:
                self.cycle_count += 1

                # Kill switch kontrolleri
                if self.consecutive_errors >= CRYPTO_CONFIG["max_consecutive_errors"]:
                    logger.error(
                        f"KILL SWITCH: {self.consecutive_errors} ardisik hata! "
                        f"Bot durduruluyor."
                    )
                    self._emergency_close()
                    self.running = False
                    break

                # Günlük kayıp kontrolü
                try:
                    account = self.client.get_account()
                    self.equity = float(account.equity)
                    self.cash = float(account.cash)
                except Exception as api_err:
                    logger.warning(f"API baglanti hatasi (yeniden deneniyor): {api_err}")
                    self.consecutive_errors += 1
                    time.sleep(10)
                    continue

                daily_change = (self.equity - self.starting_equity) / self.starting_equity

                if daily_change <= -CRYPTO_CONFIG["max_daily_loss_pct"]:
                    logger.error(
                        f"KILL SWITCH: Gunluk kayip {daily_change:.1%}! "
                        f"Bot durduruluyor."
                    )
                    self._emergency_close()
                    self.running = False
                    break

                # Açık pozisyonları yönet
                self.manage_positions()

                # Acik pozisyon sayisini kontrol et (micro pozisyonlari sayma!)
                open_positions = self.client.get_all_positions()
                real_positions = [p for p in open_positions 
                                  if float(p.qty) * float(p.current_price) >= 5.0]
                open_count = len(real_positions)

                # === F&G BAZLI DİNAMİK GÜVEN EŞİĞİ ===
                max_positions = CRYPTO_CONFIG["max_open_positions"]
                min_confidence = 50  # Baz esik: normal modda %50
                fg_value = self._last_fg_value

                if fg_value < 20:  # Extreme Fear → çok temkinli
                    min_confidence = 70
                    max_positions = 1
                    if self.cycle_count % 20 == 1:
                        logger.warning(
                            f"  EXTREME FEAR MODU: F&G={fg_value} → "
                            f"Min %{min_confidence} guven, max {max_positions} poz"
                        )
                elif fg_value < 40:  # Fear → temkinli
                    min_confidence = 55
                    max_positions = 1
                    if self.cycle_count % 20 == 1:
                        logger.warning(
                            f"  FEAR MODU: F&G={fg_value} → "
                            f"Min %{min_confidence} guven, max {max_positions} poz"
                        )
                elif self.equity < CRYPTO_CONFIG.get("micro_account_threshold", 600):
                    max_positions = 1
                    min_confidence = 55
                    if self.cycle_count == 1:
                        logger.warning(
                            f"  MICRO HESAP MODU: ${self.equity:.0f} < "
                            f"${CRYPTO_CONFIG['micro_account_threshold']} → "
                            f"Max {max_positions} pozisyon, min %{min_confidence} guven"
                        )

                # === GÜNLÜK MİNİMUM İŞLEM MEKANİZMASI ===
                today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                if self._last_buy_date != today_str:
                    self._daily_buys_count = 0
                    self._last_buy_date = today_str

                utc_hour_now = datetime.now(timezone.utc).hour
                min_daily = CRYPTO_CONFIG.get('min_daily_trades', 1)
                relax_hour = CRYPTO_CONFIG.get('min_daily_trade_relax_hour_utc', 12)
                relax_conf = CRYPTO_CONFIG.get('min_daily_trade_confidence', 50)

                if (self._daily_buys_count < min_daily
                    and utc_hour_now >= relax_hour
                    and min_confidence > relax_conf):
                    old_conf = min_confidence
                    min_confidence = relax_conf
                    if self.cycle_count % 30 == 1:
                        logger.info(
                            f"  GÜNLÜK İŞLEM: Bugün {self._daily_buys_count} alım, "
                            f"eşik {old_conf}%→{min_confidence}% (en az {min_daily} işlem hedefi)"
                        )

                # Her coin'i analiz et
                for symbol in CRYPTO_CONFIG["symbols"]:
                    # Dinamik trade araligi: once minimum 5dk bekle
                    last_time = self.last_trade_time.get(symbol)
                    if last_time:
                        elapsed = (datetime.now() - last_time).total_seconds() / 60
                        if elapsed < CRYPTO_CONFIG.get("min_interval_high_conf", 5):
                            continue  # En az 5dk bekle (her durumda)

                    # Veri çek & analiz et (TEKNİK + HABER)
                    df = self.get_crypto_bars(symbol, days=14)
                    if df.empty or len(df) < 30:
                        continue

                    analysis = self.analyze_with_news(df, symbol)

                    # Dinamik trade araligi: guven skoru yuksekse daha az bekle
                    if last_time and analysis["signal"] == "BUY":
                        elapsed = (datetime.now() - last_time).total_seconds() / 60
                        if analysis["confidence"] >= 65:
                            req_wait = CRYPTO_CONFIG.get("min_interval_high_conf", 5)
                        elif analysis["confidence"] >= 55:
                            req_wait = CRYPTO_CONFIG.get("min_interval_med_conf", 10)
                        else:
                            req_wait = CRYPTO_CONFIG.get("min_interval_low_conf", 20)
                        if elapsed < req_wait:
                            continue

                    # === GATE FİLTRELERİ (trade_gates modülüne delege) ===
                    gates_passed, block_reason = self.gates.check_all_gates(
                        symbol, analysis, CRYPTO_CONFIG
                    )

                    if (
                        analysis["signal"] == "BUY"
                        and analysis["confidence"] >= min_confidence
                        and open_count < max_positions
                        and symbol not in [p.symbol.replace("USD", "/USD") for p in real_positions]
                        and gates_passed
                    ):
                        news_info = f" | Haber: {analysis.get('news_score', 0)}"
                        logger.info(
                            f"\n  SINYAL: {symbol} | BUY | "
                            f"Guven: {analysis['confidence']}% | "
                            f"RSI: {analysis['rsi']:.0f} | "
                            f"Fiyat: ${analysis['price']:,.2f}{news_info}"
                        )
                        if self.execute_buy(symbol, analysis):
                            open_count += 1

                # Hata sayacını sıfırla (başarılı döngü)
                self.consecutive_errors = 0

                # Durum raporu — her 5 döngüde bir yaz (log şişmesini önle)
                if self.cycle_count % 5 == 0 or self.trades_today:
                    self._print_status()

                # HEARTBEAT: her 30 döngüde (~5dk) bot'un yaşadığını logla
                if self.cycle_count % 30 == 0:
                    last_trade_str = "yok"
                    if self.last_trade_time:
                        last_sym = max(self.last_trade_time, key=self.last_trade_time.get)
                        last_t = self.last_trade_time[last_sym]
                        ago = (datetime.now() - last_t).total_seconds() / 3600
                        last_trade_str = f"{last_sym} {ago:.1f}h once"
                    logger.info(
                        f"  HEARTBEAT | Cycle:{self.cycle_count} | "
                        f"Equity:${self.equity:,.2f} | "
                        f"Pos:{len(self.positions)} | "
                        f"Trades:{len(self.trades_today)} | "
                        f"LastTrade:{last_trade_str} | "
                        f"Errors:{self.consecutive_errors}"
                    )

                # Bekleme
                interval = CRYPTO_CONFIG["scan_interval_seconds"]
                if self.cycle_count % 5 == 0:
                    logger.info(f"  Bekleniyor ({interval}s)...\n")
                time.sleep(interval)

            except KeyboardInterrupt:
                logger.info("\nBot kullanici tarafindan durduruldu")
                self.running = False
            except Exception as e:
                logger.error(f"Hata: {e}")
                self.consecutive_errors += 1
                time.sleep(30)

        self._shutdown()

    def _print_status(self):
        """Mevcut durumu logla."""
        change = self.equity - self.starting_equity
        change_pct = (change / self.starting_equity) * 100
        marker = "+" if change >= 0 else ""
        logger.info(
            f"  Durum: ${self.equity:,.2f} ({marker}${change:,.2f} / {marker}{change_pct:.2f}%) | "
            f"Islem: {len(self.trades_today)} | "
            f"Saat: {datetime.now().strftime('%H:%M')}"
        )

    def _emergency_close(self):
        """Acil durum: tüm pozisyonları kapat."""
        logger.error("ACIL KAPANMA: Tum pozisyonlar kapatiliyor!")
        try:
            self.client.close_all_positions(cancel_orders=True)
            logger.error("Tum pozisyonlar kapatildi.")
        except Exception as e:
            logger.error(f"Acil kapanma hatasi: {e}")

    def _shutdown(self):
        """Bot kapanış prosedürü."""
        logger.info("\nBot kapatiliyor...")
        change = self.equity - self.starting_equity
        logger.info(f"Gunluk P&L: ${change:+,.2f}")
        logger.info(f"Toplam islem: {len(self.trades_today)}")

        # Trade geçmişini kaydet
        if self.trades_today:
            history_file = "crypto_trade_history.json"
            try:
                existing = []
                if os.path.exists(history_file):
                    with open(history_file, "r") as f:
                        existing = json.load(f)
                existing.extend(self.trades_today)
                with open(history_file, "w") as f:
                    json.dump(existing, f, indent=2)
                logger.info(f"Trade gecmisi kaydedildi: {history_file}")
            except Exception as e:
                logger.error(f"Kayit hatasi: {e}")

        logger.info("Bot basariyla kapatildi.\n")


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kripto Trading Bot")
    parser.add_argument("--live", action="store_true",
                       help="Gercek para modu (DIKKAT!)")
    parser.add_argument("--status", action="store_true",
                       help="Hesap durumunu goster")

    args = parser.parse_args()

    if args.status:
        load_dotenv()
        is_paper = os.getenv("TRADING_MODE", "paper").lower() != "live"
        client = TradingClient(
            os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=is_paper
        )
        account = client.get_account()
        positions = client.get_all_positions()

        print("\n" + "=" * 40)
        print(f"  Hesap Durumu")
        print("=" * 40)
        print(f"  Bakiye:      ${float(account.equity):,.2f}")
        print(f"  Nakit:       ${float(account.cash):,.2f}")
        print(f"  Alim Gucu:   ${float(account.buying_power):,.2f}")
        print(f"  Pozisyon:    {len(positions)} adet")
        for p in positions:
            pnl = float(p.unrealized_pl)
            m = "+" if pnl >= 0 else ""
            print(f"    {p.symbol}: {p.qty} @ ${float(p.avg_entry_price):,.2f} | P&L: {m}${pnl:,.2f}")
        print("=" * 40 + "\n")
    else:
        bot = CryptoBot(live=args.live)
        bot.run()
