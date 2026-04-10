"""
Position Manager — Pozisyon Yönetimi

StockBot'tan ayrıştırılmış pozisyon modülü.
- manage_positions(): Trailing stop, break-even, kademeli kâr alma, stop-loss
"""
from datetime import datetime
from typing import Dict

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from utils.logger import logger


class PositionManager:
    """Açık pozisyonları yönetir. StockBot referansı üzerinden state'e erişir."""

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
            symbol = pos.symbol  # Hisse senedi: doğrudan sembol

            # Cooldown kontrolü
            cooldown_until = bot.sell_cooldown.get(symbol)
            if cooldown_until and datetime.now() < cooldown_until:
                continue

            # Minimum pozisyon değeri kontrolü ($5)
            pos_value = float(pos.qty) * float(pos.current_price)
            if pos_value < config.get("min_position_close_usd", 5.0):
                logger.debug(f"  Pozisyon cok kucuk, atla: {symbol} ${pos_value:.2f}")
                continue

            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
            pnl_usd = float(pos.unrealized_pl)

            # Pozisyon senkronizasyonu — bot.positions'da yoksa ekle
            if symbol not in bot.positions:
                bot.positions[symbol] = {
                    "entry_price": entry_price,
                    "qty": float(pos.qty),
                    "entry_time": datetime.now().isoformat(),
                    "highest_price": current_price,
                    "synced_from_alpaca": True,
                }

            # Trailing stop güncelleme
            pos_data = bot.positions.get(symbol, {})
            highest = pos_data.get("highest_price", entry_price)
            if current_price > highest:
                highest = current_price
                bot.positions[symbol]["highest_price"] = highest

            trailing_drop = (highest - current_price) / highest if highest > 0 else 0

            # === BREAK-EVEN STOP ===
            pos_sl_pct_override = None
            if config.get("breakeven_enabled", True):
                be_trigger = config.get("breakeven_trigger_pct", 0.015)
                be_offset = config.get("breakeven_offset_pct", 0.001)
                if pnl_pct >= be_trigger and not pos_data.get("breakeven_set", False):
                    breakeven_price = entry_price * (1 + be_offset)
                    bot.positions[symbol]["stop_loss_pct"] = be_offset
                    bot.positions[symbol]["breakeven_set"] = True
                    logger.info(
                        f"  🔒 BREAK-EVEN {symbol}: +{pnl_pct:.1%} → SL giriş fiyatına çekildi (${breakeven_price:.2f})"
                    )
                    pos_sl_pct_override = be_offset

            # === SATIŞ KARARLARI (ÖNCELİK SIRASINA GÖRE) ===

            # 1. KESİN STOP-LOSS
            pos_sl_pct = pos_sl_pct_override if pos_sl_pct_override is not None else pos_data.get("stop_loss_pct", config["stop_loss_pct"])
            if pnl_pct <= -pos_sl_pct:
                logger.info(
                    f"  🛑 STOP LOSS {symbol}: {pnl_pct:.1%} (limit: -{pos_sl_pct:.1%}) (${pnl_usd:+.2f})"
                )
                bot.executor.execute_sell(symbol, f"STOP_LOSS ({pnl_pct:.1%} / limit -{pos_sl_pct:.1%})")

            # 2. TAKE PROFIT
            elif pnl_pct >= config["take_profit_pct"]:
                logger.info(
                    f"  💰 TAKE PROFIT {symbol}: +{pnl_pct:.1%} (${pnl_usd:+.2f})"
                )
                bot.executor.execute_sell(symbol, f"TAKE_PROFIT (+{pnl_pct:.1%})")

            # 3. TRAILING STOP
            elif pnl_pct > 0.01 and trailing_drop >= config["trailing_stop_pct"]:
                logger.info(
                    f"  📉 TRAILING STOP {symbol}: Peak ${highest:,.2f} -> ${current_price:,.2f} "
                    f"(-{trailing_drop:.1%}) | P&L: {pnl_pct:.1%}"
                )
                bot.executor.execute_sell(symbol, f"TRAILING_STOP (peak -{trailing_drop:.1%})")

            # 4. KADEMELİ KÂR ALMA (hisse senedi: tam hisse satılmalı)
            elif (pnl_pct >= config["partial_profit_pct"]
                  and not pos_data.get("partial_sold", False)):
                logger.info(
                    f"  📊 KADEMELI KÂR {symbol}: +{pnl_pct:.1%} -> Yarısı satılıyor"
                )
                try:
                    qty = float(pos.qty)
                    half_qty = max(int(qty * 0.5), 1) if qty >= 2 else qty  # Hisse: tam sayı
                    if half_qty > 0:
                        request = MarketOrderRequest(
                            symbol=symbol, qty=half_qty,
                            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
                        )
                        bot.client.submit_order(request)
                        bot.positions[symbol]["partial_sold"] = True
                        logger.info(f"  ✅ Yarısı satıldı: {half_qty} {symbol}")
                except Exception as e:
                    logger.error(f"Kademeli satış hatası {symbol}: {e}")

            # Durum logla (önemli pozisyonlar)
            if abs(pnl_pct) > 0.02:
                logger.info(
                    f"  📋 {symbol}: {pnl_pct:+.2%} (${pnl_usd:+.2f}) | "
                    f"Peak: ${highest:,.2f} | Trail: -{trailing_drop:.2%}"
                )

    def manage_short_positions(self, config: Dict, short_config: Dict):
        """Short pozisyon yonetimi — ters mantik: fiyat duserse KAR."""
        bot = self.bot
        try:
            positions = bot.client.get_all_positions()
        except Exception as e:
            logger.error(f"Short pozisyon listesi alinamadi: {e}")
            return

        for pos in positions:
            symbol = pos.symbol
            qty = float(pos.qty)

            # Sadece short pozisyonlar (Alpaca: negatif qty = short)
            if qty >= 0:
                continue

            abs_qty = abs(qty)

            # Cooldown kontrolu
            cooldown_until = bot.sell_cooldown.get(f"short_{symbol}")
            if cooldown_until and datetime.now() < cooldown_until:
                continue

            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)

            # SHORT P&L: fiyat DUSTUYSE kar, YUKSELDI ise zarar
            pnl_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0
            pnl_usd = float(pos.unrealized_pl)

            # Short pozisyon senkronizasyonu
            if symbol not in bot.short_positions:
                bot.short_positions[symbol] = {
                    "entry_price": entry_price,
                    "qty": abs_qty,
                    "entry_time": datetime.now().isoformat(),
                    "lowest_price": current_price,
                    "synced_from_alpaca": True,
                    "partial_covered": False,
                }

            pos_data = bot.short_positions.get(symbol, {})

            # Trailing: en dusuk fiyat takibi (ters trailing)
            lowest = pos_data.get("lowest_price", entry_price)
            if current_price < lowest:
                lowest = current_price
                bot.short_positions[symbol]["lowest_price"] = lowest

            # Dipten yukari ziplama orani
            trailing_rise = (current_price - lowest) / lowest if lowest > 0 else 0

            # === BREAK-EVEN SHORT ===
            if short_config.get("short_breakeven_enabled", True):
                be_trigger = short_config.get("short_breakeven_trigger_pct", 0.025)
                be_offset = short_config.get("short_breakeven_offset_pct", 0.003)
                if pnl_pct >= be_trigger and not pos_data.get("breakeven_set", False):
                    bot.short_positions[symbol]["stop_loss_pct"] = be_offset
                    bot.short_positions[symbol]["breakeven_set"] = True
                    logger.info(
                        f"  🔒 SHORT BREAK-EVEN {symbol}: +{pnl_pct:.1%} → SL girisa cekildi"
                    )

            # === SATIS KARARLARI ===

            # 1. STOP-LOSS (fiyat YUKARI gitti = zarar)
            pos_sl = pos_data.get("stop_loss_pct", short_config["short_stop_loss_pct"])
            if pnl_pct <= -pos_sl:
                logger.info(
                    f"  🛑 SHORT STOP {symbol}: {pnl_pct:.1%} (limit: -{pos_sl:.1%}) (${pnl_usd:+.2f})"
                )
                bot.short_executor.execute_cover(symbol, f"SHORT_STOP_LOSS ({pnl_pct:.1%})")

            # 2. TAKE PROFIT (fiyat ASAGI gitti = kar)
            elif pnl_pct >= short_config["short_take_profit_pct"]:
                logger.info(
                    f"  💰 SHORT TP {symbol}: +{pnl_pct:.1%} (${pnl_usd:+.2f})"
                )
                bot.short_executor.execute_cover(symbol, f"SHORT_TAKE_PROFIT (+{pnl_pct:.1%})")

            # 3. TRAILING STOP (dipten yukari ziplama)
            elif pnl_pct > 0.01 and trailing_rise >= short_config["short_trailing_stop_pct"]:
                logger.info(
                    f"  📉 SHORT TRAIL {symbol}: Low ${lowest:,.2f} -> ${current_price:,.2f} "
                    f"(+{trailing_rise:.1%}) | P&L: {pnl_pct:.1%}"
                )
                bot.short_executor.execute_cover(symbol, f"SHORT_TRAILING (+{trailing_rise:.1%})")

            # 4. KADEMELI COVER (yarisini kapat)
            elif (pnl_pct >= short_config.get("short_partial_profit_pct", 0.04)
                  and not pos_data.get("partial_covered", False)):
                logger.info(
                    f"  📊 SHORT PARTIAL {symbol}: +{pnl_pct:.1%} → Yarisini cover"
                )
                try:
                    from alpaca.trading.requests import MarketOrderRequest
                    from alpaca.trading.enums import OrderSide, TimeInForce
                    half_qty = round(abs_qty * 0.5, 4)
                    if half_qty > 0:
                        request = MarketOrderRequest(
                            symbol=symbol, qty=half_qty,
                            side=OrderSide.BUY,  # Cover = BUY
                            time_in_force=TimeInForce.DAY,
                        )
                        bot.client.submit_order(request)
                        bot.short_positions[symbol]["partial_covered"] = True
                        logger.info(f"  ✅ Short yarisini cover: {half_qty} {symbol}")
                except Exception as e:
                    logger.error(f"Short partial cover hatasi {symbol}: {e}")

            # Durum logla
            if abs(pnl_pct) > 0.02:
                logger.info(
                    f"  📋 SHORT {symbol}: {pnl_pct:+.2%} (${pnl_usd:+.2f}) | "
                    f"Low: ${lowest:,.2f} | Rise: +{trailing_rise:.2%}"
                )
