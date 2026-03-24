"""
Data Fetcher - Alpaca API ve yfinance ile piyasa verisi çekme.
Gerçek zamanlı ve geçmiş veri desteği.
"""
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from utils.logger import logger


class DataFetcher:
    """Piyasa verisi çekme sınıfı."""

    def __init__(self):
        self.data_client = StockHistoricalDataClient(
            ALPACA_API_KEY, ALPACA_SECRET_KEY
        )
        self.trading_client = TradingClient(
            ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True
        )
        logger.info("DataFetcher başlatıldı")

    def get_bars(
        self,
        symbol: str,
        timeframe: TimeFrame = TimeFrame.Minute,
        days_back: int = 5,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """Belirli bir hisse için bar (OHLCV) verisi çeker."""
        try:
            start = datetime.now() - timedelta(days=days_back)
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start,
                limit=limit,
            )
            bars = self.data_client.get_stock_bars(request)
            df = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.droplevel("symbol")
            df.index = pd.to_datetime(df.index)
            logger.debug(f"{symbol}: {len(df)} bar çekildi ({timeframe})")
            return df
        except Exception as e:
            logger.error(f"{symbol} bar verisi çekilemedi: {e}")
            return pd.DataFrame()

    def get_daily_bars(self, symbol: str, days_back: int = 60) -> pd.DataFrame:
        """Günlük bar verisi çeker (backtesting ve analiz için)."""
        return self.get_bars(symbol, TimeFrame.Day, days_back)

    def get_minute_bars(self, symbol: str, days_back: int = 5) -> pd.DataFrame:
        """Dakikalık bar verisi çeker (gün içi analiz için)."""
        return self.get_bars(symbol, TimeFrame.Minute, days_back)

    def get_latest_quote(self, symbol: str) -> Optional[Dict]:
        """Anlık fiyat bilgisi çeker."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.data_client.get_stock_latest_quote(request)
            q = quote[symbol]
            return {
                "symbol": symbol,
                "ask": float(q.ask_price),
                "bid": float(q.bid_price),
                "ask_size": q.ask_size,
                "bid_size": q.bid_size,
                "timestamp": q.timestamp,
            }
        except Exception as e:
            logger.error(f"{symbol} quote çekilemedi: {e}")
            return None

    def get_snapshot(self, symbol: str) -> Optional[Dict]:
        """Hisse snapshot verisini çeker (fiyat, hacim, değişim)."""
        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbol)
            snapshot = self.data_client.get_stock_snapshot(request)
            snap = snapshot[symbol]

            daily_bar = snap.daily_bar
            prev_daily_bar = snap.previous_daily_bar
            minute_bar = snap.minute_bar

            prev_close = float(prev_daily_bar.close) if prev_daily_bar else 0
            current_price = float(daily_bar.close) if daily_bar else 0
            change_pct = (
                ((current_price - prev_close) / prev_close * 100)
                if prev_close > 0
                else 0
            )

            return {
                "symbol": symbol,
                "price": current_price,
                "open": float(daily_bar.open) if daily_bar else 0,
                "high": float(daily_bar.high) if daily_bar else 0,
                "low": float(daily_bar.low) if daily_bar else 0,
                "volume": int(daily_bar.volume) if daily_bar else 0,
                "prev_close": prev_close,
                "change_pct": round(change_pct, 2),
                "minute_price": float(minute_bar.close) if minute_bar else current_price,
                "minute_volume": int(minute_bar.volume) if minute_bar else 0,
            }
        except Exception as e:
            logger.error(f"{symbol} snapshot çekilemedi: {e}")
            return None

    def get_snapshots_bulk(self, symbols: List[str]) -> Dict[str, Dict]:
        """Birden fazla hisse için snapshot çeker."""
        results = {}
        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbols)
            snapshots = self.data_client.get_stock_snapshot(request)

            for symbol, snap in snapshots.items():
                daily_bar = snap.daily_bar
                prev_daily_bar = snap.previous_daily_bar
                prev_close = float(prev_daily_bar.close) if prev_daily_bar else 0
                current_price = float(daily_bar.close) if daily_bar else 0
                change_pct = (
                    ((current_price - prev_close) / prev_close * 100)
                    if prev_close > 0
                    else 0
                )

                results[symbol] = {
                    "symbol": symbol,
                    "price": current_price,
                    "volume": int(daily_bar.volume) if daily_bar else 0,
                    "prev_close": prev_close,
                    "change_pct": round(change_pct, 2),
                }
        except Exception as e:
            logger.error(f"Bulk snapshot çekilemedi: {e}")
        return results

    def get_tradable_assets(self) -> List[str]:
        """Alpaca'da işlem yapılabilir US hisse listesini çeker."""
        try:
            request = GetAssetsRequest(
                asset_class=AssetClass.US_EQUITY,
                status=AssetStatus.ACTIVE,
            )
            assets = self.trading_client.get_all_assets(request)
            symbols = [
                a.symbol
                for a in assets
                if a.tradable and a.shortable is not None
            ]
            logger.info(f"{len(symbols)} işlem yapılabilir hisse bulundu")
            return symbols
        except Exception as e:
            logger.error(f"Asset listesi çekilemedi: {e}")
            return []

    def get_historical_yfinance(
        self, symbol: str, period: str = "6mo", interval: str = "1d"
    ) -> pd.DataFrame:
        """yfinance ile geçmiş veri çeker (backtesting için)."""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            df.columns = [c.lower() for c in df.columns]
            logger.debug(f"{symbol}: {len(df)} bar (yfinance, {period})")
            return df
        except Exception as e:
            logger.error(f"{symbol} yfinance verisi çekilemedi: {e}")
            return pd.DataFrame()
