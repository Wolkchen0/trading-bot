"""
Compliance Module - ABD düzenleyici uyumluluk.
PDT kuralı takibi, Wash Sale tespiti, vergi raporu dışa aktarma.
"""
import csv
import json
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from utils.logger import logger


class PDTTracker:
    """
    Pattern Day Trader (PDT) kuralı takibi.

    ABD kuralları:
    - 5 iş günü içinde 4+ day trade → PDT statüsü
    - PDT statüsünde min $25,000 bakiye zorunlu
    - $25,000 altında: HAFTADA MAX 3 DAY TRADE

    Day trade = aynı gün alıp aynı gün satma
    Kripto için PDT kuralı GEÇERLİ DEĞİLDİR.
    """

    def __init__(self, account_equity: float, pdt_file: str = "pdt_tracker.json"):
        self.account_equity = account_equity
        self.pdt_file = pdt_file
        self.day_trades: List[Dict] = self._load()
        self.PDT_THRESHOLD = 25_000.0
        self.MAX_DAY_TRADES_UNDER_PDT = 3  # 5 günde max 3
        logger.info(
            f"PDTTracker başlatıldı - Bakiye: ${account_equity:,.2f} "
            f"({'PDT güvenli' if account_equity >= self.PDT_THRESHOLD else '⚠️ PDT LİMİTLİ'})"
        )

    def _load(self) -> List[Dict]:
        if os.path.exists(self.pdt_file):
            try:
                with open(self.pdt_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save(self):
        try:
            with open(self.pdt_file, "w") as f:
                json.dump(self.day_trades, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"PDT kayıt hatası: {e}")

    def record_day_trade(self, symbol: str, buy_time: str, sell_time: str):
        """Day trade kaydeder (aynı gün alış-satış)."""
        self.day_trades.append({
            "symbol": symbol,
            "buy_time": buy_time,
            "sell_time": sell_time,
            "date": date.today().isoformat(),
        })
        self._save()
        remaining = self.get_remaining_day_trades()
        logger.warning(
            f"📋 Day trade kaydedildi: {symbol} | "
            f"Kalan hak: {remaining} (bu hafta)"
        )

    def get_day_trades_rolling_window(self) -> int:
        """
        Dönen 5 iş günü penceresinde yapılan day trade sayısını hesaplar.
        NOT: Bu takvim haftası DEĞİL, rolling 5 business day'dir.
        Örn: Çarşamba günü yapılan işlem, sonraki Çarşamba'ya kadar pencerede kalır.
        """
        today = date.today()
        # Son 9 takvim gününe bak (5 iş günü ~ max 9 takvim günü, tatil dahil)
        lookback_start = today - timedelta(days=9)

        recent = []
        for t in self.day_trades:
            trade_date_str = t.get("date", "")
            if not trade_date_str:
                continue
            try:
                trade_date = date.fromisoformat(trade_date_str)
            except ValueError:
                continue

            if trade_date > today or trade_date < lookback_start:
                continue

            # trade_date ile today arasında kaç iş günü var?
            # numpy.busday_count kullanmak yerine manuel hesapla
            business_days = 0
            d = trade_date
            while d < today:
                d += timedelta(days=1)
                if d.weekday() < 5:  # Pazartesi=0 ... Cuma=4
                    business_days += 1

            # 5 iş günü içinde mi?
            if business_days <= 5:
                recent.append(t)

        return len(recent)

    def get_remaining_day_trades(self) -> int:
        """Kalan day trade hakkı (rolling 5 iş günü penceresi)."""
        if self.account_equity >= self.PDT_THRESHOLD:
            return 999  # Sınırsız
        used = self.get_day_trades_rolling_window()
        return max(0, self.MAX_DAY_TRADES_UNDER_PDT - used)

    def can_day_trade(self, asset_type: str = "stock") -> Tuple[bool, str]:
        """
        Day trade yapılıp yapılamayacağını kontrol eder.
        Kripto için PDT kuralı geçerli değildir.
        """
        # Kripto PDT'den muaf
        if asset_type == "crypto":
            return True, "✅ Kripto: PDT kuralı yok"

        # $25K üzerinde sınırsız
        if self.account_equity >= self.PDT_THRESHOLD:
            return True, "✅ PDT güvenli ($25K+)"

        # $25K altında: haftalık limit kontrol
        remaining = self.get_remaining_day_trades()
        if remaining > 0:
            return True, f"✅ Kalan day trade hakkı: {remaining}/3"
        else:
            return False, (
                f"⛔ PDT LİMİTİ: Bu hafta {self.MAX_DAY_TRADES_UNDER_PDT} "
                f"day trade hakkı doldu! Bakiye: ${self.account_equity:,.2f} "
                f"(min $25,000 gerekli)"
            )

    def update_equity(self, equity: float):
        self.account_equity = equity


class WashSaleTracker:
    """
    Wash Sale Rule takibi (IRS kuralı).

    Kural: Bir hisseyi zararına satıp, 30 gün içinde aynı hisseyi
    tekrar alırsan, o zararı vergiden düşemezsin.

    NOT: Kripto şu an Wash Sale'den muaf (ancak değişebilir).
    """

    def __init__(self, wash_file: str = "wash_sale_tracker.json"):
        self.wash_file = wash_file
        self.loss_sales: List[Dict] = self._load()
        self.WASH_SALE_WINDOW_DAYS = 30
        logger.info("WashSaleTracker başlatıldı")

    def _load(self) -> List[Dict]:
        if os.path.exists(self.wash_file):
            try:
                with open(self.wash_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save(self):
        try:
            with open(self.wash_file, "w") as f:
                json.dump(self.loss_sales, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Wash sale kayıt hatası: {e}")

    def record_loss_sale(self, symbol: str, loss_amount: float, sell_date: str):
        """Zararına satış kaydeder."""
        if loss_amount < 0:  # Zarar
            self.loss_sales.append({
                "symbol": symbol,
                "loss": loss_amount,
                "sell_date": sell_date,
                "wash_window_end": (
                    datetime.fromisoformat(sell_date) + timedelta(days=30)
                ).isoformat()[:10],
            })
            self._save()

    def check_wash_sale(self, symbol: str, asset_type: str = "stock") -> Tuple[bool, str]:
        """
        Wash sale riski kontrol eder.
        True = WASH SALE RİSKİ VAR (alım yapılMAMALI veya dikkat edilmeli)
        """
        # Kripto muaf (şimdilik)
        if asset_type == "crypto":
            return False, "✅ Kripto: Wash Sale muaf"

        today = date.today().isoformat()
        active_windows = [
            s for s in self.loss_sales
            if s["symbol"] == symbol
            and s.get("wash_window_end", "") >= today
        ]

        if active_windows:
            total_loss = sum(s["loss"] for s in active_windows)
            end_date = max(s["wash_window_end"] for s in active_windows)
            return True, (
                f"⚠️ WASH SALE RİSKİ: {symbol} son 30 günde zararına satıldı "
                f"(toplam: ${total_loss:,.2f}). {end_date} tarihine kadar "
                f"bu hisseyi alırsan zarar vergiden düşülemez!"
            )

        return False, "✅ Wash Sale riski yok"


class TaxExporter:
    """
    Vergi raporu dışa aktarma.
    TurboTax ve benzeri vergi yazılımlarına uygun CSV formatı.
    """

    @staticmethod
    def export_to_csv(
        trades: List[Dict],
        filename: str = "tax_report.csv",
        year: Optional[int] = None,
    ) -> str:
        """
        İşlem geçmişini vergi raporu formatında CSV'ye aktarır.
        TurboTax / H&R Block / CoinTracker uyumlu format.
        """
        if year is None:
            year = date.today().year

        # Yıla göre filtrele
        year_trades = [
            t for t in trades
            if t.get("timestamp", t.get("date", "")).startswith(str(year))
            or t.get("date", "").startswith(str(year))
        ]

        filepath = f"tax_report_{year}.csv"
        if filename:
            filepath = filename

        headers = [
            "Date",
            "Type",
            "Symbol",
            "Quantity",
            "Price",
            "Total Value",
            "Fee/Commission",
            "P&L",
            "Short/Long Term",
            "Holding Period",
            "Notes",
        ]

        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

                for t in year_trades:
                    trade_date = t.get("timestamp", t.get("date", ""))[:10]
                    trade_type = t.get("action", t.get("type", ""))
                    symbol = t.get("symbol", "")
                    qty = t.get("qty", t.get("shares", 0))
                    price = t.get("price", 0)
                    total = float(qty) * float(price) if qty and price else 0
                    fee = t.get("fee", 0)
                    pnl = t.get("pnl", "")
                    term = "Short-Term"  # Day trading = always short-term
                    notes = t.get("reason", t.get("strategy", ""))

                    writer.writerow([
                        trade_date,
                        trade_type,
                        symbol,
                        qty,
                        f"{float(price):.2f}" if price else "",
                        f"{total:.2f}" if total else "",
                        f"{float(fee):.4f}" if fee else "0",
                        f"{float(pnl):.2f}" if pnl != "" else "",
                        term,
                        "< 1 year",
                        notes,
                    ])

            logger.info(f"📄 Vergi raporu oluşturuldu: {filepath} ({len(year_trades)} işlem)")
            return filepath

        except Exception as e:
            logger.error(f"CSV export hatası: {e}")
            return ""

    @staticmethod
    def export_wash_sales(
        wash_sales: List[Dict],
        filename: str = "wash_sales_report.csv",
    ) -> str:
        """Wash sale kayıtlarını CSV'ye aktarır."""
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Symbol", "Loss Amount", "Sell Date", "Wash Window End"])
                for ws in wash_sales:
                    writer.writerow([
                        ws.get("symbol", ""),
                        ws.get("loss", 0),
                        ws.get("sell_date", ""),
                        ws.get("wash_window_end", ""),
                    ])
            logger.info(f"📄 Wash sale raporu: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Wash sale export hatası: {e}")
            return ""


# ============================================================
# API GÜVENLİK KONTROL LİSTESİ
# ============================================================
API_SECURITY_CHECKLIST = """
🔒 API GÜVENLİK KONTROL LİSTESİ
================================

✅ YAPILMASI GEREKENLER:
  1. API anahtarını SADECE "Read" + "Trade" yetkisiyle oluştur
  2. "Withdrawal" (Para Çekme) yetkisini KESİNLİKLE AÇMA
  3. IP whitelist kullan (sadece kendi sunucu IP'n)
  4. API anahtarını .env dosyasında tut, asla koda yapıştırma
  5. .env dosyasını .gitignore'a ekle
  6. API anahtarını düzenli olarak yenile (her 90 gün)

❌ YAPILMAMASI GEREKENLER:
  1. API anahtarını kimseyle paylaşma
  2. Withdrawal yetkisi açma
  3. API anahtarını GitHub'a yükleme
  4. Güvenilmeyen 3. parti servislere verme

🔑 BROKER BAZLI GÜVENLİK:
  Alpaca:  API Settings → Sadece Trading izni
  Binance.US: API Management → "Enable Spot Trading" 
              → "Enable Withdrawals" = KAPALI
  Coinbase: API Settings → "Trade" izni → "Transfer" = KAPALI
  Kraken: API Settings → "Query" + "Trade" → "Withdraw" = KAPALI

📍 SUNUCU LOKASYONU ÖNERİSİ:
  - AWS us-east-1 (Virginia) → NYSE/NASDAQ'a en yakın
  - Google Cloud us-east4 (Virginia)
  - Azure East US (Virginia)
  Bot'u yerel bilgisayarda çalıştırmak da olur ama
  canlı scalping için gecikme (latency) fark yaratır.
"""


def print_security_checklist():
    """Güvenlik kontrol listesini yazdırır."""
    print(API_SECURITY_CHECKLIST)
    logger.info("🔒 API güvenlik kontrol listesi gösterildi")
