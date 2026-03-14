"""
Stock Scanner - Momentum hisse tarayıcı.
Fiyat, hacim, değişim yüzdesine göre potansiyel hisseleri filtreler.
"""
import pandas as pd
from typing import List, Dict, Optional
from config import SCANNER_CONFIG
from core.data_fetcher import DataFetcher
from utils.logger import logger


class StockScanner:
    """Momentum hisse tarama sınıfı."""

    def __init__(self, data_fetcher: DataFetcher):
        self.data_fetcher = data_fetcher
        self.config = SCANNER_CONFIG
        logger.info("StockScanner başlatıldı")

    def scan_movers(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        """
        Gainer/mover hisseleri tarar.
        Filtreleme: fiyat aralığı, hacim, günlük değişim yüzdesi.
        """
        if symbols is None:
            # Önceden belirlenmiş popüler small-cap hisseler + aktif hisseler
            symbols = self._get_watchlist()

        logger.info(f"{len(symbols)} hisse taranıyor...")

        # Batch snapshot çek
        movers = []
        batch_size = 50
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            try:
                snapshots = self.data_fetcher.get_snapshots_bulk(batch)
                for symbol, snap in snapshots.items():
                    if self._passes_filter(snap):
                        movers.append(snap)
            except Exception as e:
                logger.error(f"Batch tarama hatası: {e}")
                continue

        # Değişim yüzdesine göre sırala
        movers.sort(key=lambda x: abs(x.get("change_pct", 0)), reverse=True)

        # Top N sonuç
        top_n = self.config["top_n_results"]
        results = movers[:top_n]

        logger.info(f"✅ {len(results)} momentum hisse bulundu:")
        for m in results:
            logger.info(
                f"  {m['symbol']}: ${m['price']:.2f} ({m['change_pct']:+.1f}%) "
                f"Vol: {m['volume']:,}"
            )

        return results

    def _passes_filter(self, snap: Dict) -> bool:
        """Hissenin filtre kriterlerini karşılayıp karşılamadığını kontrol eder."""
        price = snap.get("price", 0)
        volume = snap.get("volume", 0)
        change_pct = abs(snap.get("change_pct", 0))

        # Fiyat filtresi
        if price < self.config["min_price"] or price > self.config["max_price"]:
            return False

        # Hacim filtresi
        if volume < self.config["min_volume"]:
            return False

        # Değişim yüzdesi filtresi
        if change_pct < self.config["min_change_pct"]:
            return False

        return True

    def _get_watchlist(self) -> List[str]:
        """
        Popüler aktif hisseleri döndürür.
        Gerçek üretimde bu dinamik olarak Alpaca'dan çekilir.
        """
        # Yaygın momentum small-cap/mid-cap hisseler
        # Bu liste günlük taramada genişletilebilir
        default_watchlist = [
            # Teknoloji
            "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "GOOGL", "AMZN",
            "PLTR", "SOFI", "RIVN", "LCID", "NIO", "MARA", "RIOT", "COIN",
            # Popüler small-cap'ler
            "SNDL", "CLOV", "WISH", "BBIG", "MULN", "FFIE", "NKLA",
            "PLUG", "FCEL", "BLNK", "QS", "LAZR", "LIDR",
            # Biyoteknoloji
            "MRNA", "BNTX", "NVAX",
            # Enerji
            "TELL", "ET", "OXY",
            # Finans
            "SQ", "HOOD", "UPST",
            # Diğer popüler
            "GME", "AMC", "BB", "NOK", "SPCE",
            "OPEN", "RBLX", "U", "SNAP", "PINS",
        ]

        # Alpaca'dan tam listeyi çek (isteğe bağlı - daha kapsamlı ama yavaş)
        try:
            all_assets = self.data_fetcher.get_tradable_assets()
            if all_assets:
                # Aktif listeden rastgele 200 tane al + default watchlist
                import random
                sample = random.sample(all_assets, min(200, len(all_assets)))
                combined = list(set(default_watchlist + sample))
                return combined
        except Exception:
            pass

        return default_watchlist

    def get_top_gainers(self, limit: int = 5) -> List[Dict]:
        """En çok yükselen hisseleri döndürür."""
        movers = self.scan_movers()
        gainers = [m for m in movers if m.get("change_pct", 0) > 0]
        return gainers[:limit]

    def get_top_losers(self, limit: int = 5) -> List[Dict]:
        """En çok düşen hisseleri döndürür (short fırsatları)."""
        movers = self.scan_movers()
        losers = [m for m in movers if m.get("change_pct", 0) < 0]
        losers.sort(key=lambda x: x.get("change_pct", 0))
        return losers[:limit]
