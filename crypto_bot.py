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
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Proje kök dizinini ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands, AverageTrueRange

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, StopOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from utils.logger import logger
from core.news_analyzer import NewsAnalyzer

# ============================================================
# KONFİGÜRASYON — $100 BÜTÇEYE ÖZEL
# ============================================================
CRYPTO_CONFIG = {
    # İşlem yapılacak coinler — 20 coin! (Alpaca formatı)
    "symbols": [
        # Büyük piyasa hacmi
        "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
        # Altcoinler (yüksek volatilite = daha fazla fırsat)
        "DOGE/USD", "SHIB/USD", "PEPE/USD", "BONK/USD",
        # DeFi tokenleri
        "LINK/USD", "UNI/USD", "AAVE/USD", "AVAX/USD",
        # Diğer popüler coinler
        "DOT/USD", "LTC/USD", "ADA/USD", "ARB/USD",
        "RENDER/USD", "TRUMP/USD", "ONDO/USD", "WIF/USD",
    ],

    # Risk yönetimi
    "max_risk_per_trade_pct": 0.02,     # %2 risk (küçük sermaye için)
    "max_position_pct": 0.35,           # Tek pozisyon max %35
    "max_open_positions": 3,            # Max 3 pozisyon (daha fazla çeşitlilik)
    "stop_loss_pct": 0.03,              # %3 stop-loss
    "take_profit_pct": 0.05,            # %5 take-profit
    "trailing_stop_pct": 0.025,         # %2.5 trailing stop

    # Sinyal parametreleri
    "rsi_oversold": 35,                 # RSI alış sinyali
    "rsi_overbought": 70,              # RSI satış sinyali
    "bb_proximity_pct": 0.02,          # BB alt bant yakınlık %2

    # Komisyon (Alpaca kripto)
    "commission_pct": 0.0025,           # Alpaca kripto komisyonu %0.25

    # Zamanlama
    "scan_interval_seconds": 30,        # Her 30 saniyede tara (kripto icin hizli)
    "min_trade_interval_minutes": 10,   # Min 10 dakika arayla islem

    # Kill switch
    "max_daily_loss_pct": 0.05,         # %5 günlük kayıp → dur
    "max_consecutive_errors": 3,        # 3 hata → dur
}


