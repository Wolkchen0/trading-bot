"""
Order Executor - Alpaca API ile emir gönderme ve yönetme.
Buy, Sell, Stop-Loss, Bracket Order desteği.
"""
from typing import Optional, Dict, List
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderType,
    OrderStatus,
    QueryOrderStatus,
)
from alpaca.common.exceptions import APIError

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, TRADING_MODE
from utils.logger import logger


class OrderExecutor:
    """Alpaca API emir yönetimi sınıfı."""

    def __init__(self):
        is_paper = TRADING_MODE == "paper"
        self.client = TradingClient(
            ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=is_paper
        )
        self.mode = "PAPER" if is_paper else "LIVE"
        logger.info(f"OrderExecutor başlatıldı [{self.mode} mod]")

    # ============================================================
    # HESAP BİLGİLERİ
    # ============================================================

    def get_account(self) -> Optional[Dict]:
        """Hesap bilgilerini döndürür."""
        try:
            account = self.client.get_account()
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "daily_pnl": float(account.equity) - float(account.last_equity),
                "status": account.status.value if account.status else "unknown",
                "pattern_day_trader": account.pattern_day_trader,
                "trading_blocked": account.trading_blocked,
                "account_blocked": account.account_blocked,
            }
        except Exception as e:
            logger.error(f"Hesap bilgisi alınamadı: {e}")
            return None

    def get_positions(self) -> List[Dict]:
        """Açık pozisyonları döndürür."""
        try:
            positions = self.client.get_all_positions()
            result = []
            for pos in positions:
                result.append({
                    "symbol": pos.symbol,
                    "qty": int(pos.qty),
                    "side": pos.side.value if pos.side else "long",
                    "avg_entry": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "market_value": float(pos.market_value),
                    "unrealized_pnl": float(pos.unrealized_pl),
                    "unrealized_pnl_pct": float(pos.unrealized_plpc) * 100,
                    "change_today": float(pos.change_today) * 100,
                })
            return result
        except Exception as e:
            logger.error(f"Pozisyonlar alınamadı: {e}")
            return []

    # ============================================================
    # EMİR GÖNDERME
    # ============================================================

    def buy_market(self, symbol: str, qty: int) -> Optional[Dict]:
        """Market alış emri gönderir."""
        try:
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = self.client.submit_order(request)
            logger.info(f"🟢 ALIŞ: {qty} {symbol} (Market) | Order ID: {order.id}")
            return self._order_to_dict(order)
        except APIError as e:
            logger.error(f"Alış emri başarısız {symbol}: {e}")
            return None

    def buy_limit(self, symbol: str, qty: int, limit_price: float) -> Optional[Dict]:
        """Limit alış emri gönderir."""
        try:
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price,
            )
            order = self.client.submit_order(request)
            logger.info(
                f"🟢 ALIŞ: {qty} {symbol} @ ${limit_price:.2f} (Limit) "
                f"| Order ID: {order.id}"
            )
            return self._order_to_dict(order)
        except APIError as e:
            logger.error(f"Limit alış başarısız {symbol}: {e}")
            return None

    def sell_market(self, symbol: str, qty: int) -> Optional[Dict]:
        """Market satış emri gönderir."""
        try:
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = self.client.submit_order(request)
            logger.info(f"🔴 SATIŞ: {qty} {symbol} (Market) | Order ID: {order.id}")
            return self._order_to_dict(order)
        except APIError as e:
            logger.error(f"Satış emri başarısız {symbol}: {e}")
            return None

    def sell_all(self, symbol: str) -> Optional[Dict]:
        """Bir hissenin tüm pozisyonunu kapatır."""
        try:
            self.client.close_position(symbol)
            logger.info(f"🔴 TÜM POZİSYON KAPATILDI: {symbol}")
            return {"symbol": symbol, "action": "closed"}
        except APIError as e:
            logger.error(f"Pozisyon kapatma başarısız {symbol}: {e}")
            return None

    def sell_partial(self, symbol: str, percentage: float = 0.5) -> Optional[Dict]:
        """Pozisyonun bir kısmını satar (ör: %50)."""
        try:
            positions = self.client.get_all_positions()
            pos = next((p for p in positions if p.symbol == symbol), None)
            if not pos:
                logger.warning(f"{symbol} pozisyonu bulunamadı")
                return None

            total_qty = int(pos.qty)
            sell_qty = max(1, int(total_qty * percentage))

            return self.sell_market(symbol, sell_qty)
        except Exception as e:
            logger.error(f"Kısmi satış başarısız {symbol}: {e}")
            return None

    def place_stop_loss(
        self, symbol: str, qty: int, stop_price: float
    ) -> Optional[Dict]:
        """Stop-loss emri gönderir."""
        try:
            request = StopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                stop_price=stop_price,
            )
            order = self.client.submit_order(request)
            logger.info(
                f"🛡️ STOP-LOSS: {qty} {symbol} @ ${stop_price:.2f} "
                f"| Order ID: {order.id}"
            )
            return self._order_to_dict(order)
        except APIError as e:
            logger.error(f"Stop-loss başarısız {symbol}: {e}")
            return None

    def place_bracket_order(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> Optional[Dict]:
        """
        Bracket order: Alış + Stop-Loss + Take-Profit tek emirde.
        Bu, DAS Trader Pro'nun OTO (Order Trigger Order) karşılığıdır.
        """
        try:
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price,
                order_class="bracket",
                stop_loss={"stop_price": stop_loss_price},
                take_profit={"limit_price": take_profit_price},
            )
            order = self.client.submit_order(request)
            logger.info(
                f"📦 BRACKET: {qty} {symbol} @ ${limit_price:.2f} "
                f"| SL: ${stop_loss_price:.2f} | TP: ${take_profit_price:.2f} "
                f"| Order ID: {order.id}"
            )
            return self._order_to_dict(order)
        except APIError as e:
            logger.error(f"Bracket order başarısız {symbol}: {e}")
            return None

    # ============================================================
    # EMİR YÖNETİMİ
    # ============================================================

    def cancel_order(self, order_id: str) -> bool:
        """Belirli bir emri iptal eder."""
        try:
            self.client.cancel_order_by_id(order_id)
            logger.info(f"❌ Emir iptal edildi: {order_id}")
            return True
        except APIError as e:
            logger.error(f"Emir iptal başarısız: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """Tüm açık emirleri iptal eder (Panic Button)."""
        try:
            self.client.cancel_orders()
            logger.warning("⚠️ TÜM EMİRLER İPTAL EDİLDİ")
            return True
        except APIError as e:
            logger.error(f"Toplu iptal başarısız: {e}")
            return False

    def close_all_positions(self) -> bool:
        """Tüm pozisyonları kapatır (Emergency Exit)."""
        try:
            self.client.close_all_positions(cancel_orders=True)
            logger.warning("🚨 TÜM POZİSYONLAR KAPATILDI (Emergency)")
            return True
        except APIError as e:
            logger.error(f"Toplu kapatma başarısız: {e}")
            return False

    def get_open_orders(self) -> List[Dict]:
        """Açık emirleri listeler."""
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self.client.get_orders(request)
            return [self._order_to_dict(o) for o in orders]
        except Exception as e:
            logger.error(f"Emirler alınamadı: {e}")
            return []

    def _order_to_dict(self, order) -> Dict:
        """Order objesini dict'e çevirir."""
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": order.side.value if order.side else "",
            "type": order.type.value if order.type else "",
            "status": order.status.value if order.status else "",
            "limit_price": str(order.limit_price) if order.limit_price else None,
            "stop_price": str(order.stop_price) if order.stop_price else None,
            "filled_avg_price": str(order.filled_avg_price) if order.filled_avg_price else None,
            "created_at": str(order.created_at),
        }
