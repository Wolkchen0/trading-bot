"""
AI Trading Bot - Ana Çalıştırıcı
Otomatik hisse tarama, analiz, sinyal üretimi ve emir gönderme.

Kullanım:
  python main.py                     # Paper trading (varsayılan)
  python main.py --mode paper        # Paper trading
  python main.py --mode live         # Canlı trading (dikkat!)
  python main.py --backtest AAPL     # Backtest çalıştır
  python main.py --scan              # Sadece hisse tara
  python main.py --webhook           # TradingView webhook modunu aç
  python main.py --dashboard         # Dashboard'u aç
"""
import argparse
import time
import sys
import os
from datetime import datetime
import pytz

from config import (
    SCHEDULE_CONFIG,
    RISK_CONFIG,
    KILL_SWITCH_CONFIG,
    TRADING_MODE,
)
from core.data_fetcher import DataFetcher
from core.technical_analysis import TechnicalAnalysis
from core.stock_scanner import StockScanner
from core.signal_generator import SignalType
from core.risk_manager import RiskManager
from core.order_executor import OrderExecutor
from core.portfolio_tracker import PortfolioTracker
from core.compliance import PDTTracker, WashSaleTracker, TaxExporter
from core.kill_switch import KillSwitch
from strategies.multi_strategy import MultiStrategy
from utils.logger import logger


