"""
Stock Trading Bot — Hisse Senedi Al-Sat Botu
Swing trading + sınırlı day trade stratejisi.

Özellikler:
  - NYSE/NASDAQ piyasa saatleri kontrolü
  - PDT kuralı koruması (max 2 day trade/hafta)
  - 5 uzman ajan sistemi (Tech, Fund, Sent, Social, Risk)
  - Dinamik sabah taraması
  - Earnings takvimi koruması
  - VIX + Petrol + Jeopolitik risk takibi
  - Alpaca Trading API (hisse senedi, komisyon $0)
  - KillSwitch acil durum koruması
  - Wash Sale kuralı takibi
  - Sektör korelasyon koruması
  - Pozisyon senkronizasyonu (restart-safe)
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

# Alpaca
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Teknik Analiz
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands, AverageTrueRange

# Config
from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, TRADING_MODE, BOT_MODE,
    get_base_url, STOCK_CONFIG, SHORT_CONFIG, STOCK_IDS, STOCK_SEARCH_TERMS,
    SECTOR_MAP, MARKET_REGIME_CONFIG,
)

# Core modüller
from core.market_hours import MarketHours
from core.pdt_tracker import PDTTracker
from core.stock_screener import StockScreener
from core.earnings_calendar import EarningsCalendar
from core.agent_coordinator import AgentCoordinator
from core.analyzer import TechnicalAnalyzer
from core.executor import OrderExecutor
from core.short_executor import ShortExecutor
from core.position_manager import PositionManager
from core.trade_gates import TradeGates
from core.news_analyzer import StockNewsAnalyzer
from core.social_sentiment import SocialSentimentAnalyzer
from core.fundamental_analyzer import FundamentalAnalyzer
from core.macro_data import MacroDataAnalyzer
from core.kill_switch import KillSwitch
from core.compliance import WashSaleTracker
from core.notifier import TelegramNotifier
from core.performance_tracker import PerformanceTracker
from core.sector_rotation import SectorRotator
from core.position_sizer import PositionSizer
from core.volume_analyzer import VolumeAnalyzer
from core.agent_performance import AgentPerformanceTracker
from core.gap_scanner import GapScanner
from core.relative_strength import RelativeStrength
from core.market_regime import MarketRegimeDetector
from core.signal_queue import SignalQueue

# FinBERT opsiyonel
try:
    from core.finbert_analyzer import FinBERTAnalyzer
    FINBERT_AVAILABLE = True
except ImportError:
    FINBERT_AVAILABLE = False

from utils.logger import logger


# ============================================================
# FLUSH STREAM HANDLER (Docker/Coolify log çıktısı)
# ============================================================
class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

# Root logger'a flush handler ekle
_root = logging.getLogger()
if not any(isinstance(h, FlushStreamHandler) for h in _root.handlers):
    fh = FlushStreamHandler(sys.stdout)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    ))
    _root.addHandler(fh)
    _root.setLevel(logging.INFO)


class StockBot:
    """
    Hisse Senedi Trading Bot — Swing + Sınırlı Day Trade.
    
    Günlük akış:
      1. Pre-market (09:00 ET): Sabah taraması + haber analizi
      2. Market open (09:30): İlk 30dk volatil, gözetle
      3. Safe zone (10:00-15:45): Analiz + alım
      4. Close (15:45-16:00): Trailing stop kontrol
      5. After-hours: Sadece olağanüstü fırsatlarda
    """

    POSITIONS_FILE = "bot_positions.json"

    def __init__(self):
        config = STOCK_CONFIG

        # Alpaca istemcileri
        is_paper = TRADING_MODE != "live"
        self.is_paper = is_paper
        self.client = TradingClient(
            ALPACA_API_KEY, ALPACA_SECRET_KEY,
            paper=is_paper,
        )
        self.data_client = StockHistoricalDataClient(
            api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY,
        )

        # Hesap bilgileri
        account = self.client.get_account()
        equity = float(account.equity)
        self.initial_equity = equity
        self.equity = equity

        # Pozisyon limitleri
        self.max_pos_usd = config.get("live_max_position_usd", 200)
        if is_paper:
            self.max_pos_usd = config.get("max_position_usd", 200)

        self.equity_floor = equity * config.get("equity_floor_pct", 0.85)

        # Durum değişkenleri
        self.positions = {}
        self.short_positions = {}  # SHORT pozisyonlar
        self.last_trade_time = {}
        self.trades_today = []
        self.sell_cooldown = {}
        self.consecutive_errors = 0
        self._consecutive_losses = 0
        self._symbol_consecutive_losses = {}  # Hisse bazli ardisik zarar
        self._daily_buys_count = 0
        self._last_status_time = datetime.min
        self._heartbeat_counter = 0
        self._morning_scan_done = False
        self._morning_scan_date = None
        self._market_regime = "UNKNOWN"   # BULL / BEAR / UNKNOWN
        self._regime_check_time = datetime.min
        self._daily_reset_date = None

        # Core modüller
        self.market_hours = MarketHours()
        self.pdt_tracker = PDTTracker(equity=equity)
        self.screener = StockScreener(
            api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY
        )
        self.earnings_calendar = EarningsCalendar()
        self.coordinator = AgentCoordinator()
        self.executor = OrderExecutor(self)
        self.short_executor = ShortExecutor(self)  # SHORT executor
        self.position_manager = PositionManager(self)
        self.trade_gates = TradeGates(self)
        self.news_analyzer = StockNewsAnalyzer()
        self.social_analyzer = SocialSentimentAnalyzer()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.macro_analyzer = MacroDataAnalyzer()

        # KillSwitch — acil durum koruması
        self.kill_switch = KillSwitch(
            max_consecutive_errors=config.get("max_consecutive_errors", 5),
            max_daily_loss_pct=config.get("max_daily_loss_pct", 0.03),
        )
        self.kill_switch.set_callback(self._emergency_close_all)

        # Wash Sale takibi
        self.wash_sale_tracker = WashSaleTracker()

        # Telegram bildirimleri
        self.notifier = TelegramNotifier()

        # Performans takibi
        self.performance = PerformanceTracker()

        # Sektör rotasyonu (VIX bazlı)
        self.sector_rotator = SectorRotator()

        # FinBERT — news_analyzer'ın instance'ını paylaş (çift yüklemeyi önle, ~800MB RAM tasarrufu)
        self.finbert = getattr(self.news_analyzer, 'finbert', None)

        # Teknik analizci
        self.analyzer = TechnicalAnalyzer(self)

        # Iyilestirme modullleri (v2.0)
        self.position_sizer = PositionSizer(performance_tracker=self.performance)
        self.volume_analyzer = VolumeAnalyzer()
        self.agent_perf = AgentPerformanceTracker()

        # Iyilestirme modulleri (v3.0)
        self.gap_scanner = GapScanner()
        self.relative_strength = RelativeStrength()
        self.regime_detector = MarketRegimeDetector()
        self.signal_queue = SignalQueue()
        self._spy_df_cache = None
        self._spy_cache_time = datetime.min
        self._gap_scan_done_today = False
        self._gap_scan_date = date.min

        # === POZİSYON SENKRONİZASYONU (restart-safe) ===
        self._sync_positions_from_alpaca()
        self._load_position_metadata()

        mode_str = "PAPER" if is_paper else "🔴 LIVE"
        bot_mode_str = {"long_only": "📈 LONG ONLY", "short_only": "📉 SHORT ONLY", "both": "📊 LONG + SHORT"}.get(BOT_MODE, BOT_MODE)
        logger.info("=" * 60)
        logger.info(f"  STOCK TRADING BOT BASLATILDI")
        logger.info(f"  Mod: {mode_str} | Bot: {bot_mode_str}")
        logger.info(f"  Equity: ${equity:,.2f}")
        logger.info(f"  Max pozisyon: ${self.max_pos_usd} | Floor: ${self.equity_floor:,.2f}")
        logger.info(f"  Hisse havuzu: {len(config['symbols'])} hisse")
        logger.info(f"  Acik pozisyon: {len(self.positions)} long | {len(self.short_positions)} short")
        logger.info(f"  PDT: {'EXEMPT' if equity >= 25000 else f'ACTIVE (max 2 DT/hafta)'}")
        logger.info(f"  KillSwitch: AKTIF | WashSale: AKTIF")
        logger.info("=" * 60)

    # ============================================================
    # ANA DÖNGÜ
    # ============================================================

    def run(self):
        """Ana trading döngüsü."""
        config = STOCK_CONFIG
        logger.info("Bot ana döngüye giriyor...")

        while True:
            try:
                # KillSwitch kontrolü
                if self.kill_switch.is_active:
                    logger.error(f"🚨 KILL SWITCH AKTİF: {self.kill_switch.kill_reason}")
                    logger.error("Bot durduruldu. kill_switch.json silinerek restart yapılabilir.")
                    time.sleep(60)
                    continue

                # Günlük reset
                self._daily_reset()

                # Heartbeat
                self._heartbeat_counter += 1
                if self._heartbeat_counter % config.get("heartbeat_interval", 30) == 0:
                    self._log_heartbeat()

                # Market durumu
                market_status = self.market_hours.get_market_status()

                # Piyasa kapalı → bekle
                if market_status["status"] == "CLOSED":
                    wait_secs = min(self.market_hours.seconds_until_open(), 300)
                    if self._heartbeat_counter % 60 == 0:
                        logger.info(f"  Piyasa kapalı ({market_status['reason']}) — {wait_secs//60}dk bekleniyor")
                    time.sleep(min(wait_secs, 60))
                    continue

                # Pre-market → sabah taraması
                if market_status["status"] == "PRE_MARKET":
                    self._do_morning_scan()
                    time.sleep(30)
                    continue

                # After-hours → sadece pozisyon yönetimi
                if market_status["status"] == "AFTER_HOURS":
                    self._manage_positions(config)
                    time.sleep(30)
                    continue

                # === PİYASA AÇIK ===

                # Günlük kayıp kontrolü (KillSwitch)
                try:
                    account = self.client.get_account()
                    self.equity = float(account.equity)
                    if self.kill_switch.check_daily_loss(self.equity, self.initial_equity):
                        continue  # Kill tetiklendi, döngü başına dön
                    self.kill_switch.reset_error_count()
                except Exception as e:
                    if self.kill_switch.check_api_error(e):
                        continue

                # Piyasa rejim tespiti (her 30 dk) — v3.0 gelismis rejim
                self._update_market_regime()

                # Pre-Market Gap Scanner (gunde 1 kez, piyasa acilmadan)
                if not self._gap_scan_done_today or self._gap_scan_date != date.today():
                    has_open = len(self.positions) > 0 or len(self.short_positions) > 0
                    if has_open:
                        try:
                            gap_alerts = self.gap_scanner.scan_overnight_gaps(self)
                            if gap_alerts:
                                self.gap_scanner.execute_gap_actions(self, gap_alerts)
                        except Exception as e:
                            logger.debug(f"  Gap scan hatasi: {e}")
                    self._gap_scan_done_today = True
                    self._gap_scan_date = date.today()

                # Pozisyon yonetimi (her dongude)
                if BOT_MODE in ("long_only", "both"):
                    self._manage_positions(config)

                # Short pozisyon yonetimi (her dongude)
                if BOT_MODE in ("short_only", "both") and SHORT_CONFIG.get("short_enabled", False):
                    try:
                        self.position_manager.manage_short_positions(config, SHORT_CONFIG)
                    except Exception as e:
                        logger.debug(f"  Short pozisyon yonetim hatasi: {e}")

                # Signal Queue kontrolu — bekleyen sinyalleri kontrol et
                try:
                    ready_signals = self.signal_queue.check_entries(self)
                    for sig in ready_signals:
                        sym = sig["symbol"]
                        if sig["signal"] == "BUY" and BOT_MODE in ("long_only", "both"):
                            self.executor.execute_buy(sym, sig["analysis"], config)
                        elif sig["signal"] == "SHORT" and BOT_MODE in ("short_only", "both"):
                            self.short_executor.execute_short(sym, sig["analysis"], config, SHORT_CONFIG)
                except Exception as e:
                    logger.debug(f"  Signal queue hatasi: {e}")

                # Guvenli bolge kontrolu
                if not market_status["is_safe_zone"]:
                    time.sleep(10)
                    continue

                # Mevcut pozisyon sayısı
                open_count = len(self.positions)
                max_positions = config.get("max_open_positions", 3)

                if open_count >= max_positions:
                    time.sleep(config.get("scan_interval_seconds", 30))
                    continue

                # Sabah taraması yapılmadıysa yap
                if not self._morning_scan_done or self._morning_scan_date != date.today():
                    self._do_morning_scan()

                # 🌍 Jeopolitik risk taraması (her döngüde, 2dk cache)
                try:
                    geo_scan = self.news_analyzer.scan_geopolitical_breaking()
                    geo_level = geo_scan.get("geo_risk_level", "NORMAL")
                    geo_score = geo_scan.get("geo_risk_score", 0)

                    if geo_level == "CRITICAL":
                        logger.warning(
                            f"  🚨 JEOPOLİTİK KRİTİK! Skor: {geo_score} | "
                            f"Yeni alım ENGELLENDİ. Mevcut pozisyonlar korunuyor."
                        )
                        time.sleep(config.get("scan_interval_seconds", 30))
                        continue  # Yeni alım yapma, sadece pozisyon yönet
                    elif geo_level == "HIGH":
                        max_positions = min(max_positions, 1)
                        logger.info(f"  ⚠️ Jeopolitik HIGH — Max pozisyon 1'e düşürüldü")
                except Exception as e:
                    logger.debug(f"  Jeopolitik tarama hatası: {e}")

                # Hisse analizi
                symbols = self._get_symbols_to_analyze()
                for symbol in symbols:
                    if len(self.positions) >= max_positions:
                        break
                    if symbol in self.positions:
                        continue
                    # Sektör korelasyon koruması
                    if self._sector_limit_reached(symbol, config):
                        continue
                    # Wash Sale kontrolü
                    is_wash, wash_reason = self.wash_sale_tracker.check_wash_sale(symbol)
                    if is_wash:
                        logger.info(f"  {symbol} WASH SALE: {wash_reason}")
                        continue
                    self._analyze_and_trade(symbol, config)

                # Durum raporu
                self._periodic_status_report(config)

                # Adaptif tarama araligi:
                # Acik pozisyon varken 15 saniye (hizli tepki)
                # Pozisyon yokken 30 saniye (API tasarrufu)
                has_positions = len(self.positions) > 0 or len(self.short_positions) > 0
                interval = 15 if has_positions else config.get("scan_interval_seconds", 30)
                time.sleep(interval)

            except KeyboardInterrupt:
                logger.info("Bot durduruldu (Ctrl+C)")
                self._save_position_metadata()
                break
            except Exception as e:
                self.consecutive_errors += 1
                logger.error(f"Ana döngü hatası: {e}")
                if self.kill_switch.check_api_error(e):
                    continue
                if self.consecutive_errors >= config.get("max_consecutive_errors", 5):
                    logger.critical(f"  {self.consecutive_errors} ardışık hata! 5 dakika bekleniyor.")
                    time.sleep(300)
                    self.consecutive_errors = 0
                else:
                    time.sleep(config.get("error_retry_sleep", 30))

    # ============================================================
    # SABAH TARAMASI
    # ============================================================

    def _do_morning_scan(self):
        """Pre-market sabah taraması."""
        if self._morning_scan_done and self._morning_scan_date == date.today():
            return

        logger.info("=" * 50)
        logger.info("  🌅 SABAH TARAMASI")
        logger.info("=" * 50)

        # Makro analiz (VIX, petrol, faiz)
        try:
            macro = self.macro_analyzer.get_macro_score()
            logger.info(f"  Makro skor: {macro['macro_score']} ({macro['macro_signal']})")
            if "oil" in macro:
                logger.info(f"  Petrol: {macro['oil'].get('description', 'N/A')}")
            if "vix" in macro:
                vix_data = macro["vix"]
                vix_value = vix_data.get("value", 20)
                logger.info(f"  VIX: {vix_data.get('description', 'N/A')} ({vix_value:.1f})")
                # Sektör rotasyonu güncelle
                self.sector_rotator.update_vix(vix_value)
                sr_status = self.sector_rotator.get_status()
                logger.info(
                    f"  🔄 Sektör Rejim: {sr_status['regime'].upper()} | "
                    f"Max Poz: {sr_status['max_positions']} | "
                    f"Favori: {', '.join(sr_status['preferred_sectors']) or 'YOK'} | "
                    f"Kaçın: {', '.join(sr_status['avoid_sectors']) or 'YOK'}"
                )
        except Exception as e:
            logger.debug(f"  Makro analiz hatası: {e}")

        # Piyasa duyarlılığı
        try:
            sentiment = self.news_analyzer.get_market_sentiment()
            logger.info(
                f"  Piyasa: SPY={sentiment.get('spy_sentiment', 'N/A')}, "
                f"QQQ={sentiment.get('qqq_sentiment', 'N/A')}, "
                f"Jeopolitik={sentiment.get('geopolitical_risk', 'N/A')}"
            )
        except Exception as e:
            logger.debug(f"  Piyasa sentiment hatası: {e}")

        # Hisse taraması
        try:
            opportunities = self.screener.morning_scan()
            if opportunities:
                logger.info(f"  En iyi fırsatlar:")
                for opp in opportunities[:5]:
                    logger.info(f"    {opp['symbol']}: Skor={opp['score']:.0f}")
        except Exception as e:
            logger.debug(f"  Tarama hatası: {e}")

        self._morning_scan_done = True
        self._morning_scan_date = date.today()

    # ============================================================
    # PİYASA REJİM TESPİTİ
    # ============================================================

    def _update_market_regime(self):
        """SPY bazli piyasa rejim tespiti — v3.0 gelismis (ADX+BB+EMA)."""
        if not MARKET_REGIME_CONFIG.get("enabled", True):
            return

        # 30 dakikada bir kontrol et
        now = datetime.now()
        if (now - self._regime_check_time).total_seconds() < 1800:
            return

        self._regime_check_time = now
        benchmark = MARKET_REGIME_CONFIG.get("benchmark_symbol", "SPY")

        try:
            df = self.get_stock_bars(benchmark, days=250)
            if df.empty or len(df) < 50:
                return

            # SPY verisini cache'le (relative strength icin)
            self._spy_df_cache = df
            self._spy_cache_time = now

            close = df["close"]
            price = float(close.iloc[-1])

            # Eski EMA200 rejimi (backward compat)
            ema_period = MARKET_REGIME_CONFIG.get("ema_period", 200)
            ema_period = min(ema_period, len(close) - 1)
            ema200 = EMAIndicator(close, window=ema_period).ema_indicator().iloc[-1]

            old_regime = self._market_regime

            if price < ema200:
                self._market_regime = "BEAR"
            else:
                self._market_regime = "BULL"

            # v3.0 Gelismis 4-rejim algilama (ADX + BB + EMA)
            try:
                vix = getattr(self, '_last_vix', 0)
                enhanced = self.regime_detector.detect_regime(df, vix=vix)
                self._enhanced_regime = enhanced
                self._regime_trading_mode = enhanced.get("trading_mode", "NORMAL")

                if old_regime != self._market_regime or self.regime_detector.current_regime != enhanced["regime"]:
                    logger.info(
                        f"  REJIM: {self._market_regime} | "
                        f"Detay: {enhanced['regime']} ({enhanced['trading_mode']}) "
                        f"| {enhanced['description']}"
                    )
            except Exception as e:
                logger.debug(f"  Gelismis rejim hatasi: {e}")

        except Exception as e:
            logger.debug(f"  Rejim tespiti hatasi: {e}")

    # ============================================================
    # HİSSE ANALİZİ VE İŞLEM
    # ============================================================

    def _analyze_and_trade(self, symbol: str, config: Dict):
        """Tek bir hisseyi analiz et ve gerekirse islem yap (LONG veya SHORT).
        BOT_MODE: 'long_only' | 'short_only' | 'both'
        """
        try:
            # Teknik analiz
            analysis = self._get_technical_analysis(symbol, config)
            if analysis is None:
                return

            # Multi-agent karar
            decision = self._get_agent_decision(symbol, analysis, config)

            # SHORT sinyal mapping:
            # 1. analyzer.py zaten SHORT üretir (sell_score >= 45)
            # 2. Coordinator SELL döndürür ama SELL != SHORT:
            #    - Eğer elimizde long pozisyon varsa → gerçek SELL (kapat)
            #    - Eğer pozisyonumuz yoksa → SHORT (yeni kısa pozisyon aç)
            if decision["signal"] == "SELL" and symbol not in self.positions:
                decision["signal"] = "SHORT"
            # Teknik analizden gelen native SHORT sinyalini de coordinator'dan geçir
            if analysis.get("signal") == "SHORT" and decision["signal"] == "HOLD":
                decision["signal"] = "SHORT"
                decision["confidence"] = max(decision.get("confidence", 0), analysis.get("confidence", 0))

            # Ters ETF & Endeks filtresi
            _inverse_etfs = MARKET_REGIME_CONFIG.get("inverse_etf_symbols", [])
            _index_symbols = MARKET_REGIME_CONFIG.get("index_symbols", [])
            _is_inverse_etf = symbol in _inverse_etfs
            _is_index = symbol in _index_symbols

            # Endeksler asla trade edilmez (sadece rejim tespiti icin)
            if _is_index:
                return

            # Rejim bazli guven ayarlamasi
            effective_buy_conf = config.get("min_confidence_score", 50)
            effective_short_conf = SHORT_CONFIG.get("short_min_confidence", 45)

            if self._market_regime == "BEAR":
                # Bear modda: BUY icin daha yuksek esik, SHORT icin daha dusuk
                effective_buy_conf += MARKET_REGIME_CONFIG.get("bear_buy_conf_increase", 10)
                effective_short_conf -= MARKET_REGIME_CONFIG.get("bear_short_conf_reduction", 10)

            # Ters ETF'ler sadece BEAR modda BUY (long) olarak alinir
            if _is_inverse_etf:
                if self._market_regime != "BEAR":
                    return  # Bull/Unknown modda ters ETF alma
                # Ters ETF icin short sinyal ALMA (zaten ters)
                if decision["signal"] == "SHORT":
                    return

            # === LONG (BUY) — BOT_MODE: 'long_only' veya 'both' ===
            if (decision["signal"] == "BUY"
                    and BOT_MODE in ("long_only", "both")
                    and decision["confidence"] >= effective_buy_conf):
                # Sektör rotasyonu kontrolü (VIX bazlı)
                if not self.sector_rotator.should_buy(symbol):
                    logger.debug(f"  {symbol} SEKTÖR ROTASYON BLOK: {self.sector_rotator.current_regime} rejiminde kaçınılıyor")
                    return

                # Gate kontrolü
                passed, block_reason = self.trade_gates.check_all_gates(symbol, analysis, config)
                if passed:
                    analysis["confidence"] = decision["confidence"]
                    analysis["reasons"] = [decision["reasoning"]]
                    analysis["sector_weight"] = self.sector_rotator.get_weight_multiplier(symbol)
                    if _is_inverse_etf:
                        analysis["reasons"].append("🐻 BEAR_MODE_INVERSE_ETF")
                    self.executor.execute_buy(symbol, analysis, config)
                else:
                    logger.debug(f"  {symbol} GATE BLOK: {block_reason}")

            # === SHORT — BOT_MODE: 'short_only' veya 'both' ===
            elif (decision["signal"] == "SHORT"
                  and BOT_MODE in ("short_only", "both")
                  and SHORT_CONFIG.get("short_enabled", False)
                  and decision["confidence"] >= effective_short_conf):

                # Zaten short pozisyonumuz var mi?
                if symbol in self.short_positions:
                    return

                # Zaten long pozisyonumuz var mi? (ayni anda long+short yapma)
                if symbol in self.positions:
                    return

                logger.info(f"  🔻 {symbol} SHORT sinyal: Guven={decision['confidence']:.0f} | Rejim={self._market_regime} | {decision.get('reasoning', '')}")
                analysis["confidence"] = decision["confidence"]
                analysis["reasons"] = [decision.get("reasoning", "SHORT")]
                if self._market_regime == "BEAR":
                    analysis["reasons"].append("🐻 BEAR_MODE")
                self.short_executor.execute_short(symbol, analysis, config, SHORT_CONFIG)

        except Exception as e:
            logger.debug(f"  {symbol} analiz hatası: {e}")

    def _get_technical_analysis(self, symbol: str, config: Dict) -> Optional[Dict]:
        """Hisse için gelişmiş teknik analiz + volume analizi.

        İçerik: RSI, EMA, MACD, BB, ATR, Ichimoku, ADX, OBV, Fibonacci,
        RSI Divergence, VWAP, S/R + Unusual Volume + Smart Money algılama.
        SHORT sinyali de üretir (sell_score >= 45).
        """
        try:
            df = self.get_stock_bars(symbol, days=30)
            if df.empty or len(df) < 30:
                return None

            # Teknik analiz
            result = self.analyzer.analyze(df, config)

            # Volume analizi (Smart Money algılama)
            vol_data = self.volume_analyzer.analyze_volume(df)
            result["volume_analysis"] = vol_data

            # Volume sinyali confidence'a katki saglar
            if vol_data.get("confidence_boost", 0) > 0:
                boost = vol_data["confidence_boost"]
                vol_signal = vol_data.get("signal", "NORMAL")

                if vol_signal == "ACCUMULATION" and result["signal"] in ("BUY", "HOLD"):
                    result["confidence"] = min(result["confidence"] + boost, 100)
                    result["reasons"].append(f"SmartMoney:+{boost}({vol_signal})")
                elif vol_signal == "DISTRIBUTION" and result["signal"] in ("SHORT", "SELL", "HOLD"):
                    result["confidence"] = min(result.get("sell_score", 0) + boost, 100)
                    result["reasons"].append(f"SmartMoney:+{boost}({vol_signal})")

            # Relative Strength (SPY'a gore guc siralamasi)
            try:
                spy_df = self._spy_df_cache
                if spy_df is not None and not spy_df.empty:
                    rs_data = self.relative_strength.calculate_rs(df, spy_df)
                    result["relative_strength"] = rs_data

                    # RS bazli confidence ayarlama
                    side = "LONG" if result["signal"] in ("BUY",) else "SHORT"
                    rs_boost = self.relative_strength.get_rs_signal_boost(rs_data, side)
                    if rs_boost != 0:
                        result["confidence"] = max(0, min(result["confidence"] + rs_boost, 100))
                        result["reasons"].append(
                            f"RS:{rs_data['rank_label']}({rs_data['composite_rs']:+.1%})"
                        )
            except Exception:
                pass

            return result
        except Exception as e:
            logger.debug(f"  {symbol} teknik analiz hatası: {e}")
            return None

    def _get_agent_decision(self, symbol: str, analysis: Dict, config: Dict) -> Dict:
        """5 ajan karar sistemi."""
        try:
            # Tech data (zaten var)
            tech_data = analysis

            # Fund data
            fund_data = {"fundamental_score": 0, "metrics": {}}
            try:
                fund_data = self.fundamental_analyzer.analyze_fundamentals(symbol)
            except Exception:
                pass

            # Sentiment data
            sent_data = {"news_score": 0}
            try:
                news = self.news_analyzer.analyze_stock_news(symbol)
                sent_data = {
                    "news_score": news.get("news_score", 0),
                    "sentiment_label": news.get("signal", "NEUTRAL"),
                    "fear_greed_value": 50,
                    "fear_greed_signal": "NEUTRAL",
                }
            except Exception:
                pass

            # Social data
            social_data = {"social_score": 0}
            try:
                social_data = self.social_analyzer.analyze_social(symbol)
            except Exception:
                pass

            # Risk data
            risk_data = self._build_risk_data(analysis, config)

            # Dinamik ajan ağırlıkları (performans bazlı)
            try:
                dynamic_weights = self.agent_perf.get_dynamic_weights()
                self.coordinator.WEIGHTS = dynamic_weights
            except Exception:
                pass  # Hata durumunda varsayılan ağırlıklar kullanılır

            # Coordinator kararı
            decision = self.coordinator.decide(
                symbol, tech_data, fund_data,
                sent_data, social_data, risk_data
            )

            # Ajan tahminlerini kaydet (öz-değerlendirme için)
            try:
                if decision.get("signal") != "HOLD":
                    self.agent_perf.record_prediction(
                        symbol=symbol,
                        agent_votes=decision.get("votes", []),
                        coordinator_signal=decision["signal"],
                    )
            except Exception:
                pass

            return decision

        except Exception as e:
            logger.debug(f"  {symbol} ajan karar hatası: {e}")
            return {"signal": "HOLD", "confidence": 0}

    def _build_risk_data(self, analysis: Dict, config: Dict) -> Dict:
        """Risk ajanı için veri hazırla."""
        try:
            account = self.client.get_account()
            equity = float(account.equity)
            daily_pnl = equity - self.initial_equity
            daily_pnl_pct = (daily_pnl / self.initial_equity * 100) if self.initial_equity > 0 else 0

            # VIX
            vix = 0
            geo_risk = "NORMAL"
            oil_signal = "STABLE"
            try:
                macro = self.macro_analyzer.get_macro_score()
                vix = macro.get("vix", {}).get("vix", 0)
                oil_signal = macro.get("oil", {}).get("signal", "STABLE")
            except Exception:
                pass

            # Jeopolitik risk (haberlerden)
            try:
                market_sent = self.news_analyzer.get_market_sentiment()
                geo_risk = market_sent.get("geopolitical_risk", "NORMAL")
            except Exception:
                pass

            return {
                "daily_pnl_pct": daily_pnl_pct,
                "open_positions": len(self.positions),
                "max_positions": config.get("max_open_positions", 3),
                "atr_pct": (analysis.get("atr", 0) / analysis.get("price", 1) * 100) if analysis.get("price", 0) > 0 else 0,
                "equity_floor_hit": equity < self.equity_floor,
                "vix": vix,
                "geopolitical_risk": geo_risk,
                "oil_signal": oil_signal,
            }
        except Exception:
            return {}

    # ============================================================
    # POZİSYON YÖNETİMİ
    # ============================================================

    def _manage_positions(self, config: Dict):
        """Açık pozisyonları yönet — trailing stop, take profit, break-even."""
        try:
            self.position_manager.manage_positions(config)
        except Exception as e:
            logger.error(f"  Pozisyon yönetim hatası: {e}")

    # ============================================================
    # VERİ ÇEKME
    # ============================================================

    def get_stock_bars(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """Alpaca'dan hisse bar verisi çek."""
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Hour,
                start=datetime.now() - timedelta(days=days),
            )
            bars = self.data_client.get_stock_bars(request)
            df = bars.df

            if hasattr(df.index, 'droplevel'):
                try:
                    df = df.droplevel("symbol")
                except (KeyError, ValueError):
                    pass

            return df

        except Exception as e:
            logger.debug(f"  {symbol} bar verisi hatası: {e}")
            return pd.DataFrame()

    # ============================================================
    # YARDIMCI
    # ============================================================

    def _get_symbols_to_analyze(self) -> List[str]:
        """Analiz edilecek hisseleri döndür — tarama sonucuna göre sırala."""
        # Tarama sonuçları varsa öncelikli
        if self.screener.scan_cache:
            sorted_symbols = sorted(
                self.screener.scan_cache.keys(),
                key=lambda s: self.screener.scan_cache[s].get("score", 0),
                reverse=True,
            )
            return sorted_symbols[:10]

        # Yoksa varsayılan havuz
        return STOCK_CONFIG.get("symbols", list(STOCK_IDS.keys()))[:10]

    def _sector_limit_reached(self, symbol: str, config: Dict) -> bool:
        """Aynı sektörde max pozisyon kontrolü."""
        max_per_sector = config.get("max_positions_per_sector", 2)
        symbol_sector = SECTOR_MAP.get(symbol, "Unknown")
        if symbol_sector == "Unknown":
            return False

        sector_count = 0
        for pos_symbol in self.positions:
            if SECTOR_MAP.get(pos_symbol, "") == symbol_sector:
                sector_count += 1

        if sector_count >= max_per_sector:
            logger.debug(
                f"  {symbol} SEKTÖR LİMİT: {symbol_sector} sektöründe "
                f"{sector_count}/{max_per_sector} pozisyon dolu"
            )
            return True
        return False

    def _log_heartbeat(self):
        """Gelişmiş heartbeat logu."""
        try:
            account = self.client.get_account()
            equity = float(account.equity)
            cash = float(account.cash)
            self.equity = equity
            pnl = equity - self.initial_equity
            pnl_pct = (pnl / self.initial_equity * 100) if self.initial_equity > 0 else 0

            market_status = self.market_hours.get_market_status()
            pdt_status = self.pdt_tracker.get_status()

            # Pozisyon detayları
            pos_details = []
            for sym, data in self.positions.items():
                entry = data.get("entry_price", 0)
                pos_details.append(f"{sym}@${entry:.2f}")

            logger.info(
                f"  💓 ${equity:,.2f} ({pnl:+.2f}/{pnl_pct:+.1f}%) | "
                f"Cash: ${cash:,.2f} | "
                f"Poz: {len(self.positions)} [{', '.join(pos_details) or 'yok'}] | "
                f"İşlem: {len(self.trades_today)} | "
                f"DT: {pdt_status['week_day_trades']}/{pdt_status['max_day_trades']} | "
                f"Zarar serisi: {self._consecutive_losses} | "
                f"Piyasa: {market_status['status']} {market_status.get('time_et', '')} | "
                f"Kill: {'⚠️AKTİF' if self.kill_switch.is_active else 'OK'}"
            )

            # PDT güncelle
            self.pdt_tracker.update_equity(equity)

            # Periyodik pozisyon sync (her 10 heartbeat'te)
            if self._heartbeat_counter % 300 == 0:
                self._sync_positions_from_alpaca()

            # Pozisyon metadata kaydet
            self._save_position_metadata()

        except Exception as e:
            logger.error(f"  Heartbeat hatası: {e}")

    def _periodic_status_report(self, config: Dict):
        """Periyodik durum raporu + gunluk kapanış raporu."""
        interval = config.get("status_report_interval", 5) * 60
        if (datetime.now() - self._last_status_time).total_seconds() < interval:
            return
        self._last_status_time = datetime.now()
        self._log_heartbeat()

        # Gunluk Telegram raporu (gunde 1 kez, 15:50-16:00 arasi)
        now = datetime.now()
        if (now.hour == 15 and now.minute >= 50 and
            getattr(self, '_daily_report_date', None) != date.today()):
            try:
                if hasattr(self, 'notifier'):
                    self.notifier.send_daily_report(self)
                    self._daily_report_date = date.today()
                    logger.info("  Gunluk Telegram raporu gonderildi")
            except Exception as e:
                logger.debug(f"  Gunluk rapor hatasi: {e}")

    # ============================================================
    # POZİSYON SENKRONİZASYONU & PERSISTENCE
    # ============================================================

    def _sync_positions_from_alpaca(self):
        """Alpaca'dan açık pozisyonları senkronize et (restart-safe).
        
        Alpaca'da qty > 0 = LONG, qty < 0 = SHORT pozisyon.
        BOT_MODE'a göre sadece ilgili pozisyonlar sync edilir.
        """
        try:
            alpaca_positions = self.client.get_all_positions()
            synced_long = 0
            synced_short = 0

            for pos in alpaca_positions:
                symbol = pos.symbol
                qty = float(pos.qty)
                entry_price = float(pos.avg_entry_price)
                current_price = float(pos.current_price)
                unrealized_pl = float(pos.unrealized_pl)

                if qty > 0:
                    # LONG pozisyon
                    if symbol not in self.positions and BOT_MODE in ("long_only", "both"):
                        self.positions[symbol] = {
                            "entry_price": entry_price,
                            "qty": qty,
                            "entry_time": datetime.now().isoformat(),
                            "synced_from_alpaca": True,
                            "highest_price": current_price,
                        }
                        synced_long += 1
                        logger.info(
                            f"  🔄 LONG sync: {symbol} | "
                            f"{qty:.4f} @ ${entry_price:,.2f} | "
                            f"P&L: ${unrealized_pl:+.2f}"
                        )
                elif qty < 0:
                    # SHORT pozisyon (Alpaca negatif qty = short)
                    if symbol not in self.short_positions and BOT_MODE in ("short_only", "both"):
                        self.short_positions[symbol] = {
                            "entry_price": entry_price,
                            "qty": abs(qty),
                            "entry_time": datetime.now().isoformat(),
                            "synced_from_alpaca": True,
                            "lowest_price": current_price,
                        }
                        synced_short += 1
                        logger.info(
                            f"  🔄 SHORT sync: {symbol} | "
                            f"{abs(qty):.4f} @ ${entry_price:,.2f} | "
                            f"P&L: ${unrealized_pl:+.2f}"
                        )

            # Bot'ta var ama Alpaca'da olmayan pozisyonları temizle
            alpaca_long_symbols = {pos.symbol for pos in alpaca_positions if float(pos.qty) > 0}
            alpaca_short_symbols = {pos.symbol for pos in alpaca_positions if float(pos.qty) < 0}

            for symbol in list(self.positions.keys()):
                if symbol not in alpaca_long_symbols:
                    logger.warning(f"  🗑️ LONG temizlendi (Alpaca'da yok): {symbol}")
                    self.positions.pop(symbol)

            for symbol in list(self.short_positions.keys()):
                if symbol not in alpaca_short_symbols:
                    logger.warning(f"  🗑️ SHORT temizlendi (Alpaca'da yok): {symbol}")
                    self.short_positions.pop(symbol)

            total = synced_long + synced_short
            if total > 0:
                logger.info(f"  Sync: {synced_long} long + {synced_short} short = {total} pozisyon")

        except Exception as e:
            logger.error(f"  Pozisyon sync hatası: {e}")

    def _save_position_metadata(self):
        """Pozisyon metadata'sını dosyaya kaydet (restart-safe)."""
        try:
            data = {
                "positions": self.positions,
                "short_positions": self.short_positions,
                "last_trade_time": {
                    k: (v.isoformat() if hasattr(v, 'isoformat') else str(v))
                    for k, v in self.last_trade_time.items()
                },
                "consecutive_losses": self._consecutive_losses,
                "symbol_consecutive_losses": self._symbol_consecutive_losses,
                "daily_buys_count": self._daily_buys_count,
                "trades_today": self.trades_today,
                "last_update": datetime.now().isoformat(),
            }
            with open(self.POSITIONS_FILE, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"  Pozisyon kayıt hatası: {e}")

    def _load_position_metadata(self):
        """Kaydedilmiş pozisyon metadata'sını yükle."""
        try:
            if os.path.exists(self.POSITIONS_FILE):
                with open(self.POSITIONS_FILE, "r") as f:
                    data = json.load(f)
                # Sadece metadata'yı güncelle (pozisyonlar Alpaca'dan geldi)
                for sym, meta in data.get("positions", {}).items():
                    if sym in self.positions:
                        # Mevcut pozisyona ek bilgileri aktar
                        self.positions[sym].update({
                            "entry_time": meta.get("entry_time", self.positions[sym].get("entry_time")),
                            "highest_price": meta.get("highest_price", self.positions[sym].get("highest_price", 0)),
                            "stop_loss_pct": meta.get("stop_loss_pct"),
                            "breakeven_set": meta.get("breakeven_set", False),
                            "partial_sold": meta.get("partial_sold", False),
                            "synced_from_alpaca": False,
                        })
                # Short pozisyon metadata'sını yükle
                for sym, meta in data.get("short_positions", {}).items():
                    if sym in self.short_positions:
                        self.short_positions[sym].update({
                            "entry_time": meta.get("entry_time", self.short_positions[sym].get("entry_time")),
                            "lowest_price": meta.get("lowest_price", self.short_positions[sym].get("lowest_price", 0)),
                            "stop_loss_pct": meta.get("stop_loss_pct"),
                            "breakeven_set": meta.get("breakeven_set", False),
                            "partial_covered": meta.get("partial_covered", False),
                            "synced_from_alpaca": False,
                        })
                self._consecutive_losses = data.get("consecutive_losses", 0)
                self._symbol_consecutive_losses = data.get("symbol_consecutive_losses", {})
                logger.info(f"  📁 Metadata yüklendi ({len(self.positions)} long + {len(self.short_positions)} short)")
        except Exception as e:
            logger.debug(f"  Pozisyon metadata yüklenemedi: {e}")

    # ============================================================
    # GÜNLÜK RESET & ACİL DURUM
    # ============================================================

    def _daily_reset(self):
        """Her yeni gün başında değişkenleri sıfırla."""
        today = date.today()
        if self._daily_reset_date == today:
            return

        # Önceki günün özetini gönder (ilk çalıştırma hariç)
        if self._daily_reset_date is not None:
            pnl = self.equity - self.initial_equity
            wins = len([t for t in self.trades_today if "TAKE_PROFIT" in str(t) or "TRAILING_STOP" in str(t)])
            losses = len([t for t in self.trades_today if "STOP_LOSS" in str(t)])
            self.notifier.notify_daily_summary(
                equity=self.equity, pnl=pnl,
                trades_count=len(self.trades_today),
                positions=self.positions,
                wins=wins, losses=losses,
            )

        self._daily_reset_date = today
        self.trades_today = []
        self._daily_buys_count = 0
        self._morning_scan_done = False
        self.initial_equity = self.equity  # Günlük PnL için baz
        logger.info(f"  📆 Günlük reset: {today} | Başlangıç equity: ${self.equity:,.2f}")

    def _emergency_close_all(self, reason: str):
        """KillSwitch tarafından çağrılır — tüm pozisyonları kapat."""
        logger.error(f"🚨 ACİL KAPANIŞ: {reason}")
        self.notifier.notify_kill_switch(reason, self.equity)
        try:
            self.client.close_all_positions(cancel_orders=True)
            logger.error("  Tüm pozisyonlar kapatıldı, emirler iptal edildi.")
            self.positions.clear()
        except Exception as e:
            logger.error(f"  Acil kapanış hatası: {e}")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    bot = StockBot()
    bot.run()
