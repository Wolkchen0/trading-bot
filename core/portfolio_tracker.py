"""
Portfolio Tracker - Portföy ve performans takibi.
Günlük P&L, işlem geçmişi, win rate hesaplama.
"""
import json
import os
from datetime import datetime, date
from typing import Dict, List, Optional
from config import LOG_CONFIG
from utils.logger import logger


class PortfolioTracker:
    """Portföy ve performans takip sınıfı."""

    def __init__(self):
        self.history_file = LOG_CONFIG.get("trade_history_file", "trade_history.json")
        self.trades: List[Dict] = self._load_history()
        logger.info(f"PortfolioTracker başlatıldı - {len(self.trades)} geçmiş işlem")

    def _load_history(self) -> List[Dict]:
        """İşlem geçmişini dosyadan yükler."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        """İşlem geçmişini dosyaya kaydeder."""
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.trades, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Geçmiş kayıt hatası: {e}")

    def add_trade(self, trade: Dict):
        """Yeni bir işlem kaydeder."""
        trade["timestamp"] = datetime.now().isoformat()
        self.trades.append(trade)
        self._save_history()
        logger.info(
            f"📝 Trade eklendi: {trade.get('action', '?')} "
            f"{trade.get('qty', 0)} {trade.get('symbol', '?')} "
            f"@ ${trade.get('price', 0):.2f}"
        )

    def get_today_trades(self) -> List[Dict]:
        """Bugünkü işlemleri döndürür."""
        today = date.today().isoformat()
        return [
            t for t in self.trades
            if t.get("timestamp", "").startswith(today)
            or t.get("date", "") == today
        ]

    def get_overall_stats(self) -> Dict:
        """Genel performans istatistikleri."""
        if not self.trades:
            return self._empty_stats()

        closed_trades = [t for t in self.trades if "pnl" in t]
        if not closed_trades:
            return self._empty_stats()

        wins = [t for t in closed_trades if t["pnl"] > 0]
        losses = [t for t in closed_trades if t["pnl"] < 0]

        total = len(closed_trades)
        win_count = len(wins)
        loss_count = len(losses)

        total_pnl = sum(t["pnl"] for t in closed_trades)
        total_wins = sum(t["pnl"] for t in wins) if wins else 0
        total_losses = sum(t["pnl"] for t in losses) if losses else 0

        avg_win = total_wins / win_count if win_count > 0 else 0
        avg_loss = total_losses / loss_count if loss_count > 0 else 0

        # Profit factor
        profit_factor = (
            abs(total_wins / total_losses) if total_losses != 0 else float("inf")
        )

        # Max drawdown (basit hesaplama)
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in closed_trades:
            cumulative += t["pnl"]
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_count / total * 100, 1) if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_dd, 2),
            "expectancy": round(
                (win_count / total * avg_win + loss_count / total * avg_loss)
                if total > 0
                else 0,
                2,
            ),
        }

    def get_daily_pnl_history(self) -> List[Dict]:
        """Günlük P&L geçmişi."""
        from collections import defaultdict

        daily = defaultdict(float)
        for t in self.trades:
            d = t.get("date", t.get("timestamp", "")[:10])
            if d and "pnl" in t:
                daily[d] += t["pnl"]

        return [
            {"date": d, "pnl": round(p, 2)}
            for d, p in sorted(daily.items())
        ]

    def _empty_stats(self) -> Dict:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "expectancy": 0,
        }
