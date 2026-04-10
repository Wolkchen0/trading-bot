"""
Short Executor — Short Pozisyon Acma (Sell Short) ve Kapatma (Buy to Cover)

Alpaca API uzerinden short selling islemleri:
- execute_short(): Kisa pozisyon ac
- execute_cover(): Kisa pozisyonu kapat (buy to cover)
- Squeeze korumasi, ATR adaptif stop-loss, PDT kontrolu
"""
from datetime import datetime, timedelta
from typing import Dict

from alpaca.trading.requests import (
    MarketOrderRequest, StopLimitOrderRequest, GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

from utils.logger import logger


class ShortExecutor:
    """Short pozisyon acma ve kapatma emirlerini yonetir."""

    def __init__(self, bot):
        self.bot = bot

    def execute_short(self, symbol: str, analysis: Dict, config: Dict, short_config: Dict) -> bool:
        """
        Short pozisyon ac — Alpaca'da pozisyon yokken SELL emri = short sell.

        1. Kara liste ve squeeze kontrolu
        2. Pozisyon boyutu hesapla (long'dan kucuk)
        3. SELL emri gonder (short)
        4. Stop-loss emri (BUY yonunde, fiyat YUKARI giderse)
        """
        bot = self.bot
        try:
            account = bot.client.get_account()
            equity = float(account.equity)

            # Paper-only kontrolu
            if short_config.get("short_paper_only", True) and not bot.is_paper:
                logger.debug(f"  {symbol} SHORT: Canli hesapta short devre disi")
                return False

            # Kara liste kontrolu
            if symbol in short_config.get("short_blacklist", []):
                logger.info(f"  {symbol} SHORT KARA LISTE: Squeeze riski yuksek")
                return False

            # Max short pozisyon kontrolu
            short_count = sum(1 for s, p in bot.short_positions.items())
            if short_count >= short_config.get("short_max_positions", 2):
                logger.debug(f"  SHORT limit: {short_count}/{short_config['short_max_positions']}")
                return False

            # Toplam short maruz kalma kontrolu
            total_short_value = sum(
                p["qty"] * p["entry_price"] for p in bot.short_positions.values()
            )
            max_exposure = equity * short_config.get("short_max_exposure_pct", 0.40)
            if total_short_value >= max_exposure:
                logger.debug(f"  SHORT maruz kalma limiti: ${total_short_value:.2f} >= ${max_exposure:.2f}")
                return False

            # Squeeze korumasi
            if short_config.get("short_squeeze_protection", True):
                if self._is_squeeze_risk(symbol, analysis):
                    logger.warning(f"  {symbol} SHORT SQUEEZE RISKI! Volume/fiyat spike — short yapilmiyor")
                    return False

            # Pozisyon boyutu
            price = analysis["price"]
            max_invest = min(
                equity * short_config.get("short_max_position_pct", 0.20),
                short_config.get("short_max_position_usd", 150),
            )

            if max_invest < config.get("min_trade_value", 10):
                logger.debug(f"  SHORT yetersiz: ${max_invest:.2f}")
                return False

            qty = round(max_invest / price, 4)  # Fractional shares
            if qty * price < 1:
                return False

            logger.info(f"  SHORT pozisyon: ${max_invest:.2f} | {qty:.4f} adet @ ${price:,.2f}")

            # Short emri gonder (pozisyon yokken SELL = short sell)
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = bot.client.submit_order(request)

            logger.info(
                f"  🔻 SHORT {symbol}: {qty:.4f} @ ${price:,.2f} "
                f"(${qty * price:,.2f}) | {', '.join(analysis.get('reasons', []))}"
            )

            # ATR adaptif stop-loss (ters yon — fiyat YUKARI giderse)
            atr_value = analysis.get("atr", 0)
            if atr_value > 0 and price > 0:
                atr_pct = atr_value / price
                adaptive_sl = atr_pct * short_config.get("short_atr_stop_multiplier", 2.0)
                adaptive_sl = max(adaptive_sl, short_config["short_stop_loss_pct"])
                adaptive_sl = min(adaptive_sl, short_config["short_stop_loss_max_pct"])
            else:
                adaptive_sl = short_config["short_stop_loss_pct"]

            # Sunucu tarafli stop-loss (BUY emri — fiyat yukselirse cover)
            stop_price = round(price * (1 + adaptive_sl), 2)
            try:
                limit_price = round(stop_price * 1.005, 2)  # Ters: limit > stop
                sl_request = StopLimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY,  # Short cover = BUY
                    time_in_force=TimeInForce.GTC,
                    stop_price=stop_price,
                    limit_price=limit_price,
                )
                bot.client.submit_order(sl_request)
                logger.info(
                    f"  SHORT STOP-LOSS: {symbol} @ ${stop_price:,.2f} "
                    f"(+{adaptive_sl:.1%} | ATR={atr_value:.4f})"
                )
            except Exception as sl_err:
                logger.warning(f"  Short stop-loss emri gonderilemedi: {sl_err}")

            # Pozisyon kaydet
            bot.short_positions[symbol] = {
                "entry_price": price,
                "qty": qty,
                "entry_time": datetime.now().isoformat(),
                "order_id": str(order.id),
                "stop_loss_price": stop_price,
                "stop_loss_pct": adaptive_sl,
                "lowest_price": price,  # Trailing stop icin (ters)
                "partial_covered": False,
            }
            bot.last_trade_time[symbol] = datetime.now()
            bot.trades_today.append({
                "action": "SHORT", "symbol": symbol, "price": price,
                "qty": qty, "time": datetime.now().isoformat(),
            })
            bot.consecutive_errors = 0

            # Telegram bildirim
            if hasattr(bot, 'notifier'):
                bot.notifier.send_message(
                    f"🔻 SHORT {symbol}\n"
                    f"Qty: {qty:.4f} @ ${price:,.2f}\n"
                    f"Stop: ${stop_price:,.2f} (+{adaptive_sl:.1%})\n"
                    f"Sebepler: {', '.join(analysis.get('reasons', []))}"
                )

            return True

        except Exception as e:
            error_msg = str(e)
            if "403" in error_msg or "short" in error_msg.lower():
                logger.error(f"SHORT REJECT: {symbol} — {error_msg}")
            else:
                logger.error(f"SHORT hata {symbol}: {e}")
            bot.consecutive_errors += 1
            return False

    def execute_cover(self, symbol: str, reason: str) -> bool:
        """
        Short pozisyonu kapat (buy to cover).
        Alpaca'da close_position() otomatik olarak cover eder.
        """
        bot = self.bot
        try:
            # Cooldown kontrolu
            cooldown_until = bot.sell_cooldown.get(f"short_{symbol}")
            if cooldown_until and datetime.now() < cooldown_until:
                logger.debug(f"  COVER cooldown: {symbol}")
                return False

            # PDT kontrolu
            pos = bot.short_positions.get(symbol, {})
            entry_time = pos.get("entry_time", "")
            if hasattr(bot, 'pdt_tracker') and entry_time:
                should_hold, hold_reason = bot.pdt_tracker.should_hold_overnight(symbol, entry_time)
                if should_hold and "STOP_LOSS" not in reason:
                    logger.warning(f"  SHORT PDT: {hold_reason}")
                    return False

            # Bekleyen stop emirlerini iptal et
            try:
                orders = bot.client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN)
                )
                for o in orders:
                    if o.symbol == symbol and o.side == OrderSide.BUY:
                        bot.client.cancel_order_by_id(o.id)
                        logger.debug(f"  Short stop emri iptal: {o.id}")
            except Exception:
                pass

            # Pozisyonu kapat
            bot.client.close_position(symbol)

            # PDT kaydi
            if hasattr(bot, 'pdt_tracker') and entry_time:
                if bot.pdt_tracker.is_same_day_position(symbol, entry_time):
                    bot.pdt_tracker.record_day_trade(
                        symbol, entry_time, datetime.now().isoformat()
                    )

            # Cooldown
            cooldown_secs = 300
            bot.sell_cooldown[f"short_{symbol}"] = datetime.now() + timedelta(seconds=cooldown_secs)

            entry = pos.get("entry_price", 0)
            qty = pos.get("qty", 0)

            logger.info(f"  🔺 COVER {symbol}: {qty:.4f} | Sebep: {reason}")

            bot.short_positions.pop(symbol, None)
            bot.last_trade_time[symbol] = datetime.now()
            bot.trades_today.append({
                "action": "COVER", "symbol": symbol,
                "reason": reason, "time": datetime.now().isoformat(),
            })

            # Telegram bildirim
            if hasattr(bot, 'notifier'):
                bot.notifier.send_message(
                    f"🔺 COVER {symbol} | {reason}"
                )

            bot.consecutive_errors = 0
            return True

        except Exception as e:
            logger.error(f"COVER hata {symbol}: {e}")
            bot.consecutive_errors += 1
            return False

    def _is_squeeze_risk(self, symbol: str, analysis: Dict) -> bool:
        """Short squeeze risk tespiti."""
        volume_ratio = analysis.get("volume_ratio", 1.0)
        momentum = analysis.get("momentum_5bar", 0)

        # Volume 3x VE fiyat %5+ yukseliyorsa
        if volume_ratio > 3.0 and momentum > 5.0:
            return True

        # RSI 80+ (asiri alinan, squeeze yangini olabilir)
        rsi = analysis.get("rsi", 50)
        if rsi > 80 and volume_ratio > 2.0:
            return True

        return False