class TradingBot:
    """AI Trading Bot ana sınıfı."""

    def __init__(self):
        logger.info("=" * 60)
        logger.info("🤖 AI TRADING BOT BAŞLATILIYOR...")
        logger.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"📝 Mod: {'PAPER (Demo)' if TRADING_MODE == 'paper' else '🔴 LIVE (Gerçek)'}")
        logger.info("=" * 60)

        # Modüller
        self.data_fetcher = DataFetcher()
        self.ta = TechnicalAnalysis()
        self.scanner = StockScanner(self.data_fetcher)
        self.strategy = MultiStrategy()
        self.executor = OrderExecutor()
        self.tracker = PortfolioTracker()

        # Hesap bilgileri
        account = self.executor.get_account()
        if account:
            self.equity = account["equity"]
            self.risk_manager = RiskManager(self.equity)
            self.pdt_tracker = PDTTracker(self.equity)
            self.wash_sale_tracker = WashSaleTracker()
            self.tax_exporter = TaxExporter()
            logger.info(f"💰 Hesap: ${self.equity:,.2f}")
            if self.equity < 25000:
                logger.warning(
                    f"⚠️ PDT UYARISI: Bakiye ${self.equity:,.2f} < $25,000. "
                    f"Hisse senedinde haftada max 3 day trade yapabilirsiniz!"
                )
        else:
            logger.error("Hesap bilgisi alınamadı! API key'leri kontrol edin.")
            sys.exit(1)

        self.running = True
        self.starting_equity = self.equity
        self.et_tz = pytz.timezone(SCHEDULE_CONFIG["timezone"])

        # Kill Switch (acil durum)
        self.kill_switch = KillSwitch(
            max_consecutive_errors=KILL_SWITCH_CONFIG["max_consecutive_api_errors"],
            max_daily_loss_pct=KILL_SWITCH_CONFIG["max_daily_loss_pct"],
        )
        self.kill_switch.set_callback(self._emergency_shutdown)

        if self.kill_switch.is_active:
            logger.error("🚨 Kill switch önceki oturumdan aktif. Bot başlatılamıyor.")
            logger.error("   Resetlemek için: python main.py --kill-reset")
            sys.exit(1)

    def run(self):
        """Ana trading döngüsü."""
        logger.info("\n🚀 Trading döngüsü başlıyor...")
        scan_interval = SCHEDULE_CONFIG["scan_interval_seconds"]

        while self.running:
            try:
                # Kill switch kontrolü
                if self.kill_switch.is_active:
                    logger.error("🚨 Kill switch aktif! Bot durduruluyor.")
                    self.running = False
                    break

                # Piyasa saatlerini kontrol et
                if not self._is_market_hours():
                    logger.info("⏸️ Piyasa kapalı. Bekleniyor...")
                    time.sleep(60)
                    continue

                # Günlük hesap güncelleme
                self._update_account()

                # Kill switch: günlük kayıp kontrolü
                if self.kill_switch.check_daily_loss(self.equity, self.starting_equity):
                    self.running = False
                    break

                # Trade yapılabilir mi kontrol et
                can_trade, msg = self.risk_manager.can_trade()
                if not can_trade:
                    logger.warning(f"⛔ Trade durdu: {msg}")
                    time.sleep(scan_interval)
                    continue

                # Önce açık pozisyonları yönet
                self._manage_open_positions()

                # Yeni fırsatları tara
                self._scan_and_trade()

                # Başarılı döngü — hata sayacını sıfırla
                self.kill_switch.reset_error_count()

                # Bekleme
                logger.info(f"⏳ {scan_interval}s bekleniyor...\n")
                time.sleep(scan_interval)

            except KeyboardInterrupt:
                logger.info("\n🛑 Bot kullanıcı tarafından durduruldu")
                self.running = False
            except Exception as e:
                logger.error(f"❌ Hata: {e}")
                # Kill switch: API hata sayacı
                if self.kill_switch.check_api_error(e):
                    self.running = False
                    break
                time.sleep(30)

        self._shutdown()

    def _is_market_hours(self) -> bool:
        """ABD piyasasının açık olup olmadığını kontrol eder."""
        now = datetime.now(self.et_tz)

        # Hafta sonu
        if now.weekday() >= 5:
            return False

        market_open = datetime.strptime(SCHEDULE_CONFIG["market_open"], "%H:%M").time()
        stop_time = datetime.strptime(SCHEDULE_CONFIG["stop_trading_time"], "%H:%M").time()

        return market_open <= now.time() <= stop_time

    def _update_account(self):
        """Hesap bilgilerini günceller."""
        account = self.executor.get_account()
        if account:
            self.equity = account["equity"]
            self.risk_manager.update_equity(self.equity)
            self.risk_manager.update_daily_pnl(account["daily_pnl"])

            positions = self.executor.get_positions()
            self.risk_manager.update_positions_count(len(positions))
            self.pdt_tracker.update_equity(self.equity)

    def _scan_and_trade(self):
        """Hisseleri tarar ve trade sinyali ararken bulduklarında işlem yapar."""
        # Momentum hisselerini tara
        movers = self.scanner.get_top_gainers(limit=5)

        if not movers:
            logger.info("📭 Filtre kriterlerine uyan hisse bulunamadı")
            return

        logger.info(f"\n🔍 {len(movers)} hisse analiz ediliyor...")

        for mover in movers:
            symbol = mover["symbol"]

            try:
                # Bu hissede zaten pozisyonumuz var mı?
                positions = self.executor.get_positions()
                if any(p["symbol"] == symbol for p in positions):
                    logger.debug(f"  {symbol}: Zaten pozisyonda, atlanıyor")
                    continue

                # Teknik analiz için veri çek
                df = self.data_fetcher.get_minute_bars(symbol, days_back=3)
                if df.empty or len(df) < 50:
                    continue

                # Teknik göstergeleri hesapla
                df = self.ta.calculate_all(df)
                signal_data = self.ta.get_signal_data(df)
                if not signal_data:
                    continue

                # Çoklu strateji analizi
                final_signal = self.strategy.analyze(signal_data)

                # BUY sinyali varsa ve güven yeterliyse
                if (
                    final_signal.signal_type == SignalType.BUY
                    and self.risk_manager.check_signal_confidence(final_signal.confidence)
                ):
                    # PDT kontrolü (hisse senedinde day trade limiti)
                    can_dt, pdt_msg = self.pdt_tracker.can_day_trade("stock")
                    if not can_dt:
                        logger.warning(f"  {symbol}: {pdt_msg}")
                        continue

                    # Wash Sale kontrolü
                    is_wash, ws_msg = self.wash_sale_tracker.check_wash_sale(symbol)
                    if is_wash:
                        logger.warning(f"  {symbol}: {ws_msg}")
                        # Wash sale uyarısı — işlem yapılabilir ama vergi etkisi not edilir

                    self._execute_buy(symbol, signal_data, final_signal.confidence)

            except Exception as e:
                logger.error(f"  {symbol} analiz hatası: {e}")

    def _execute_buy(self, symbol: str, signal_data: dict, confidence: float):
        """Alış emri gönderir."""
        close = signal_data["close"]
        atr = signal_data.get("atr", close * 0.02)

        # Stop-loss ve take-profit hesapla
        stop_loss = self.ta.calculate_stop_loss(close, atr, "buy")
        take_profit = self.ta.calculate_take_profit(close, stop_loss)

        # Pozisyon büyüklüğü hesapla
        position = self.risk_manager.calculate_position_size(close, stop_loss)
        shares = position["shares"]

        if shares <= 0:
            logger.info(f"  {symbol}: Hisse sayısı 0, işlem yapılmıyor")
            return

        # Bracket order gönder (alış + stop-loss + take-profit)
        logger.info(
            f"\n{'='*40}\n"
            f"🟢 ALIŞ EMRI: {symbol}\n"
            f"  Hisse: {shares}\n"
            f"  Fiyat: ${close:.2f}\n"
            f"  Stop-Loss: ${stop_loss:.2f}\n"
            f"  Take-Profit: ${take_profit:.2f}\n"
            f"  Risk: ${position['risk_amount']:.2f} ({position['risk_pct']:.1f}%)\n"
            f"  Güven: {confidence:.0%}\n"
            f"{'='*40}"
        )

        result = self.executor.place_bracket_order(
            symbol=symbol,
            qty=shares,
            limit_price=round(close * 1.005, 2),  # %0.5 slippage payı
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
        )

        if result:
            # Trade kaydet
            self.tracker.add_trade({
                "action": "BUY",
                "symbol": symbol,
                "qty": shares,
                "price": close,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": confidence,
                "fee": position.get("fees", {}).get("total_round_trip", 0),
                "order_id": result.get("id", ""),
            })

    def _manage_open_positions(self):
        """Açık pozisyonları yönetir (trailing stop vb.)."""
        positions = self.executor.get_positions()

        for pos in positions:
            symbol = pos["symbol"]
            entry = pos["avg_entry"]
            current = pos["current_price"]
            pnl_pct = pos["unrealized_pnl_pct"]

            # Kâr çok yüksekse %50 sat
            if pnl_pct >= 10.0:
                logger.info(f"💰 {symbol}: +{pnl_pct:.1f}% — %50 kâr alma")
                self.executor.sell_partial(symbol, 0.5)

                self.tracker.add_trade({
                    "action": "PARTIAL_SELL",
                    "symbol": symbol,
                    "qty": pos["qty"] // 2,
                    "price": current,
                    "pnl": pos["unrealized_pnl"] * 0.5,
                    "reason": "Kısmi kâr alma (+10%)",
                })

    def _emergency_shutdown(self, reason: str):
        """
        🚨 ACİL KAPANIŞ: Tüm pozisyonları piyasa fiyatından kapat.
        Kill switch tarafından tetiklenir.
        """
        logger.error(f"🚨 ACİL KAPANIŞ: {reason}")
        logger.error("Tüm emirler iptal ediliyor...")
        self.executor.cancel_all_orders()

        logger.error("Tüm pozisyonlar kapatılıyor (piyasa fiyatından)...")
        self.executor.close_all_positions()

        logger.error("🚨 Acil kapanış tamamlandı. Bot durduruluyor.")
        self.running = False

    def _shutdown(self):
        """Bot kapanış prosedürü."""
        logger.info("\n🏁 Bot kapatılıyor...")

        # Günlük istatistikler
        stats = self.risk_manager.get_daily_stats()
        if stats["total_trades"] > 0:
            logger.info(f"📊 Günlük Özet:")
            logger.info(f"  İşlemler: {stats['total_trades']}")
            logger.info(f"  Win Rate: {stats['win_rate']:.1f}%")
            logger.info(f"  P&L: ${stats['total_pnl']:,.2f}")
            logger.info(f"  Komisyon: ${self.risk_manager.get_daily_fees():,.2f}")

        # Vergi raporu oluştur
        trades = self.tracker.trades
        if trades:
            csv_path = self.tax_exporter.export_to_csv(trades)
            if csv_path:
                logger.info(f"📄 Vergi raporu kaydedildi: {csv_path}")

        # PDT durumu
        remaining = self.pdt_tracker.get_remaining_day_trades()
        if remaining < 999:
            logger.info(f"📋 PDT: Kalan day trade hakkı: {remaining}/3")

        logger.info("👋 Bot başarıyla kapatıldı\n")


