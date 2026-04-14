"""
Notifier — Telegram Bildirim Sistemi

Trade gerçekleştiğinde, KillSwitch tetiklendiğinde, günlük özet,
ve önemli olaylarda anlık Telegram bildirimi gönderir.

Kurulum:
  1. @BotFather'dan bot oluştur → TELEGRAM_BOT_TOKEN al
  2. Botu gruba/kanala ekle veya kendine mesaj at
  3. @userinfobot'tan TELEGRAM_CHAT_ID al
  4. .env dosyasına ekle:
     TELEGRAM_BOT_TOKEN=xxx
     TELEGRAM_CHAT_ID=xxx
"""
import os
import requests
from datetime import datetime
from typing import Dict, Optional
from utils.logger import logger


class TelegramNotifier:
    """Telegram bildirim gönderici."""

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.bot_token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

        if self.enabled:
            logger.info("📱 TelegramNotifier aktif")
        else:
            logger.info("📱 TelegramNotifier devre dışı (TELEGRAM_BOT_TOKEN/.CHAT_ID yok)")

    def _send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Telegram mesajı gönder."""
        if not self.enabled:
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
            else:
                logger.debug(f"Telegram hata: {response.status_code}")
                return False
        except Exception as e:
            logger.debug(f"Telegram gönderim hatası: {e}")
            return False

    # ============================================================
    # TİCARET BİLDİRİMLERİ
    # ============================================================

    def notify_buy(self, symbol: str, qty: float, price: float,
                   confidence: int, reasons: list):
        """Alım bildirimi."""
        text = (
            f"🟢 <b>ALIŞ: {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Adet: {qty:.4f} | Fiyat: ${price:,.2f}\n"
            f"💰 Toplam: ${qty * price:,.2f}\n"
            f"🎯 Güven: %{confidence}\n"
            f"📝 Nedenler: {', '.join(reasons[:3])}\n"
            f"🕒 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._send(text)

    def notify_sell(self, symbol: str, reason: str,
                    pnl: float = 0, pnl_pct: float = 0):
        """Satış bildirimi."""
        emoji = "🔴" if pnl < 0 else "🟢"
        pnl_emoji = "📉" if pnl < 0 else "📈"

        text = (
            f"{emoji} <b>SATIŞ: {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            f"📝 Sebep: {reason}\n"
            f"🕒 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._send(text)

    def notify_kill_switch(self, reason: str, equity: float):
        """KillSwitch tetiklenme bildirimi."""
        text = (
            f"🚨🚨🚨 <b>KILL SWITCH TETİKLENDİ</b> 🚨🚨🚨\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ Sebep: {reason}\n"
            f"💰 Bakiye: ${equity:,.2f}\n"
            f"📋 Tüm pozisyonlar kapatılıyor!\n"
            f"🕒 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._send(text)

    def notify_daily_summary(self, equity: float, pnl: float,
                              trades_count: int, positions: dict,
                              wins: int = 0, losses: int = 0):
        """Günlük özet bildirimi."""
        pnl_pct = (pnl / max(equity - pnl, 1)) * 100
        emoji = "📈" if pnl >= 0 else "📉"

        pos_text = ""
        if positions:
            pos_lines = []
            for sym, data in positions.items():
                entry = data.get("entry_price", 0)
                pos_lines.append(f"  • {sym} @ ${entry:,.2f}")
            pos_text = "\n".join(pos_lines)
        else:
            pos_text = "  Yok"

        text = (
            f"{emoji} <b>GÜNLÜK ÖZET</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye: ${equity:,.2f}\n"
            f"📊 P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            f"📋 İşlem: {trades_count} (✅{wins} / ❌{losses})\n"
            f"📌 Açık Pozisyonlar:\n{pos_text}\n"
            f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self._send(text)

    def notify_error(self, error_msg: str):
        """Kritik hata bildirimi."""
        text = (
            f"⚠️ <b>HATA</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{error_msg[:500]}\n"
            f"🕒 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._send(text)

    def notify_pdt_warning(self, remaining: int):
        """PDT limiti uyarısı."""
        text = (
            f"⚠️ <b>PDT UYARISI</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Kalan day trade hakkı: {remaining}/2\n"
            f"Dikkat: Hakkın dolduğunda gün içi satış engellenecek!"
        )
        self._send(text)

    def send_message(self, text: str) -> bool:
        """Genel amaçlı mesaj gönder (short executor, özel bildirimler vb.)."""
        return self._send(text)
