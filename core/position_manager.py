"""
Position Manager — Pozisyon Yönetimi

CryptoBot'tan ayrıştırılmış pozisyon modülü.
- manage_positions(): Trailing stop, break-even, kademeli kâr alma, stop-loss
"""
from datetime import datetime
from typing import Dict

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from utils.logger import logger


class PositionManager:
    """Açık pozisyonları yönetir. CryptoBot referansı üzerinden state'e erişir."""

    def __init__(self, bot):
        self.bot = bot

    def manage_positions(self, config: Dict):
        """Gelişmiş pozisyon yönetimi: trailing stop + kademeli kâr alma."""
        bot = self.bot
        try:
            positions = bot.client.get_all_positions()
        except Exception as e:
            logger.error(f"Pozisyon listesi alinamadi: {e}")
            bot.consecutive_errors += 1
            return

        for pos in positions:
            symbol_clean = pos.symbol
            if "USD" in symbol_clean:
                symbol = symbol_clean[:-3] + "/" + symbol_clean[-3:]
            else:
                symbol = symbol_clean

            # Cooldown kontrolü
            cooldown_until = bot.sell_cooldown.get(symbol)
            if cooldown_until and datetime.now() < cooldown_until:
                continue

            # Minimum pozisyon değeri kontrolü ($5)
            pos_value = float(pos.qty) * float(pos.current_price)
            if pos_value < 5.0:
                logger.debug(f"  Pozisyon cok kucuk, atla: {symbol} ${pos_value:.2f}")
                continue

            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_usd = float(pos.unrealized_pl)

            # Trailing stop güncelleme
            pos_data = bot.positions.get(symbol, {})
            highest = pos_data.get("highest_price", entry_price)
            if current_price > highest:
                highest = current_price
                if symbol in bot.positions:
                    bot.positions[symbol]["highest_price"] = highest

            trailing_drop = (highest - current_price) / highest if highest > 0 else 0

            # === BREAK-EVEN STOP ===
            pos_sl_pct_override = None
            if config.get("breakeven_enabled", True):
                be_trigger = config.get("breakeven_trigger_pct", 0.015)
                be_offset = config.get("breakeven_offset_pct", 0.001)
                if pnl_pct >= be_trigger and not pos_data.get("breakeven_set", False):
                    breakeven_price = entry_price * (1 + be_offset)
                    if symbol in bot.positions:
                        bot.positions[symbol]["stop_loss_pct"] = be_offset
                        bot.positions[symbol]["breakeven_set"] = True
                    logger.info(
                        f"  🔒 BREAK-EVEN {symbol}: +{pnl_pct:.1%} → SL giris fiyatina cekildi (${breakeven_price:.4f})"
                    )
                    pos_sl_pct_override = be_offset

            # === SATIŞ KARARLARI (ÖNCELİK SIRASINA GÖRE) ===

            # 1. KESİN STOP-LOSS
            pos_sl_pct = pos_sl_pct_override if pos_sl_pct_override is not None else pos_data.get("stop_loss_pct", config["stop_loss_pct"])
            if pnl_pct <= -pos_sl_pct:
                logger.info(
                    f"  STOP LOSS {symbol}: {pnl_pct:.1%} (limit: -{pos_sl_pct:.1%}) (${pnl_usd:+.2f})"
                )
                bot.executor.execute_sell(symbol, f"STOP_LOSS ({pnl_pct:.1%} / limit -{pos_sl_pct:.1%})")

            # 2. TAKE PROFIT
            elif pnl_pct >= config["take_profit_pct"]:
                logger.info(
                    f"  TAKE PROFIT {symbol}: +{pnl_pct:.1%} (${pnl_usd:+.2f})"
                )
                bot.executor.execute_sell(symbol, f"TAKE_PROFIT (+{pnl_pct:.1%})")

            # 3. TRAILING STOP
            elif pnl_pct > 0.01 and trailing_drop >= config["trailing_stop_pct"]:
                logger.info(
                    f"  TRAILING STOP {symbol}: Peak ${highest:,.4f} -> ${current_price:,.4f} "
                    f"(-{trailing_drop:.1%}) | P&L: {pnl_pct:.1%}"
                )
                bot.executor.execute_sell(symbol, f"TRAILING_STOP (peak -{trailing_drop:.1%})")

            # 4. KADEMELİ KÂR ALMA
            elif (pnl_pct >= config["partial_profit_pct"]
                  and not pos_data.get("partial_sold", False)):
                logger.info(
                    f"  KADEMELI KAR {symbol}: +{pnl_pct:.1%} -> Yarisi satiliyor"
                )
                try:
                    qty = float(pos.qty)
                    half_qty = round(qty * 0.5, 8)
                    if half_qty > 0:
                        request = MarketOrderRequest(
                            symbol=symbol, qty=half_qty,
                            side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
                        )
                        bot.client.submit_order(request)
                        if symbol in bot.positions:
                            bot.positions[symbol]["partial_sold"] = True
                        logger.info(f"  Yarisi satildi: {half_qty:.6f} {symbol}")
                except Exception as e:
                    logger.error(f"Kademeli satis hatasi {symbol}: {e}")

            # Durum logla
            if abs(pnl_pct) > 0.01:
                logger.debug(
                    f"  Pozisyon {symbol}: {pnl_pct:+.2%} | "
                    f"Peak: ${highest:,.4f} | Trail: -{trailing_drop:.2%}"
                )
