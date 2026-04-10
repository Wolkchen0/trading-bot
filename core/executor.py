"""
Order Executor — Hisse Senedi Alım/Satım Emir Yönetimi

- execute_buy(): Alım emri + adaptif stop-loss + PDT koruması
- execute_sell(): Satım emri + cooldown + PDT kontrolü
- Alpaca hisse senedi: komisyon $0, fractional shares destekli
"""
from datetime import datetime, timedelta
from typing import Dict

from alpaca.trading.requests import (
    MarketOrderRequest, StopLimitOrderRequest, GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

from utils.logger import logger


class OrderExecutor:
    """Hisse senedi alım/satım emirlerini yönetir."""

    def __init__(self, bot):
        self.bot = bot

    def execute_buy(self, symbol: str, analysis: Dict, config: Dict) -> bool:
        """Hisse alım emri — PDT-aware, fractional shares destekli."""
        bot = self.bot
        try:
            account = bot.client.get_account()
            cash = float(account.cash)
            equity = float(account.equity)

            # Equity floor kontrolü
            if not bot.is_paper and bot.equity_floor > 0 and equity < bot.equity_floor:
                logger.warning(
                    f"EQUITY FLOOR! Hesap ${equity:,.2f} < floor ${bot.equity_floor:,.2f} — "
                    f"Yeni alim yapilmiyor."
                )
                return False

            # Market saati kontrolü
            if hasattr(bot, 'market_hours'):
                status = bot.market_hours.get_market_status()
                if not status["is_trading_allowed"]:
                    # Extended hours: sadece çok yüksek güvenle
                    confidence = analysis.get("confidence", 0)
                    if not bot.market_hours.should_allow_extended_hours(confidence):
                        logger.info(f"  Piyasa kapalı ({status['status']}), alım engellendi")
                        return False

            # Nakit rezerv kontrolü
            cash_reserve = equity * config.get("cash_reserve_pct", 0.15)
            available_cash = max(cash - cash_reserve, 0)

            if available_cash < 10:
                logger.warning(f"Nakit rezerv korumasi: Cash ${cash:.2f}, Rezerv ${cash_reserve:.2f}")
                return False

            # Tier-based pozisyon boyutu
            tier_weight = config.get("tier_weights", {}).get(
                symbol, config.get("default_tier_weight", 0.20)
            )
            max_invest = min(
                available_cash * tier_weight,
                equity * config["max_position_pct"],
                bot.max_pos_usd,
            )

            if max_invest < config.get("min_trade_value", 10):
                logger.warning(f"Yetersiz bakiye: ${max_invest:.2f} < min ${config.get('min_trade_value', 10)}")
                return False

            price = analysis["price"]

            # Hisse senedi: komisyon $0!
            qty = round(max_invest / price, 4)  # Fractional shares

            if qty * price < 1:
                logger.warning(f"Çok küçük işlem: ${qty * price:.2f}")
                return False

            logger.info(f"  Pozisyon: ${max_invest:.2f} | {qty:.4f} adet @ ${price:,.2f} (tier: {tier_weight:.0%})")

            # Emir gönder
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,  # Hisse: DAY (piyasa kapanışında iptal)
            )
            order = bot.client.submit_order(request)

            logger.info(
                f"  ✅ BUY {symbol}: {qty:.4f} @ ${price:,.2f} "
                f"(${qty * price:,.2f}) | Komisyon: $0 "
                f"| {', '.join(analysis.get('reasons', []))}"
            )

            # ADAPTIF STOP-LOSS
            atr_value = analysis.get("atr", 0)
            if atr_value > 0 and price > 0:
                atr_pct = atr_value / price
                adaptive_sl = atr_pct * config['atr_stop_multiplier']
                adaptive_sl = max(adaptive_sl, config['stop_loss_pct'])
                adaptive_sl = min(adaptive_sl, config['stop_loss_max_pct'])
            else:
                adaptive_sl = config['stop_loss_pct']

            # Sunucu taraflı stop-loss
            stop_price = round(price * (1 - adaptive_sl), 2)
            try:
                limit_price = round(stop_price * 0.995, 2)
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
                    f"  STOP-LOSS: {symbol} @ ${stop_price:,.2f} "
                    f"({adaptive_sl:.1%} | ATR={atr_value:.4f})"
                )
            except Exception as sl_err:
                logger.warning(f"  Stop-loss emri gönderilemedi: {sl_err}")

            # Pozisyon kaydet
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

            # Telegram bildirim
            if hasattr(bot, 'notifier'):
                bot.notifier.notify_buy(
                    symbol, qty, price,
                    confidence=int(analysis.get('confidence', 0)),
                    reasons=analysis.get('reasons', []),
                )

            return True

        except Exception as e:
            error_msg = str(e)
            # PDT rejection handler
            if "403" in error_msg or "pattern day trader" in error_msg.lower():
                if hasattr(bot, 'pdt_tracker'):
                    bot.pdt_tracker.handle_pdt_rejection(symbol, error_msg)
                logger.error(f"PDT VIOLATION: {symbol} alım reddedildi — {error_msg}")
            else:
                logger.error(f"BUY hatasi {symbol}: {e}")
            bot.consecutive_errors += 1
            return False

    def execute_sell(self, symbol: str, reason: str) -> bool:
        """Satış emri — PDT kontrolü ile."""
        bot = self.bot
        try:
            # Cooldown kontrolü
            cooldown_until = bot.sell_cooldown.get(symbol)
            if cooldown_until and datetime.now() < cooldown_until:
                logger.debug(f"  SELL cooldown: {symbol}")
                return False

            # PDT kontrolü — aynı gün alınmış pozisyon mu?
            pos = bot.positions.get(symbol, {})
            entry_time = pos.get("entry_time", "")
            if hasattr(bot, 'pdt_tracker') and entry_time:
                should_hold, hold_reason = bot.pdt_tracker.should_hold_overnight(symbol, entry_time)
                if should_hold:
                    # STOP_LOSS durumunda PDT'yi görmezden gel (sermaye koruması > PDT)
                    if "STOP_LOSS" not in reason:
                        logger.warning(f"  {hold_reason}")
                        return False
                    else:
                        logger.warning(f"  PDT: STOP_LOSS override — sermaye koruması öncelikli")

            # Bekleyen stop-loss emirlerini iptal et
            try:
                orders = bot.client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN)
                )
                for o in orders:
                    if o.symbol == symbol and o.side == OrderSide.SELL:
                        bot.client.cancel_order_by_id(o.id)
                        logger.debug(f"  Eski stop-loss iptal: {o.id}")
            except Exception:
                pass

            # Pozisyonu kapat
            bot.client.close_position(symbol)

            # PDT kaydı (aynı gün alınıp satıldıysa)
            if hasattr(bot, 'pdt_tracker') and entry_time:
                if bot.pdt_tracker.is_same_day_position(symbol, entry_time):
                    bot.pdt_tracker.record_day_trade(
                        symbol, entry_time, datetime.now().isoformat()
                    )

            # Cooldown — swing trade için daha uzun (varsayılan 5dk)
            cooldown_secs = 300  # default 5 dakika
            try:
                from config import STOCK_CONFIG
                cooldown_secs = STOCK_CONFIG.get("sell_cooldown_seconds", 300)
            except Exception:
                pass
            bot.sell_cooldown[symbol] = datetime.now() + timedelta(seconds=cooldown_secs)

            entry = pos.get("entry_price", 0)
            qty = pos.get("qty", 0)

            logger.info(f"  ✅ SELL {symbol}: {qty:.4f} | Sebep: {reason}")

            bot.positions.pop(symbol, None)
            bot.last_trade_time[symbol] = datetime.now()
            bot.trades_today.append({
                "action": "SELL", "symbol": symbol,
                "reason": reason, "time": datetime.now().isoformat(),
            })

            # Kayıp/kazanç serisi takibi
            if "STOP_LOSS" in reason:
                bot._consecutive_losses = getattr(bot, '_consecutive_losses', 0) + 1
                sym_losses = getattr(bot, '_symbol_consecutive_losses', {})
                sym_losses[symbol] = sym_losses.get(symbol, 0) + 1
                bot._symbol_consecutive_losses = sym_losses
                logger.info(f"  Ardisik zarar: {bot._consecutive_losses} | {symbol}: {sym_losses[symbol]}")
                # WashSale kaydı
                if hasattr(bot, 'wash_sale_tracker'):
                    bot.wash_sale_tracker.record_loss_sale(
                        symbol, -1.0, datetime.now().isoformat()[:10]
                    )
            elif "TAKE_PROFIT" in reason or "TRAILING_STOP" in reason:
                bot._consecutive_losses = 0
                sym_losses = getattr(bot, '_symbol_consecutive_losses', {})
                sym_losses[symbol] = 0
                bot._symbol_consecutive_losses = sym_losses

            # Performans takibi + Telegram bildirim
            if hasattr(bot, 'performance'):
                from config import SECTOR_MAP
                sector = SECTOR_MAP.get(symbol, "Unknown")
                bot.performance.record_trade(
                    symbol=symbol, action="SELL", qty=float(qty),
                    price=float(entry), pnl=pnl_usd, reason=reason,
                    sector=sector,
                )
            if hasattr(bot, 'notifier'):
                pnl_pct = (pnl_usd / max(float(entry) * float(qty), 0.01)) * 100 if entry else 0
                bot.notifier.notify_sell(symbol, reason, pnl_usd, pnl_pct)

            bot.consecutive_errors = 0
            return True

        except Exception as e:
            error_msg = str(e)
            if "403" in error_msg or "pattern day trader" in error_msg.lower():
                if hasattr(bot, 'pdt_tracker'):
                    bot.pdt_tracker.handle_pdt_rejection(symbol, error_msg)
                logger.error(f"PDT: {symbol} satış reddedildi — pozisyon overnight tutulacak")
            else:
                logger.error(f"SELL hatasi {symbol}: {e}")
            bot.consecutive_errors += 1
            return False
