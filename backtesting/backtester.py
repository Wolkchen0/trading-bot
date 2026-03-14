"""
Backtester - Geçmiş verilerle strateji testi.
Win rate, P&L, max drawdown, Sharpe ratio hesaplama.
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional
from core.data_fetcher import DataFetcher
from core.technical_analysis import TechnicalAnalysis
from strategies.multi_strategy import MultiStrategy
from core.signal_generator import SignalType
from config import RISK_CONFIG, COMMISSION_CONFIG
from utils.logger import logger


class Backtester:
    """Strateji backtesting motoru."""

    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.ta = TechnicalAnalysis()
        self.strategy = MultiStrategy()
        logger.info(f"Backtester başlatıldı - Başlangıç: ${initial_capital:,.2f}")

    def run(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> Dict:
        """
        Bir hisse üzerinde backtest çalıştırır.

        Args:
            symbol: Hisse kodu (ör: "AAPL")
            period: Veri periyodu ("1mo", "3mo", "6mo", "1y")
            interval: Bar aralığı ("1d", "1h")

        Returns:
            Backtest sonuçları (P&L, win rate, drawdown vb.)
        """
        logger.info(f"📊 Backtest başlıyor: {symbol} ({period}, {interval})")

        # Veri çek (yfinance)
        fetcher = DataFetcher()
        df = fetcher.get_historical_yfinance(symbol, period, interval)

        if df.empty or len(df) < 50:
            logger.error(f"Yetersiz veri: {symbol}")
            return {"error": "Yetersiz veri"}

        # Teknik analiz hesapla
        df = self.ta.calculate_all(df)

        # Simülasyon
        capital = self.initial_capital
        position = 0  # Hisse adedi
        entry_price = 0.0
        trades = []
        equity_curve = []
        total_fees = 0.0  # Toplam ödenen komisyon
        max_risk_pct = RISK_CONFIG["max_risk_per_trade_pct"]
        rr_ratio = RISK_CONFIG["risk_reward_ratio"]
        slippage_pct = COMMISSION_CONFIG["estimated_slippage_pct"]
        stock_comm_per_share = COMMISSION_CONFIG["stock_commission_per_share"]
        stock_comm_pct = COMMISSION_CONFIG["stock_commission_pct"]
        sec_fee = COMMISSION_CONFIG["sec_fee_per_dollar"]
        finra_taf = COMMISSION_CONFIG["finra_taf_per_share"]

        for i in range(50, len(df)):
            current_bar = df.iloc[i]
            prev_bar = df.iloc[i - 1]
            close = float(current_bar["close"])

            # Sinyal verisi oluştur
            signal_data = self.ta.get_signal_data(df.iloc[: i + 1])
            if not signal_data:
                equity_curve.append(capital + position * close)
                continue

            # Strateji analizi
            final_signal = self.strategy.analyze(signal_data)

            # ============ BUY ============
            if (
                final_signal.signal_type == SignalType.BUY
                and position == 0
                and final_signal.confidence >= 0.5
            ):
                atr = signal_data.get("atr", close * 0.02)
                stop_loss = close - (atr * 1.5)
                risk_per_share = close - stop_loss
                take_profit = close + (risk_per_share * rr_ratio)

                if risk_per_share > 0:
                    max_risk = capital * max_risk_pct
                    shares = int(max_risk / risk_per_share)
                    shares = min(shares, int(capital * 0.2 / close))  # max %20
                    shares = max(shares, 1)

                    if shares * close <= capital:
                        # Alış komisyonu hesapla
                        buy_fee = max(
                            stock_comm_per_share * shares + close * shares * stock_comm_pct,
                            COMMISSION_CONFIG["stock_min_commission"]
                        )
                        buy_slippage = close * shares * slippage_pct
                        buy_total_cost = shares * close + buy_fee + buy_slippage

                        if buy_total_cost <= capital:
                            position = shares
                            entry_price = close
                            capital -= buy_total_cost
                            total_fees += buy_fee + buy_slippage

                            trades.append({
                                "type": "BUY",
                                "date": str(df.index[i]),
                                "price": close,
                                "shares": shares,
                                "stop_loss": round(stop_loss, 2),
                                "take_profit": round(take_profit, 2),
                                "confidence": round(final_signal.confidence, 2),
                                "fee": round(buy_fee + buy_slippage, 4),
                            })

            # ============ SELL ============
            elif position > 0:
                last_buy = trades[-1] if trades else {}
                stop_loss = last_buy.get("stop_loss", entry_price * 0.95)
                take_profit = last_buy.get("take_profit", entry_price * 1.10)

                should_sell = False
                sell_reason = ""

                # Stop-loss vurdu
                if close <= stop_loss:
                    should_sell = True
                    sell_reason = "Stop-Loss"
                # Take-profit vurdu
                elif close >= take_profit:
                    should_sell = True
                    sell_reason = "Take-Profit"
                # Strateji SAT diyor
                elif (
                    final_signal.signal_type == SignalType.SELL
                    and final_signal.confidence >= 0.5
                ):
                    should_sell = True
                    sell_reason = "Strateji"

                if should_sell:
                    # Satış komisyonu hesapla
                    sell_value = position * close
                    sell_fee = max(
                        stock_comm_per_share * position + sell_value * stock_comm_pct,
                        COMMISSION_CONFIG["stock_min_commission"]
                    )
                    sell_fee += sell_value * sec_fee  # SEC fee
                    sell_fee += min(position * finra_taf, 8.30)  # FINRA TAF
                    sell_slippage = sell_value * slippage_pct
                    sell_net = sell_value - sell_fee - sell_slippage

                    pnl = sell_net - (entry_price * position)
                    capital += sell_net
                    total_fees += sell_fee + sell_slippage

                    trades.append({
                        "type": "SELL",
                        "date": str(df.index[i]),
                        "price": close,
                        "shares": position,
                        "pnl": round(pnl, 2),
                        "pnl_pct": round((close / entry_price - 1) * 100, 2),
                        "reason": sell_reason,
                        "fee": round(sell_fee + sell_slippage, 4),
                    })

                    position = 0
                    entry_price = 0

            equity_curve.append(capital + position * close)

        # Eğer hâlâ pozisyondaysa, son fiyattan kapat
        if position > 0:
            final_price = float(df.iloc[-1]["close"])
            pnl = (final_price - entry_price) * position
            capital += position * final_price
            trades.append({
                "type": "SELL",
                "date": str(df.index[-1]),
                "price": final_price,
                "shares": position,
                "pnl": round(pnl, 2),
                "reason": "Periyot Sonu",
            })
            position = 0

        # ============ SONUÇLARI HESAPLA ============
        results = self._calculate_results(trades, equity_curve, symbol, total_fees)
        self._print_results(results)
        return results

    def _calculate_results(
        self, trades: List[Dict], equity_curve: List[float], symbol: str,
        total_fees: float = 0.0,
    ) -> Dict:
        """Backtest sonuçlarını hesaplar."""
        sell_trades = [t for t in trades if t["type"] == "SELL" and "pnl" in t]
        wins = [t for t in sell_trades if t["pnl"] > 0]
        losses = [t for t in sell_trades if t["pnl"] <= 0]

        total_trades = len(sell_trades)
        final_equity = equity_curve[-1] if equity_curve else self.initial_capital

        total_pnl = sum(t["pnl"] for t in sell_trades)
        total_return_pct = ((final_equity / self.initial_capital) - 1) * 100

        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
        avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0
        avg_loss = (sum(t["pnl"] for t in losses) / len(losses)) if losses else 0

        # Max Drawdown
        eq = pd.Series(equity_curve)
        peak = eq.cummax()
        drawdown = (eq - peak) / peak * 100
        max_drawdown = float(drawdown.min()) if len(drawdown) > 0 else 0

        # Sharpe Ratio (basit)
        if len(equity_curve) > 1:
            returns = pd.Series(equity_curve).pct_change().dropna()
            sharpe = (
                (returns.mean() / returns.std() * np.sqrt(252))
                if returns.std() > 0
                else 0
            )
        else:
            sharpe = 0

        # Profit Factor
        total_wins_amt = sum(t["pnl"] for t in wins)
        total_losses_amt = abs(sum(t["pnl"] for t in losses))
        profit_factor = (
            total_wins_amt / total_losses_amt if total_losses_amt > 0 else float("inf")
        )

        return {
            "symbol": symbol,
            "initial_capital": self.initial_capital,
            "final_equity": round(final_equity, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "total_fees": round(total_fees, 2),
            "trades": trades,
            "equity_curve": equity_curve,
        }

    def _print_results(self, results: Dict):
        """Sonuçları konsola yazdırır."""
        logger.info("=" * 60)
        logger.info(f"📊 BACKTEST SONUÇLARI: {results['symbol']}")
        logger.info("=" * 60)
        logger.info(f"  Başlangıç Sermaye:  ${results['initial_capital']:,.2f}")
        logger.info(f"  Final Sermaye:      ${results['final_equity']:,.2f}")
        logger.info(f"  Toplam P&L:         ${results['total_pnl']:,.2f} ({results['total_return_pct']:+.1f}%)")
        logger.info(f"  Toplam İşlem:       {results['total_trades']}")
        logger.info(f"  Kazanç/Kayıp:       {results['wins']}W / {results['losses']}L")
        logger.info(f"  Win Rate:           {results['win_rate']:.1f}%")
        logger.info(f"  Ort. Kazanç:        ${results['avg_win']:,.2f}")
        logger.info(f"  Ort. Kayıp:         ${results['avg_loss']:,.2f}")
        logger.info(f"  Profit Factor:      {results['profit_factor']:.2f}")
        logger.info(f"  Max Drawdown:       {results['max_drawdown_pct']:.1f}%")
        logger.info(f"  Sharpe Ratio:       {results['sharpe_ratio']:.2f}")
        logger.info(f"  Toplam Komisyon:    ${results.get('total_fees', 0):,.2f}")
        logger.info("=" * 60)

    def run_multiple(self, symbols: List[str], period: str = "6mo") -> List[Dict]:
        """Birden fazla hisse üzerinde backtest çalıştırır."""
        results = []
        for symbol in symbols:
            try:
                result = self.run(symbol, period)
                results.append(result)
            except Exception as e:
                logger.error(f"Backtest hatası ({symbol}): {e}")
                continue

        # Özet
        if results:
            total_pnl = sum(r.get("total_pnl", 0) for r in results)
            avg_wr = np.mean([r.get("win_rate", 0) for r in results])
            logger.info(f"\n📈 TOPLAM SONUÇ: ${total_pnl:,.2f} | Ort. Win Rate: {avg_wr:.1f}%")

        return results


# Doğrudan çalıştırma
if __name__ == "__main__":
    bt = Backtester(initial_capital=10000)

    # Tek hisse test
    result = bt.run("AAPL", period="6mo")

    # Çoklu hisse test
    # results = bt.run_multiple(["AAPL", "TSLA", "AMD", "NVDA"], period="6mo")
