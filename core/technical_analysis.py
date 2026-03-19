"""
Technical Analysis - Gelişmiş Teknik Gösterge Hesaplama
RSI, EMA, MACD, VWAP, Bollinger Bands, ATR
+ Ichimoku Cloud, Fibonacci Retracement, OBV, ADX, RSI Divergence
"""
import pandas as pd
import numpy as np
import ta as ta_lib
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, SMAIndicator, ADXIndicator, IchimokuIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import VolumeWeightedAveragePrice, OnBalanceVolumeIndicator
from typing import Dict, Optional
from config import TECHNICAL_CONFIG
from utils.logger import logger


class TechnicalAnalysis:
    """Gelişmiş teknik gösterge hesaplama sınıfı."""

    def __init__(self):
        self.config = TECHNICAL_CONFIG
        logger.info("TechnicalAnalysis başlatıldı (Ichimoku/Fib/OBV/ADX aktif)")

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

        # ============================================================
        # YENİ GÖSTERGELER
        # ============================================================

        # ADX (Trend Gücü)
        try:
            adx = ADXIndicator(df["high"], df["low"], df["close"], window=14)
            df["adx"] = adx.adx()
            df["adx_pos"] = adx.adx_pos()  # +DI
            df["adx_neg"] = adx.adx_neg()  # -DI
        except Exception:
            df["adx"] = 0
            df["adx_pos"] = 0
            df["adx_neg"] = 0

        # OBV (On-Balance Volume)
        try:
            obv = OnBalanceVolumeIndicator(df["close"], df["volume"])
            df["obv"] = obv.on_balance_volume()
            # OBV trend: son 10 bar'da yükselen mi?
            df["obv_sma_10"] = df["obv"].rolling(10).mean()
            df["obv_rising"] = (df["obv"] > df["obv_sma_10"]).astype(int)
        except Exception:
            df["obv"] = 0
            df["obv_rising"] = 0

        # Ichimoku Cloud
        try:
            ichimoku = IchimokuIndicator(
                df["high"], df["low"],
                window1=9, window2=26, window3=52
            )
            df["ichimoku_a"] = ichimoku.ichimoku_a()  # Senkou Span A
            df["ichimoku_b"] = ichimoku.ichimoku_b()  # Senkou Span B
            df["ichimoku_base"] = ichimoku.ichimoku_base_line()
            df["ichimoku_conv"] = ichimoku.ichimoku_conversion_line()

            # Fiyat bulutun üstünde mi altında mı?
            cloud_top = df[["ichimoku_a", "ichimoku_b"]].max(axis=1)
            cloud_bottom = df[["ichimoku_a", "ichimoku_b"]].min(axis=1)
            df["ichimoku_above_cloud"] = (df["close"] > cloud_top).astype(int)
            df["ichimoku_below_cloud"] = (df["close"] < cloud_bottom).astype(int)
        except Exception:
            df["ichimoku_above_cloud"] = 0
            df["ichimoku_below_cloud"] = 0

        # Fibonacci Retracement (son 50 bar)
        try:
            lookback = min(50, len(df))
            recent = df.tail(lookback)
            fib_high = recent["high"].max()
            fib_low = recent["low"].min()
            fib_range = fib_high - fib_low

            if fib_range > 0:
                df["fib_236"] = fib_high - fib_range * 0.236
                df["fib_382"] = fib_high - fib_range * 0.382
                df["fib_500"] = fib_high - fib_range * 0.500
                df["fib_618"] = fib_high - fib_range * 0.618

                # Fiyat hangi Fibonacci seviyesine en yakın?
                current = df["close"].iloc[-1]
                distances = {
                    "fib_236": abs(current - df["fib_236"].iloc[-1]),
                    "fib_382": abs(current - df["fib_382"].iloc[-1]),
                    "fib_500": abs(current - df["fib_500"].iloc[-1]),
                    "fib_618": abs(current - df["fib_618"].iloc[-1]),
                }
                df["nearest_fib"] = min(distances, key=distances.get)
                df["fib_proximity_pct"] = min(distances.values()) / current * 100
            else:
                df["fib_236"] = 0
                df["fib_382"] = 0
                df["fib_500"] = 0
                df["fib_618"] = 0
                df["nearest_fib"] = "none"
                df["fib_proximity_pct"] = 100
        except Exception:
            df["nearest_fib"] = "none"
            df["fib_proximity_pct"] = 100

        logger.debug(f"Teknik analiz tamamlandı - {len(df)} bar (gelişmiş)")
        return df

    # ============================================================
    # RSI DIVERGENCE TESPİTİ
    # ============================================================

    def detect_rsi_divergence(self, df: pd.DataFrame, lookback: int = 20) -> Dict:
        """
        RSI Divergence tespiti.
        Bullish: Fiyat yeni dip -> RSI yeni dip yapmıyor (gizli güç)
        Bearish: Fiyat yeni tepe -> RSI yeni tepe yapmıyor (zayıflama)
        """
        result = {"bullish_divergence": False, "bearish_divergence": False, "score": 0}

        if len(df) < lookback + 5 or "rsi" not in df.columns:
            return result

        try:
            recent = df.tail(lookback)
            price = recent["close"].values
            rsi = recent["rsi"].values

            # NaN temizle
            valid = ~(np.isnan(price) | np.isnan(rsi))
            if valid.sum() < 10:
                return result

            price = price[valid]
            rsi = rsi[valid]

            # Son yarı vs ilk yarı karşılaştırma
            mid = len(price) // 2

            price_first_half_min = price[:mid].min()
            price_second_half_min = price[mid:].min()
            rsi_first_half_min = rsi[:mid].min()
            rsi_second_half_min = rsi[mid:].min()

            price_first_half_max = price[:mid].max()
            price_second_half_max = price[mid:].max()
            rsi_first_half_max = rsi[:mid].max()
            rsi_second_half_max = rsi[mid:].max()

            # Bullish divergence: fiyat düşük dip, RSI yüksek dip
            if (price_second_half_min < price_first_half_min and
                rsi_second_half_min > rsi_first_half_min):
                result["bullish_divergence"] = True
                result["score"] = 15

            # Bearish divergence: fiyat yüksek tepe, RSI düşük tepe
            if (price_second_half_max > price_first_half_max and
                rsi_second_half_max < rsi_first_half_max):
                result["bearish_divergence"] = True
                result["score"] = -15

        except Exception as e:
            logger.debug(f"Divergence hatasi: {e}")

        return result

    def get_signal_data(self, df: pd.DataFrame) -> Optional[Dict]:
        """Son bar için sinyal verileri döndürür (gelişmiş)."""
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

            # === YENİ GÖSTERGELER ===
            # ADX
            "adx": float(last.get("adx", 0)) if pd.notna(last.get("adx")) else 0,
            "adx_pos": float(last.get("adx_pos", 0)) if pd.notna(last.get("adx_pos")) else 0,
            "adx_neg": float(last.get("adx_neg", 0)) if pd.notna(last.get("adx_neg")) else 0,

            # OBV
            "obv_rising": int(last.get("obv_rising", 0)) if pd.notna(last.get("obv_rising")) else 0,

            # Ichimoku
            "ichimoku_above_cloud": int(last.get("ichimoku_above_cloud", 0)) if pd.notna(last.get("ichimoku_above_cloud")) else 0,
            "ichimoku_below_cloud": int(last.get("ichimoku_below_cloud", 0)) if pd.notna(last.get("ichimoku_below_cloud")) else 0,

            # Fibonacci
            "nearest_fib": str(last.get("nearest_fib", "none")),
            "fib_proximity_pct": float(last.get("fib_proximity_pct", 100)) if pd.notna(last.get("fib_proximity_pct")) else 100,
        }

        # RSI Divergence
        divergence = self.detect_rsi_divergence(df)
        result["rsi_bullish_divergence"] = divergence["bullish_divergence"]
        result["rsi_bearish_divergence"] = divergence["bearish_divergence"]
        result["divergence_score"] = divergence["score"]

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
