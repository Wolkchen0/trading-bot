"""
Crypto Data Fetcher - CCXT ile kripto borsasından veri çekme ve trade yapma.

⚠️ ABD KULLANICILARI İÇİN:
  - Global Binance (binance.com) DEĞİL → Binance.US (binanceus) kullanılmalı
  - Coinbase DEĞİL → Coinbase Advanced Trade (coinbaseadvanced)
  - Bybit, KuCoin, OKX → ABD'de yasal olarak kullanılamaz
  
🔒 API GÜVENLİK:
  - Sadece Read + Trade yetkileri açılmalı
  - ASLA Withdrawal yetkisi açılmamalı
  - IP whitelist ayarlanmalı
"""
import ccxt
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict
from utils.logger import logger


class CryptoFetcher:
    """CCXT tabanlı kripto veri ve trade sınıfı (ABD uyumlu)."""

    # ABD'de yasal olarak kullanılabilecek borsalar
    # ⚠️ Global borsaları (binance, bybit, kucoin, okx) KULLANMAYIN
    EXCHANGES = {
        "binanceus": ccxt.binanceus,       # Binance.US (ABD versiyonu)
        "kraken": ccxt.kraken,             # ABD uyumlu
        "coinbaseadvanced": ccxt.coinbase, # Coinbase Advanced Trade
        "gemini": ccxt.gemini,             # ABD uyumlu
    }

    def __init__(self, exchange_name: str = "binanceus", api_key: str = "", secret: str = ""):
        """
        Kripto borsasına bağlan.
        API key olmadan da fiyat verisi çekilebilir.
        
        ⚠️ API key oluştururken:
        - Sadece "Read" + "Spot Trading" yetkisi aç
        - "Withdrawal/Transfer" yetkisini KESİNLİKLE AÇMA
        - IP whitelist ayarla
        """
        if exchange_name not in self.EXCHANGES:
            logger.warning(f"Bilinmeyen borsa: {exchange_name}, binanceus kullanılıyor")
            exchange_name = "binanceus"

        config = {"enableRateLimit": True}
        if api_key and secret:
            config["apiKey"] = api_key
            config["secret"] = secret

        self.exchange = self.EXCHANGES[exchange_name](config)
        self.exchange_name = exchange_name
        logger.info(f"CryptoFetcher başlatıldı: {exchange_name} (ABD uyumlu)")

    def get_ohlcv(
        self, symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 200
    ) -> pd.DataFrame:
        """
        OHLCV (mum) verisi çeker.
        symbol: 'BTC/USDT', 'ETH/USDT', 'SOL/USDT' vb.
        timeframe: '1m', '5m', '15m', '1h', '4h', '1d'
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            logger.debug(f"{symbol}: {len(df)} bar çekildi ({timeframe})")
            return df
        except Exception as e:
            logger.error(f"Kripto OHLCV hatası ({symbol}): {e}")
            return pd.DataFrame()

    def get_ticker(self, symbol: str = "BTC/USDT") -> Optional[Dict]:
        """Anlık fiyat bilgisi."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "last": ticker.get("last", 0),
                "bid": ticker.get("bid", 0),
                "ask": ticker.get("ask", 0),
                "high": ticker.get("high", 0),
                "low": ticker.get("low", 0),
                "volume": ticker.get("baseVolume", 0),
                "change_pct": ticker.get("percentage", 0),
                "timestamp": ticker.get("datetime", ""),
            }
        except Exception as e:
            logger.error(f"Kripto ticker hatası ({symbol}): {e}")
            return None

    def get_top_movers(self, quote: str = "USDT", limit: int = 10) -> List[Dict]:
        """En çok hareket eden kripto paraları bulur."""
        try:
            tickers = self.exchange.fetch_tickers()
            usdt_pairs = [
                v for k, v in tickers.items()
                if k.endswith(f"/{quote}") and v.get("percentage") is not None
            ]
            usdt_pairs.sort(key=lambda x: abs(x.get("percentage", 0)), reverse=True)

            results = []
            for t in usdt_pairs[:limit]:
                results.append({
                    "symbol": t.get("symbol", ""),
                    "last": t.get("last", 0),
                    "change_pct": round(t.get("percentage", 0), 2),
                    "volume": t.get("baseVolume", 0),
                })

            logger.info(f"Top {limit} kripto mover bulundu")
            return results
        except Exception as e:
            logger.error(f"Top movers hatası: {e}")
            return []

    # ============ TRADE FONKSİYONLARI (API key gerektirir) ============

    def buy_market(self, symbol: str, amount: float) -> Optional[Dict]:
        """Market alış emri."""
        try:
            order = self.exchange.create_market_buy_order(symbol, amount)
            logger.info(f"🟢 KRİPTO ALIŞ: {amount} {symbol}")
            return order
        except Exception as e:
            logger.error(f"Kripto alış hatası: {e}")
            return None

    def sell_market(self, symbol: str, amount: float) -> Optional[Dict]:
        """Market satış emri."""
        try:
            order = self.exchange.create_market_sell_order(symbol, amount)
            logger.info(f"🔴 KRİPTO SATIŞ: {amount} {symbol}")
            return order
        except Exception as e:
            logger.error(f"Kripto satış hatası: {e}")
            return None

    def get_balance(self) -> Optional[Dict]:
        """Hesap bakiyesi."""
        try:
            balance = self.exchange.fetch_balance()
            non_zero = {
                k: v for k, v in balance.get("total", {}).items()
                if v and v > 0
            }
            return non_zero
        except Exception as e:
            logger.error(f"Bakiye hatası: {e}")
            return None

    @staticmethod
    def list_exchanges() -> List[str]:
        """Desteklenen borsaları listeler."""
        return list(CryptoFetcher.EXCHANGES.keys())
