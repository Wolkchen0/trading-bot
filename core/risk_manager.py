"""
Risk Manager - Pozisyon büyüklüğü, stop-loss, günlük limit yönetimi.
Trading'in en kritik modülü — sermayeyi korur.
"""
import json
import os
from datetime import datetime, date
from typing import Dict, Optional, List
from config import RISK_CONFIG, COMMISSION_CONFIG, LOG_CONFIG
from utils.logger import logger


class RiskManager:
    """Risk yönetimi sınıfı."""

    def __init__(self, account_equity: float):
        self.config = RISK_CONFIG
        self.fee_config = COMMISSION_CONFIG
        self.account_equity = account_equity
        self.daily_pnl = 0.0
        self.daily_fees = 0.0  # Günlük toplam ödenen komisyon
        self.open_positions_count = 0
        self.trades_today: List[Dict] = []
        self.today = date.today().isoformat()
        logger.info(f"RiskManager başlatıldı - Sermaye: ${account_equity:,.2f}")

    def update_equity(self, equity: float):
        """Hesap bakiyesini günceller."""
        self.account_equity = equity

    def update_daily_pnl(self, pnl: float):
        """Günlük P&L'i günceller."""
        self.daily_pnl = pnl

    def update_positions_count(self, count: int):
        """Açık pozisyon sayısını günceller."""
        self.open_positions_count = count

    # ============================================================
    # TRADE ÖNCESİ KONTROLLER
    # ============================================================

    def can_trade(self) -> tuple[bool, str]:
        """Trade yapılıp yapılamayacağını kontrol eder."""
        # Günlük kayıp limiti kontrolü
        max_daily_loss = self.account_equity * self.config["max_daily_loss_pct"]
        if self.daily_pnl <= -max_daily_loss:
            msg = (
                f"⛔ GÜNLÜK KAYIP LİMİTİ: ${self.daily_pnl:.2f} "
                f"(limit: -${max_daily_loss:.2f})"
            )
            logger.warning(msg)
            return False, msg

        # Max pozisyon sayısı kontrolü
        if self.open_positions_count >= self.config["max_open_positions"]:
            msg = (
                f"⛔ MAX POZİSYON: {self.open_positions_count} "
                f"(limit: {self.config['max_open_positions']})"
            )
            logger.warning(msg)
            return False, msg

        return True, "✅ Trade yapılabilir"

    def calculate_position_size(
        self, entry_price: float, stop_loss_price: float
    ) -> Dict:
        """
        Risk bazlı pozisyon büyüklüğü hesaplar.
        Tek trade'de max %1 risk kuralı uygulanır.
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            return {"shares": 0, "error": "Geçersiz fiyatlar"}

        # Risk miktarı (sermayenin %1'i)
        max_risk_amount = self.account_equity * self.config["max_risk_per_trade_pct"]

        # Hisse başına risk
        risk_per_share = abs(entry_price - stop_loss_price)

        if risk_per_share <= 0:
            return {"shares": 0, "error": "Stop-loss giriş fiyatına çok yakın"}

        # Hisse sayısı
        shares = int(max_risk_amount / risk_per_share)

        # Max pozisyon büyüklüğü kontrolü (sermayenin %20'si)
        max_position_value = self.account_equity * self.config["max_position_size_pct"]
        max_shares_by_value = int(max_position_value / entry_price)
        shares = min(shares, max_shares_by_value)

        # Minimum 1 hisse
        shares = max(shares, 1) if shares > 0 else 0

        position_value = shares * entry_price
        actual_risk = shares * risk_per_share

        # Komisyon hesapla (gidiş-dönüş: alış + satış)
        fees = self.calculate_round_trip_fees(entry_price, shares)

        # Beklenen kâr komisyonu karşılıyor mu?
        expected_profit = shares * risk_per_share * self.config["risk_reward_ratio"]
        if self.fee_config["min_profit_after_fees"] and expected_profit <= fees["total_round_trip"]:
            logger.warning(
                f"⚠️ Komisyon kontrolü: Beklenen kâr (${expected_profit:.2f}) "
                f"komisyonu karşılamıyor (${fees['total_round_trip']:.2f}). "
                f"İşlem atlanıyor."
            )
            return {"shares": 0, "error": "Komisyon kârdan yüksek"}

        result = {
            "shares": shares,
            "entry_price": entry_price,
            "stop_loss": stop_loss_price,
            "position_value": round(position_value, 2),
            "risk_amount": round(actual_risk, 2),
            "risk_pct": round((actual_risk / self.account_equity) * 100, 2),
            "risk_per_share": round(risk_per_share, 2),
            "fees": fees,
        }

        logger.info(
            f"📊 Pozisyon: {shares} hisse @ ${entry_price:.2f} "
            f"| SL: ${stop_loss_price:.2f} "
            f"| Risk: ${actual_risk:.2f} ({result['risk_pct']:.1f}%) "
            f"| Fee: ${fees['total_round_trip']:.4f}"
        )

        return result

    def calculate_take_profit(
        self, entry_price: float, stop_loss_price: float
    ) -> float:
        """Risk/Ödül oranına göre take-profit hesaplar."""
        risk = abs(entry_price - stop_loss_price)
        rr = self.config["risk_reward_ratio"]

        if entry_price > stop_loss_price:  # Long
            take_profit = entry_price + (risk * rr)
        else:  # Short
            take_profit = entry_price - (risk * rr)

        return round(take_profit, 2)

    def calculate_trailing_stop(
        self, entry_price: float, current_price: float, highest_price: float
    ) -> float:
        """Trailing stop hesaplar."""
        trail_pct = self.config["trailing_stop_pct"]

        if current_price > entry_price:
            # Kârdayken trailing stop aktif
            trail_price = highest_price * (1 - trail_pct)
            return round(trail_price, 2)
        else:
            # Zarardayken orijinal stop-loss kullan
            return 0.0

    def check_signal_confidence(self, confidence: float) -> bool:
        """Sinyal güven puanını kontrol eder."""
        min_conf = self.config["min_confidence_score"]
        if confidence < min_conf:
            logger.info(
                f"⚠️ Düşük güven puanı: {confidence:.2f} (min: {min_conf})"
            )
            return False
        return True

    # ============================================================
    # KOMİSYON HESAPLAMA
    # ============================================================

    def calculate_round_trip_fees(
        self, price: float, shares: int, asset_type: str = "stock"
    ) -> Dict:
        """
        Gidiş-dönüş (alış+satış) toplam komisyon hesaplar.
        Her "AL" dediğinde satış komisyonunu da dahil eder.
        """
        if asset_type == "crypto":
            # Kripto: alış ve satış için yüzde bazlı
            buy_fee = price * shares * self.fee_config["crypto_taker_fee_pct"]
            sell_fee = price * shares * self.fee_config["crypto_taker_fee_pct"]
        else:
            # Hisse senedi
            position_value = price * shares

            # Alış komisyonu
            buy_fee_per_share = self.fee_config["stock_commission_per_share"] * shares
            buy_fee_pct = position_value * self.fee_config["stock_commission_pct"]
            buy_fee = max(buy_fee_per_share + buy_fee_pct, self.fee_config["stock_min_commission"])

            # Satış komisyonu (aynı) + SEC fee + FINRA TAF
            sell_fee_per_share = self.fee_config["stock_commission_per_share"] * shares
            sell_fee_pct = position_value * self.fee_config["stock_commission_pct"]
            sec_fee = position_value * self.fee_config["sec_fee_per_dollar"]
            finra_taf = min(shares * self.fee_config["finra_taf_per_share"], 8.30)
            sell_fee = max(sell_fee_per_share + sell_fee_pct, self.fee_config["stock_min_commission"]) + sec_fee + finra_taf

        # Slippage tahmini (gidiş-dönüş)
        slippage = price * shares * self.fee_config["estimated_slippage_pct"] * 2

        total = buy_fee + sell_fee + slippage

        return {
            "buy_fee": round(buy_fee, 4),
            "sell_fee": round(sell_fee, 4),
            "slippage": round(slippage, 4),
            "total_round_trip": round(total, 4),
            "fee_per_share": round(total / shares, 6) if shares > 0 else 0,
        }

    def get_daily_fees(self) -> float:
        """Bugün ödenen toplam komisyon."""
        return self.daily_fees

    def add_fee(self, fee_amount: float):
        """Günlük komisyon toplamına ekler."""
        self.daily_fees += fee_amount

    # ============================================================
    # TRADE KAYIT
    # ============================================================

    def record_trade(self, trade_data: Dict):
        """İşlemi kayıt altına alır."""
        trade_data["timestamp"] = datetime.now().isoformat()
        trade_data["date"] = self.today
        self.trades_today.append(trade_data)

        # JSON dosyasına kaydet
        history_file = LOG_CONFIG.get("trade_history_file", "trade_history.json")
        try:
            history = []
            if os.path.exists(history_file):
                with open(history_file, "r") as f:
                    history = json.load(f)
            history.append(trade_data)
            with open(history_file, "w") as f:
                json.dump(history, f, indent=2, default=str)
            logger.info(f"📝 Trade kaydedildi: {trade_data.get('symbol', '?')}")
        except Exception as e:
            logger.error(f"Trade kayıt hatası: {e}")

    def get_daily_stats(self) -> Dict:
        """Günlük istatistikleri döndürür."""
        if not self.trades_today:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_win": 0,
                "avg_loss": 0,
            }

        wins = [t for t in self.trades_today if t.get("pnl", 0) > 0]
        losses = [t for t in self.trades_today if t.get("pnl", 0) < 0]

        total_trades = len(self.trades_today)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(t.get("pnl", 0) for t in self.trades_today)
        avg_win = (
            sum(t.get("pnl", 0) for t in wins) / win_count if win_count > 0 else 0
        )
        avg_loss = (
            sum(t.get("pnl", 0) for t in losses) / loss_count
            if loss_count > 0
            else 0
        )

        return {
            "total_trades": total_trades,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
        }
