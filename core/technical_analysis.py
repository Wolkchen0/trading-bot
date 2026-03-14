"""
Technical Analysis - 'ta' kütüphanesi ile teknik gösterge hesaplama.
RSI, EMA, MACD, VWAP, Bollinger Bands, ATR vb.
"""
import pandas as pd
import ta as ta_lib
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import VolumeWeightedAveragePrice
from typing import Dict, Optional
from config import TECHNICAL_CONFIG
from utils.logger import logger


class TechnicalAnalysis:
    """Teknik gösterge hesaplama sınıfı."""

    def __init__(self):
        self.config = TECHNICAL_CONFIG
        logger.info("TechnicalAnalysis başlatıldı")

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Tüm teknik göstergeleri hesaplar ve DataFrame'e ekler."""
        if df.empty or len(df) < 30:
            logger.warning("Yeterli veri yok (min 30 bar gerekli)")
            return df

        df = df.copy()

        # RSI
        rsi = RSIIndicator(df["close"], window=self.config["rsi_period"])
        df["rsi"] = rsi.rsi()

        # EMA'lar
        df["ema_fast"] = EMAIndicator(df["close"], window=self.config["ema_fast"]).ema_indicator()
        df["ema_medium"] = EMAIndicator(df["close"], window=self.config["ema_medium"]).ema_indicator()
        df["ema_slow"] = EMAIndicator(df["close"], window=self.config["ema_slow"]).ema_indicator()

        # MACD
        macd = MACD(
            df["close"],
            window_fast=self.config["macd_fast"],
            window_slow=self.config["macd_slow"],
            window_sign=self.config["macd_signal"],
        )
        df["MACD_12_26_9"] = macd.macd()
        df["MACDs_12_26_9"] = macd.macd_signal()
        df["MACDh_12_26_9"] = macd.macd_diff()

        # Bollinger Bands
        bb = BollingerBands(
            df["close"],
            window=self.config["bb_period"],
            window_dev=self.config["bb_std_dev"],
        )
        df["BBU_20_2.0"] = bb.bollinger_hband()
        df["BBM_20_2.0"] = bb.bollinger_mavg()
        df["BBL_20_2.0"] = bb.bollinger_lband()

        # ATR (stop-loss hesabı için)
        atr = AverageTrueRange(
            df["high"], df["low"], df["close"], window=self.config["atr_period"]
        )
        df["atr"] = atr.average_true_range()

        # VWAP (gün içi veri için)
        if "volume" in df.columns and len(df) > 1:
            try:
                vwap = VolumeWeightedAveragePrice(
                    df["high"], df["low"], df["close"], df["volume"]
                )
                df["vwap"] = vwap.volume_weighted_average_price()
            except Exception:
                df["vwap"] = None

        # Volume MA (göreli hacim için)
        df["volume_sma_20"] = SMAIndicator(df["volume"].astype(float), window=20).sma_indicator()
        df["relative_volume"] = df["volume"] / df["volume_sma_20"]

        # Momentum (close - close[10])
        df["momentum"] = df["close"] - df["close"].shift(10)

        # Stochastic RSI
        try:
            stoch_rsi = StochRSIIndicator(df["close"])
            df["STOCHRSIk_14_14_3_3"] = stoch_rsi.stochrsi_k()
            df["STOCHRSId_14_14_3_3"] = stoch_rsi.stochrsi_d()
        except Exception:
            pass

        logger.debug(f"Teknik analiz tamamlandı - {len(df)} bar")
        return df

    def get_signal_data(self, df: pd.DataFrame) -> Optional[Dict]:
        """Son bar için sinyal verileri döndürür."""
        if df.empty:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        result = {
            "close": float(last.get("close", 0)),
            "volume": float(last.get("volume", 0)),
            "rsi": float(last.get("rsi", 50)) if pd.notna(last.get("rsi")) else 50,
            "ema_fast": float(last.get("ema_fast", 0)) if pd.notna(last.get("ema_fast")) else 0,
            "ema_medium": float(last.get("ema_medium", 0)) if pd.notna(last.get("ema_medium")) else 0,
            "ema_slow": float(last.get("ema_slow", 0)) if pd.notna(last.get("ema_slow")) else 0,
            "atr": float(last.get("atr", 0)) if pd.notna(last.get("atr")) else 0,
            "vwap": float(last.get("vwap", 0)) if pd.notna(last.get("vwap")) else 0,
            "relative_volume": float(last.get("relative_volume", 1)) if pd.notna(last.get("relative_volume")) else 1,
            "momentum": float(last.get("momentum", 0)) if pd.notna(last.get("momentum")) else 0,

            # MACD
            "macd": float(last.get("MACD_12_26_9", 0)) if pd.notna(last.get("MACD_12_26_9")) else 0,
            "macd_signal": float(last.get("MACDs_12_26_9", 0)) if pd.notna(last.get("MACDs_12_26_9")) else 0,
            "macd_hist": float(last.get("MACDh_12_26_9", 0)) if pd.notna(last.get("MACDh_12_26_9")) else 0,

            # Bollinger Bands
            "bb_upper": float(last.get("BBU_20_2.0", 0)) if pd.notna(last.get("BBU_20_2.0")) else 0,
            "bb_middle": float(last.get("BBM_20_2.0", 0)) if pd.notna(last.get("BBM_20_2.0")) else 0,
            "bb_lower": float(last.get("BBL_20_2.0", 0)) if pd.notna(last.get("BBL_20_2.0")) else 0,

            # Önceki bar
            "prev_close": float(prev.get("close", 0)),
            "prev_rsi": float(prev.get("rsi", 50)) if pd.notna(prev.get("rsi")) else 50,
            "prev_ema_fast": float(prev.get("ema_fast", 0)) if pd.notna(prev.get("ema_fast")) else 0,
            "prev_macd_hist": float(prev.get("MACDh_12_26_9", 0)) if pd.notna(prev.get("MACDh_12_26_9")) else 0,
        }

        return result

    def calculate_stop_loss(self, entry_price: float, atr: float, side: str = "buy") -> float:
        """ATR bazlı stop-loss fiyatı hesaplar."""
        multiplier = self.config["atr_multiplier"]
        if side == "buy":
            return round(entry_price - (atr * multiplier), 2)
        else:
            return round(entry_price + (atr * multiplier), 2)

    def calculate_take_profit(self, entry_price: float, stop_loss: float, rr_ratio: float = 2.0) -> float:
        """Risk/Ödül oranına göre take-profit hesaplar."""
        risk = abs(entry_price - stop_loss)
        if entry_price > stop_loss:  # Long pozisyon
            return round(entry_price + (risk * rr_ratio), 2)
        else:  # Short pozisyon
            return round(entry_price - (risk * rr_ratio), 2)