def run_backtest(symbol: str, period: str = "6mo", capital: float = 10000):
    """Backtest çalıştırır."""
    from backtesting.backtester import Backtester
    bt = Backtester(initial_capital=capital)
    bt.run(symbol, period)


def run_scan():
    """Sadece hisse tarama yapar."""
    fetcher = DataFetcher()
    scanner = StockScanner(fetcher)
    logger.info("\n🔎 Hisse taraması başlıyor...\n")
    movers = scanner.scan_movers()
    if movers:
        logger.info(f"\n✅ {len(movers)} hisse bulundu!")
    else:
        logger.info("📭 Uygun hisse bulunamadı")


def run_webhook():
    """TradingView webhook modunu başlatır."""
    from core.webhook_receiver import WebhookReceiver

    executor = OrderExecutor()

    def on_signal(signal):
        """Webhook sinyali geldiğinde çalışır."""
        action = signal.get("action", "")
        symbol = signal.get("symbol", "")
        qty = signal.get("qty", 0)

        if action == "buy" and qty > 0:
            executor.buy_market(symbol, int(qty))
        elif action == "sell" and qty > 0:
            executor.sell_market(symbol, int(qty))
        elif action == "close":
            executor.sell_all(symbol)

    webhook = WebhookReceiver(port=5000)
    webhook.set_callback(on_signal)
    logger.info("🌐 TradingView Webhook modu başlatılıyor...")
    logger.info("📩 URL: http://localhost:5000/webhook")
    webhook.start(threaded=False)


