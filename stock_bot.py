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
    ALPACA_API_KEY, ALPACA_SECRET_KEY, TRADING_MODE,
    get_base_url, STOCK_CONFIG, STOCK_IDS, STOCK_SEARCH_TERMS,
    SECTOR_MAP,
)

# Core modüller
from core.market_hours import MarketHours
from core.pdt_tracker import PDTTracker
from core.stock_screener import StockScreener
from core.earnings_calendar import EarningsCalendar
from core.agent_coordinator import AgentCoordinator
from core.analyzer import TechnicalAnalyzer
from core.executor import OrderExecutor
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
        self.last_trade_time = {}
        self.trades_today = []
        self.sell_cooldown = {}
        self.consecutive_errors = 0
        self._consecutive_losses = 0
        self._symbol_consecutive_losses = {}  # Hisse bazlı ardışık zarar
        self._daily_buys_count = 0
        self._last_status_time = datetime.min
        self._heartbeat_counter = 0
        self._morning_scan_done = False
        self._morning_scan_date = None
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

        # FinBERT (opsiyonel)
        if FINBERT_AVAILABLE:
            try:
                self.finbert = FinBERTAnalyzer()
            except Exception:
                self.finbert = None
        else:
            self.finbert = None

        # Teknik analizci
        self.analyzer = TechnicalAnalyzer(self)

        # === POZİSYON SENKRONİZASYONU (restart-safe) ===
        self._sync_positions_from_alpaca()
        self._load_position_metadata()

        mode_str = "PAPER" if is_paper else "🔴 LIVE"
        logger.info("=" * 60)
        logger.info(f"  STOCK TRADING BOT BAŞLATILDI")
        logger.info(f"  Mod: {mode_str} | Equity: ${equity:,.2f}")
        logger.info(f"  Max pozisyon: ${self.max_pos_usd} | Floor: ${self.equity_floor:,.2f}")
        logger.info(f"  Hisse havuzu: {len(config['symbols'])} hisse")
        logger.info(f"  Açık pozisyon: {len(self.positions)}")
        logger.info(f"  PDT: {'EXEMPT' if equity >= 25000 else f'ACTIVE (max 2 DT/hafta)'}")
        logger.info(f"  KillSwitch: AKTİF | WashSale: AKTİF")
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

                # Pozisyon yönetimi (her döngüde)
                self._manage_positions(config)

                # Güvenli bölge kontrolü
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

                time.sleep(config.get("scan_interval_seconds", 30))

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
                logger.info(f"  VIX: {macro['vix'].get('description', 'N/A')}")
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
    # HİSSE ANALİZİ VE İŞLEM
    # ============================================================

    def _analyze_and_trade(self, symbol: str, config: Dict):
        """Tek bir hisseyi analiz et ve gerekirse işlem yap."""
        try:
            # Teknik analiz
            analysis = self._get_technical_analysis(symbol, config)
            if analysis is None:
                return

            # Multi-agent karar
            decision = self._get_agent_decision(symbol, analysis, config)

            if decision["signal"] == "BUY" and decision["confidence"] >= config.get("min_confidence_score", 50):
                # Gate kontrolü
                passed, block_reason = self.trade_gates.check_all_gates(symbol, analysis, config)
                if passed:
                    analysis["confidence"] = decision["confidence"]
                    analysis["reasons"] = [decision["reasoning"]]
                    self.executor.execute_buy(symbol, analysis, config)
                else:
                    logger.debug(f"  {symbol} GATE BLOK: {block_reason}")

        except Exception as e:
            logger.debug(f"  {symbol} analiz hatası: {e}")

    def _get_technical_analysis(self, symbol: str, config: Dict) -> Optional[Dict]:
        """Hisse için teknik analiz yap."""
        try:
            df = self.get_stock_bars(symbol, days=30)
            if df.empty or len(df) < 14:
                return None

            close = df["close"]
            price = float(close.iloc[-1])

            # RSI
            rsi = RSIIndicator(close, window=14).rsi().iloc[-1]

            # EMA'lar
            ema9 = EMAIndicator(close, window=9).ema_indicator().iloc[-1]
            ema21 = EMAIndicator(close, window=21).ema_indicator().iloc[-1]
            ema50 = EMAIndicator(close, window=min(50, len(close)-1)).ema_indicator().iloc[-1] if len(close) >= 50 else price

            # EMA200 (varsa)
            above_ema200 = True
            if len(close) >= 200:
                ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]
                above_ema200 = price > ema200

            # MACD
            macd_obj = MACD(close)
            macd_line = macd_obj.macd().iloc[-1]
            macd_signal = macd_obj.macd_signal().iloc[-1]
            macd_cross = "BULLISH" if macd_line > macd_signal else "BEARISH"

            # Bollinger Bands
            bb = BollingerBands(close)
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_upper = bb.bollinger_hband().iloc[-1]

            # ATR
            atr = AverageTrueRange(df["high"], df["low"], close).average_true_range().iloc[-1]

            # Skor hesapla
            tech_score = 0
            reasons = []

            if rsi < config.get("rsi_oversold", 30):
                tech_score += 25
                reasons.append(f"RSI oversold ({rsi:.0f})")
            elif rsi > config.get("rsi_overbought", 70):
                tech_score -= 20
                reasons.append(f"RSI overbought ({rsi:.0f})")

            if ema9 > ema21:
                tech_score += 15
                reasons.append("EMA9>EMA21")
            else:
                tech_score -= 10

            if macd_cross == "BULLISH":
                tech_score += 15
                reasons.append("MACD bullish")

            if price <= bb_lower * 1.01:
                tech_score += 10
                reasons.append("BB bant dibi")

            # Sinyal belirle
            signal = "HOLD"
            if tech_score >= 30:
                signal = "BUY"
            elif tech_score <= -20:
                signal = "SELL"

            return {
                "signal": signal,
                "price": price,
                "rsi": rsi,
                "ema9": ema9,
                "ema21": ema21,
                "macd_signal": macd_cross,
                "atr": atr,
                "above_ema200": above_ema200,
                "tech_score": tech_score,
                "confidence": min(abs(tech_score) * 1.5, 100),
                "reasons": reasons,
            }

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

            # Coordinator kararı
            decision = self.coordinator.decide(
                symbol, tech_data, fund_data,
                sent_data, social_data, risk_data
            )
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
        """Periyodik durum raporu."""
        interval = config.get("status_report_interval", 5) * 60
        if (datetime.now() - self._last_status_time).total_seconds() < interval:
            return
        self._last_status_time = datetime.now()
        self._log_heartbeat()

    # ============================================================
    # POZİSYON SENKRONİZASYONU & PERSISTENCE
    # ============================================================

    def _sync_positions_from_alpaca(self):
        """Alpaca'dan açık pozisyonları senkronize et (restart-safe)."""
        try:
            alpaca_positions = self.client.get_all_positions()
            synced = 0
            for pos in alpaca_positions:
                symbol = pos.symbol
                if symbol not in self.positions:
                    self.positions[symbol] = {
                        "entry_price": float(pos.avg_entry_price),
                        "qty": float(pos.qty),
                        "entry_time": datetime.now().isoformat(),  # Gerçek zaman bilinmiyor
                        "synced_from_alpaca": True,
                        "highest_price": float(pos.current_price),
                    }
                    synced += 1
                    logger.info(
                        f"  🔄 Pozisyon sync: {symbol} | "
                        f"{float(pos.qty):.4f} @ ${float(pos.avg_entry_price):,.2f} | "
                        f"P&L: ${float(pos.unrealized_pl):+.2f}"
                    )

            # Bot'ta var ama Alpaca'da olmayan pozisyonları temizle
            alpaca_symbols = {pos.symbol for pos in alpaca_positions}
            for symbol in list(self.positions.keys()):
                if symbol not in alpaca_symbols:
                    logger.warning(f"  🗑️ Pozisyon temizlendi (Alpaca'da yok): {symbol}")
                    self.positions.pop(symbol)

            if synced > 0:
                logger.info(f"  Toplam {synced} pozisyon Alpaca'dan senkronize edildi")

        except Exception as e:
            logger.error(f"  Pozisyon sync hatası: {e}")

    def _save_position_metadata(self):
        """Pozisyon metadata'sını dosyaya kaydet (restart-safe)."""
        try:
            data = {
                "positions": self.positions,
                "last_trade_time": {k: v.isoformat() for k, v in self.last_trade_time.items()},
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
                self._consecutive_losses = data.get("consecutive_losses", 0)
                self._symbol_consecutive_losses = data.get("symbol_consecutive_losses", {})
                logger.info(f"  📁 Pozisyon metadata yüklendi ({len(self.positions)} pozisyon)")
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