class CryptoBot:
    """$100 bütçeli kripto trading botu."""

    def __init__(self, live: bool = False):
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")

        if not self.api_key or not self.secret_key:
            logger.error("API key bulunamadi! .env dosyasini kontrol edin.")
            sys.exit(1)

        self.is_paper = not live
        self.client = TradingClient(self.api_key, self.secret_key, paper=self.is_paper)
        self.crypto_data = CryptoHistoricalDataClient()

        # Hesap bilgisi
        account = self.client.get_account()
        self.equity = float(account.equity)
        self.starting_equity = self.equity
        self.cash = float(account.cash)

        # Durum
        self.running = True
        self.consecutive_errors = 0
        self.daily_pnl = 0.0
        self.trades_today = []
        self.last_trade_time = {}
        self.positions = {}

        # Haber analiz modülü
        self.news = NewsAnalyzer()

        # Loglama
        mode = "PAPER" if self.is_paper else "LIVE"
        logger.info("=" * 60)
        logger.info(f"  KRIPTO TRADING BOT BASLATILDI [{mode}]")
        logger.info(f"  Bakiye: ${self.equity:,.2f}")
        logger.info(f"  Coinler: {', '.join(CRYPTO_CONFIG['symbols'])}")
        logger.info(f"  Max pozisyon: {CRYPTO_CONFIG['max_open_positions']}")
        logger.info(f"  Stop-loss: {CRYPTO_CONFIG['stop_loss_pct']:.0%}")
        logger.info(f"  Take-profit: {CRYPTO_CONFIG['take_profit_pct']:.0%}")
        logger.info("=" * 60)

        if not self.is_paper:
            logger.warning("!!! GERCEK PARA MODU AKTIF !!!")
            logger.warning(f"!!! Bakiye: ${self.equity:,.2f} !!!")
            logger.warning("!!! 10 saniye icinde basliyor... Ctrl+C ile iptal !!!")
            time.sleep(10)

    # ============================================================
    # VERİ ÇEKME
    # ============================================================

    def get_crypto_bars(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """Alpaca'dan kripto bar verisi çeker."""
        try:
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Hour,
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
            # Fallback: yfinance
            return self._get_yfinance_data(symbol)

    def _get_yfinance_data(self, symbol: str) -> pd.DataFrame:
        """yfinance fallback veri kaynağı."""
        try:
            yf_symbol = symbol.replace("/", "-")
            df = yf.download(yf_symbol, period="1mo", interval="1h", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            logger.error(f"{symbol} yfinance verisi cekilemedi: {e}")
            return pd.DataFrame()

    # ============================================================
    # TEKNİK ANALİZ
    # ============================================================

    def analyze(self, df: pd.DataFrame) -> Dict:
        """Teknik göstergeleri hesaplar ve sinyal üretir."""
        if len(df) < 30:
            return {"signal": "HOLD", "confidence": 0, "reason": "Yetersiz veri"}

        close = df["close"]

        # RSI
        rsi = RSIIndicator(close, window=14).rsi().iloc[-1]

        # EMA
        ema_9 = EMAIndicator(close, window=9).ema_indicator().iloc[-1]
        ema_21 = EMAIndicator(close, window=21).ema_indicator().iloc[-1]

        # MACD
        macd = MACD(close)
        macd_hist = macd.macd_diff().iloc[-1]
        prev_macd_hist = macd.macd_diff().iloc[-2]

        # Bollinger Bands
        bb = BollingerBands(close, window=20, window_dev=2)
        bb_lower = bb.bollinger_lband().iloc[-1]
        bb_upper = bb.bollinger_hband().iloc[-1]

        # ATR
        atr = AverageTrueRange(
            df["high"], df["low"], df["close"], window=14
        ).average_true_range().iloc[-1]

        current_price = close.iloc[-1]
        confidence = 0
        reasons = []

        # === BUY SİNYALLERİ ===
        buy_score = 0

        # RSI oversold
        if rsi < CRYPTO_CONFIG["rsi_oversold"]:
            buy_score += 30
            reasons.append(f"RSI={rsi:.0f} (oversold)")

        # EMA crossover (fast > slow)
        if ema_9 > ema_21:
            buy_score += 20
            reasons.append("EMA9>EMA21")

        # MACD histogram pozitif dönüş
        if macd_hist > 0 and prev_macd_hist <= 0:
            buy_score += 25
            reasons.append("MACD pozitif donen")

        # BB alt bant yakınlık
        if current_price < bb_lower * (1 + CRYPTO_CONFIG["bb_proximity_pct"]):
            buy_score += 25
            reasons.append("BB alt bant")

        # === SELL SİNYALLERİ ===
        sell_score = 0

        if rsi > CRYPTO_CONFIG["rsi_overbought"]:
            sell_score += 30
            reasons.append(f"RSI={rsi:.0f} (overbought)")

        if ema_9 < ema_21:
            sell_score += 20

        if macd_hist < 0 and prev_macd_hist >= 0:
            sell_score += 25
            reasons.append("MACD negatif donen")

        if current_price > bb_upper:
            sell_score += 25
            reasons.append("BB ust bant")

        # Karar
        if buy_score >= 50:
            signal = "BUY"
            confidence = min(buy_score, 100)
        elif sell_score >= 50:
            signal = "SELL"
            confidence = min(sell_score, 100)
        else:
            signal = "HOLD"
            confidence = 0

        return {
            "signal": signal,
            "confidence": confidence,
            "reasons": reasons,
            "price": current_price,
            "rsi": rsi,
            "ema_9": ema_9,
            "ema_21": ema_21,
            "macd_hist": macd_hist,
            "atr": atr,
            "bb_lower": bb_lower,
            "bb_upper": bb_upper,
        }

    def analyze_with_news(self, df, symbol: str) -> Dict:
        """Teknik analiz + haber analizi birleştir."""
        # Teknik analiz
        tech = self.analyze(df)

        # Haber analizi
        try:
            news_data = self.news.get_coin_sentiment(symbol)
            news_score = news_data["news_score"]
            news_signal = news_data["news_signal"]

            # Haber skorunu teknik analize ekle
            # Pozitif haber → BUY güvenini artır
            # Negatif haber → BUY güvenini düşür / SELL güvenini artır
            if tech["signal"] == "BUY":
                if news_score >= 10:
                    tech["confidence"] = min(tech["confidence"] + 15, 100)
                    tech["reasons"].append(f"Haber: POZITIF ({news_score})")
                elif news_score <= -20:
                    tech["confidence"] = max(tech["confidence"] - 25, 0)
                    tech["reasons"].append(f"Haber: NEGATIF ({news_score}) - DIKKAT!")
                    if tech["confidence"] < 50:
                        tech["signal"] = "HOLD"
                        tech["reasons"].append("Haberler nedeniyle BUY iptal")

            elif tech["signal"] == "HOLD" and news_score >= 30:
                # Çok pozitif haber → BUY'a çevir
                tech["signal"] = "BUY"
                tech["confidence"] = 55
                tech["reasons"].append(f"HABER TETIKLEDI: Cok pozitif ({news_score})")

            elif tech["signal"] == "HOLD" and news_score <= -30:
                # Çok negatif haber → Pozisyon varsa SELL sinyali
                tech["signal"] = "SELL"
                tech["confidence"] = 55
                tech["reasons"].append(f"HABER TETIKLEDI: Cok negatif ({news_score})")

            # Haber verilerini ekle
            tech["news_score"] = news_score
            tech["news_signal"] = news_signal
            tech["fear_greed"] = news_data["fear_greed"]
            tech["news_count"] = news_data["relevant_news_count"]

        except Exception as e:
            logger.debug(f"Haber analizi hatasi {symbol}: {e}")
            tech["news_score"] = 0
            tech["news_signal"] = "NEUTRAL"

        return tech

    # ============================================================
    # EMİR YÖNETIMI
    # ============================================================

    def execute_buy(self, symbol: str, analysis: Dict) -> bool:
        """Alış emri gönderir."""
        try:
            # Pozisyon boyutu hesapla
            account = self.client.get_account()
            cash = float(account.cash)
            max_invest = cash * CRYPTO_CONFIG["max_position_pct"]

            if max_invest < 1:
                logger.warning(f"Yetersiz bakiye: ${cash:.2f}")
                return False

            price = analysis["price"]
            commission = max_invest * CRYPTO_CONFIG["commission_pct"]
            invest_after_fee = max_invest - commission

            # Kripto miktarı (fractional)
            qty = round(invest_after_fee / price, 8)

            if qty * price < 1:
                logger.warning(f"Cok kucuk islem: ${qty * price:.2f}")
                return False

            # Emir gönder
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC,
            )
            order = self.client.submit_order(request)

            logger.info(
                f"  BUY {symbol}: {qty:.6f} @ ${price:,.2f} "
                f"(${qty * price:,.2f}) | Fee: ${commission:.2f} "
                f"| {', '.join(analysis['reasons'])}"
            )

            # SUNUCU TARAFLI STOP-LOSS (bot offline olsa bile calısır!)
            stop_price = round(price * (1 - CRYPTO_CONFIG['stop_loss_pct']), 6)
            try:
                sl_request = StopOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    stop_price=stop_price,
                )
                sl_order = self.client.submit_order(sl_request)
                logger.info(
                    f"  STOP-LOSS yerlestirildi: {symbol} @ ${stop_price:,.4f} "
                    f"(sunucu tarafli, bot kapansa bile calisir)"
                )
            except Exception as sl_err:
                logger.warning(f"  Stop-loss emri gonderilemedi: {sl_err}")

            # Kaydet
            self.positions[symbol] = {
                "entry_price": price,
                "qty": qty,
                "entry_time": datetime.now().isoformat(),
                "order_id": str(order.id),
                "stop_loss_price": stop_price,
            }
            self.last_trade_time[symbol] = datetime.now()
            self.trades_today.append({
                "action": "BUY", "symbol": symbol, "price": price,
                "qty": qty, "time": datetime.now().isoformat(),
            })
            self.consecutive_errors = 0
            return True

        except Exception as e:
            logger.error(f"BUY hatasi {symbol}: {e}")
            self.consecutive_errors += 1
            return False

    def execute_sell(self, symbol: str, reason: str) -> bool:
        """Satış emri gönderir."""
        try:
            # Önce bekleyen stop-loss emirlerini iptal et
            try:
                orders = self.client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN)
                )
                for o in orders:
                    if o.symbol == symbol.replace('/', '') and o.side == OrderSide.SELL:
                        self.client.cancel_order_by_id(o.id)
                        logger.debug(f"  Eski stop-loss iptal: {o.id}")
            except Exception:
                pass

            # Pozisyonu kapat
            self.client.close_position(symbol.replace("/", ""))

            pos = self.positions.get(symbol, {})
            entry = pos.get("entry_price", 0)
            qty = pos.get("qty", 0)

            logger.info(
                f"  SELL {symbol}: {qty:.6f} | Sebep: {reason}"
            )

            self.positions.pop(symbol, None)
            self.last_trade_time[symbol] = datetime.now()
            self.trades_today.append({
                "action": "SELL", "symbol": symbol,
                "reason": reason, "time": datetime.now().isoformat(),
            })
            self.consecutive_errors = 0
            return True

        except Exception as e:
            logger.error(f"SELL hatasi {symbol}: {e}")
            self.consecutive_errors += 1
            return False

    # ============================================================
    # POZİSYON YÖNETİMİ
    # ============================================================

    def manage_positions(self):
        """Açık pozisyonları kontrol et (stop-loss, take-profit)."""
        try:
            positions = self.client.get_all_positions()
        except Exception as e:
            logger.error(f"Pozisyon listesi alinamadi: {e}")
            self.consecutive_errors += 1
            return

        for pos in positions:
            symbol_clean = pos.symbol  # BTCUSD
            # Alpaca formatına çevir
            if "USD" in symbol_clean:
                symbol = symbol_clean[:-3] + "/" + symbol_clean[-3:]  # BTC/USD
            else:
                symbol = symbol_clean

            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            pnl_pct = (current_price - entry_price) / entry_price

            # Take profit
            if pnl_pct >= CRYPTO_CONFIG["take_profit_pct"]:
                logger.info(
                    f"  TAKE PROFIT {symbol}: +{pnl_pct:.1%} "
                    f"(${float(pos.unrealized_pl):+.2f})"
                )
                self.execute_sell(symbol, f"TAKE_PROFIT (+{pnl_pct:.1%})")

            # Stop loss
            elif pnl_pct <= -CRYPTO_CONFIG["stop_loss_pct"]:
                logger.info(
                    f"  STOP LOSS {symbol}: {pnl_pct:.1%} "
                    f"(${float(pos.unrealized_pl):+.2f})"
                )
                self.execute_sell(symbol, f"STOP_LOSS ({pnl_pct:.1%})")

    # ============================================================
    # ANA DÖNGÜ
    # ============================================================

    def run(self):
        """Ana trading döngüsü — 7/24 çalışır."""
        logger.info("\nBot calisma moduna gecti...\n")

        while self.running:
            try:
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
                account = self.client.get_account()
                self.equity = float(account.equity)
                self.cash = float(account.cash)
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

                # Açık pozisyon sayısını kontrol et
                open_positions = self.client.get_all_positions()
                open_count = len(open_positions)

                # Her coin'i analiz et
                for symbol in CRYPTO_CONFIG["symbols"]:
                    # Min işlem aralığı kontrolü
                    last_time = self.last_trade_time.get(symbol)
                    if last_time:
                        elapsed = (datetime.now() - last_time).total_seconds() / 60
                        if elapsed < CRYPTO_CONFIG["min_trade_interval_minutes"]:
                            continue

                    # Veri çek & analiz et (TEKNİK + HABER)
                    df = self.get_crypto_bars(symbol, days=14)
                    if df.empty or len(df) < 30:
                        continue

                    analysis = self.analyze_with_news(df, symbol)

                    # BUY sinyali
                    if (
                        analysis["signal"] == "BUY"
                        and analysis["confidence"] >= 50
                        and open_count < CRYPTO_CONFIG["max_open_positions"]
                        and symbol not in [p.symbol.replace("USD", "/USD") for p in open_positions]
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

                # Durum raporu
                self._print_status()

                # Bekleme
                interval = CRYPTO_CONFIG["scan_interval_seconds"]
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
        client = TradingClient(
            os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True
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