def run_dashboard():
    """Streamlit dashboard'u başlatır."""
    import subprocess
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard", "app.py")
    logger.info("🖥️ Dashboard başlatılıyor...")
    subprocess.run(["streamlit", "run", dashboard_path], check=True)


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="🤖 AI Trading Bot")
    parser.add_argument("--mode", choices=["paper", "live"], default=None,
                       help="Trading modu (paper/live)")
    parser.add_argument("--backtest", type=str, default=None,
                       help="Backtest yapılacak hisse (ör: AAPL)")
    parser.add_argument("--period", type=str, default="6mo",
                       help="Backtest periyodu (ör: 6mo, 1y)")
    parser.add_argument("--capital", type=float, default=10000,
                       help="Backtest başlangıç sermayesi")
    parser.add_argument("--scan", action="store_true",
                       help="Sadece hisse tarama yap")
    parser.add_argument("--webhook", action="store_true",
                       help="TradingView webhook modunu aç")
    parser.add_argument("--dashboard", action="store_true",
                       help="Dashboard'u aç")
    parser.add_argument("--export-tax", action="store_true",
                       help="Vergi raporunu CSV olarak dışa aktar")
    parser.add_argument("--security", action="store_true",
                       help="API güvenlik kontrol listesini göster")
    parser.add_argument("--kill-reset", action="store_true",
                       help="Kill switch'i sıfırla (acil durumdan kurtulmak için)")

    args = parser.parse_args()

    # Mode override
    if args.mode:
        os.environ["TRADING_MODE"] = args.mode

    try:
        if args.backtest:
            run_backtest(args.backtest, args.period, args.capital)
        elif args.scan:
            run_scan()
        elif args.webhook:
            run_webhook()
        elif args.dashboard:
            run_dashboard()
        elif args.export_tax:
            tracker = PortfolioTracker()
            TaxExporter.export_to_csv(tracker.trades)
            logger.info("✅ Vergi raporu oluşturuldu!")
        elif args.security:
            from core.compliance import print_security_checklist
            print_security_checklist()
        elif args.kill_reset:
            ks = KillSwitch()
            ks.reset()
            logger.info("✅ Kill switch sıfırlandı. Bot tekrar başlatılabilir.")
        else:
            bot = TradingBot()
            bot.run()
    except KeyboardInterrupt:
        logger.info("\n🛑 Program sonlandırıldı")
    except Exception as e:
        logger.error(f"❌ Kritik hata: {e}")
        raise
