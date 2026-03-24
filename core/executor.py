"""
Order Executor — Alım/Satım Emir Yönetimi

CryptoBot'tan ayrıştırılmış emir modülü.
- execute_buy(): Alım emri + adaptif stop-loss
- execute_sell(): Satım emri + cooldown
"""
from datetime import datetime, timedelta
from typing import Dict

from alpaca.trading.requests import (
    MarketOrderRequest, StopLimitOrderRequest, GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

from utils.logger import logger


class OrderExecutor:
    """Alım/satım emirlerini yönetir. CryptoBot referansı üzerinden state'e erişir."""

    def __init__(self, bot):
        self.bot = bot

    def execute_buy(self, symbol: str, analysis: Dict, config: Dict) -> bool:
        """Alış emri gönderir — LIVE/PAPER pozisyon boyutlandırması."""
        bot = self.bot
        try:
            account = bot.client.get_account()
            cash = float(account.cash)
            equity = float(account.equity)

            # LIVE: Equity floor kontrolü
            if not bot.is_paper and bot.equity_floor > 0 and equity < bot.equity_floor:
                logger.warning(
                    f"EQUITY FLOOR! Hesap ${equity:,.2f} < floor ${bot.equity_floor:,.2f} — "
                    f"Yeni alim yapilmiyor. Mevcut pozisyonlar korunuyor."
                )
                return False

            # Nakit rezerv kontrolü
            cash_reserve = equity * config.get("cash_reserve_pct", 0.20)
            available_cash = max(cash - cash_reserve, 0)

            if available_cash < 10:
                logger.warning(f"Nakit rezerv korumasi: Cash ${cash:.2f}, Rezerv ${cash_reserve:.2f}")
                return False

            # Tier-based pozisyon boyutu
            tier_weight = config.get("tier_weights", {}).get(
                symbol, config.get("default_tier_weight", 0.15)
            )
            max_invest = min(
                available_cash * tier_weight,
                equity * config["max_position_pct"],
                bot.max_pos_usd,
            )

            if max_invest < config.get("min_trade_value", 10):
                logger.warning(f"Yetersiz bakiye: ${max_invest:.2f} < min ${config.get('min_trade_value', 10)}")
                return False

            logger.info(f"  Pozisyon: ${max_invest:.2f} (limit: ${bot.max_pos_usd}, tier: {tier_weight:.0%})")

            price = analysis["price"]
            commission = max_invest * config["commission_pct"]
            invest_after_fee = max_invest - commission

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
            order = bot.client.submit_order(request)

            logger.info(
                f"  BUY {symbol}: {qty:.6f} @ ${price:,.2f} "
                f"(${qty * price:,.2f}) | Fee: ${commission:.2f} "
                f"| {', '.join(analysis['reasons'])}"
            )

            # ADAPTIF STOP-LOSS: ATR bazlı dinamik hesaplama
            atr_value = analysis.get("atr", 0)
            if atr_value > 0 and price > 0:
                atr_pct = atr_value / price
                adaptive_sl = atr_pct * config['atr_stop_multiplier']
                adaptive_sl = max(adaptive_sl, config['stop_loss_pct'])
                adaptive_sl = min(adaptive_sl, config['stop_loss_max_pct'])
            else:
                adaptive_sl = config['stop_loss_pct']

            # SUNUCU TARAFLI STOP-LOSS
            stop_price = round(price * (1 - adaptive_sl), 6)
            try:
                limit_price = round(stop_price * 0.995, 6)
                sl_request = StopLimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    stop_price=stop_price,
                    limit_price=limit_price,
                )
                bot.client.submit_order(sl_request)
                logger.info(
                    f"  ADAPTIF STOP-LOSS: {symbol} @ ${stop_price:,.4f} "
                    f"({adaptive_sl:.1%} | ATR={atr_value:.4f}) "
                    f"(sunucu tarafli)"
                )
            except Exception as sl_err:
                logger.warning(f"  Stop-loss emri gonderilemedi: {sl_err}")

            # Kaydet
            bot.positions[symbol] = {
                "entry_price": price,
                "qty": qty,
                "entry_time": datetime.now().isoformat(),
                "order_id": str(order.id),
                "stop_loss_price": stop_price,
                "stop_loss_pct": adaptive_sl,
            }
            bot.last_trade_time[symbol] = datetime.now()
            bot.trades_today.append({
                "action": "BUY", "symbol": symbol, "price": price,
                "qty": qty, "time": datetime.now().isoformat(),
            })
            bot.consecutive_errors = 0
            bot._daily_buys_count = getattr(bot, '_daily_buys_count', 0) + 1
            return True

        except Exception as e:
            logger.error(f"BUY hatasi {symbol}: {e}")
            bot.consecutive_errors += 1
            return False

    def execute_sell(self, symbol: str, reason: str) -> bool:
        """Satış emri gönderir — cooldown ile döngü önleme."""
        bot = self.bot
        try:
            # Cooldown kontrolü
            cooldown_until = bot.sell_cooldown.get(symbol)
            if cooldown_until and datetime.now() < cooldown_until:
                logger.debug(f"  SELL cooldown: {symbol} (bekle {(cooldown_until - datetime.now()).seconds}sn)")
                return False

            # Bekleyen stop-loss emirlerini iptal et
            try:
                orders = bot.client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN)
                )
                for o in orders:
                    if o.symbol == symbol.replace('/', '') and o.side == OrderSide.SELL:
                        bot.client.cancel_order_by_id(o.id)
                        logger.debug(f"  Eski stop-loss iptal: {o.id}")
            except Exception:
                pass

            # Pozisyonu kapat
            bot.client.close_position(symbol.replace("/", ""))

            # 60 saniyelik cooldown koy
            bot.sell_cooldown[symbol] = datetime.now() + timedelta(seconds=60)

            pos = bot.positions.get(symbol, {})
            entry = pos.get("entry_price", 0)
            qty = pos.get("qty", 0)

            logger.info(
                f"  SELL {symbol}: {qty:.6f} | Sebep: {reason}"
            )

            bot.positions.pop(symbol, None)
            bot.last_trade_time[symbol] = datetime.now()
            bot.trades_today.append({
                "action": "SELL", "symbol": symbol,
                "reason": reason, "time": datetime.now().isoformat(),
            })

            # Kayıp/kazanç serisi takibi
            if "STOP_LOSS" in reason:
                bot._consecutive_losses = getattr(bot, '_consecutive_losses', 0) + 1
                coin_losses = getattr(bot, '_coin_consecutive_losses', {})
                coin_losses[symbol] = coin_losses.get(symbol, 0) + 1
                bot._coin_consecutive_losses = coin_losses
                logger.info(f"  Ardisik zarar: {bot._consecutive_losses} | {symbol} zarar serisi: {coin_losses[symbol]}")
            elif "TAKE_PROFIT" in reason or "TRAILING_STOP" in reason:
                bot._consecutive_losses = 0
                coin_losses = getattr(bot, '_coin_consecutive_losses', {})
                coin_losses[symbol] = 0
                bot._coin_consecutive_losses = coin_losses

            bot.consecutive_errors = 0
            return True

        except Exception as e:
            logger.error(f"SELL hatasi {symbol}: {e}")
            bot.consecutive_errors += 1
            return False
