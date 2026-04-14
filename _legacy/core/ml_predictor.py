"""
ML Predictor — Makine Ogrenimi ile Fiyat Yonu Tahmini
Scikit-learn tabanlı (Python 3.14 uyumlu, hafif)

Model: Random Forest + Gradient Boosting ensemble
Features: RSI, MACD, BB, Volume, Trend, EMA, ATR
Hedef: 1h/4h/24h sonrası fiyat yonu (UP/DOWN)
"""
import os
import json
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from utils.logger import logger

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands, AverageTrueRange

try:
    from sklearn.ensemble import (
        RandomForestClassifier,
        GradientBoostingClassifier,
        VotingClassifier,
    )
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("scikit-learn yuklu degil, ML tahmini devre disi")


ML_CONFIG = {
    # Model ayarlari
    "min_training_samples": 100,     # Minimum egitim verisi
    "test_size": 0.2,                # %20 test
    "prediction_threshold": 0.60,    # %60 guven esigi
    "retrain_hours": 24,             # 24 saatte yeniden egit

    # Feature windowlari
    "rsi_window": 14,
    "ema_fast": 9,
    "ema_slow": 21,
    "bb_window": 20,
    "atr_window": 14,

    # Tahmin hedefleri
    "horizons": {
        "1h": 1,     # 1 saat sonra
        "4h": 4,     # 4 saat sonra
        "24h": 24,   # 24 saat sonra
    },

    # Model dosyasi
    "model_dir": "models",
}


class MLPredictor:
    """Makine ogrenimi ile fiyat yonu tahmini."""

    def __init__(self):
        self.models = {}  # {symbol: {horizon: model}}
        self.scalers = {}  # {symbol: scaler}
        self.last_train = {}
        self.accuracies = {}

        if ML_AVAILABLE:
            logger.info("MLPredictor baslatildi - Ensemble model aktif")
        else:
            logger.info("MLPredictor baslatildi - ML devre disi (scikit-learn yok)")

    # ============================================================
    # 1. FEATURE ENGINEERING
    # ============================================================

    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ham OHLCV verisinden ML ozelliklerini cikarir.
        Her satir icin ~15 feature olusturur.
        """
        if len(df) < 50:
            return pd.DataFrame()

        features = pd.DataFrame(index=df.index)
        close = df["close"]
        volume = df["volume"] if "volume" in df.columns else pd.Series(0, index=df.index)

        # === Teknik Gostergeler ===
        # RSI
        features["rsi"] = RSIIndicator(close, window=ML_CONFIG["rsi_window"]).rsi()

        # EMA
        ema_fast = EMAIndicator(close, window=ML_CONFIG["ema_fast"]).ema_indicator()
        ema_slow = EMAIndicator(close, window=ML_CONFIG["ema_slow"]).ema_indicator()
        features["ema_ratio"] = ema_fast / ema_slow

        # MACD
        macd = MACD(close)
        features["macd_hist"] = macd.macd_diff()
        features["macd_signal_diff"] = macd.macd() - macd.macd_signal()

        # Bollinger Bands
        bb = BollingerBands(close, window=ML_CONFIG["bb_window"], window_dev=2)
        features["bb_pct"] = (close - bb.bollinger_lband()) / (
            bb.bollinger_hband() - bb.bollinger_lband() + 1e-10
        )

        # ATR (volatilite)
        features["atr_pct"] = AverageTrueRange(
            df["high"], df["low"], close, window=ML_CONFIG["atr_window"]
        ).average_true_range() / close

        # === Fiyat Degisim Oranlari ===
        features["return_1h"] = close.pct_change(1)
        features["return_3h"] = close.pct_change(3)
        features["return_6h"] = close.pct_change(6)
        features["return_12h"] = close.pct_change(12)

        # === Volume ===
        if volume.sum() > 0:
            vol_ma = volume.rolling(20).mean()
            features["volume_ratio"] = volume / (vol_ma + 1e-10)
        else:
            features["volume_ratio"] = 1.0

        # === Momentum ===
        features["momentum_5"] = close / close.shift(5) - 1
        features["momentum_10"] = close / close.shift(10) - 1

        # === Volatilite ===
        features["volatility_10"] = close.pct_change().rolling(10).std()

        # NaN temizle
        features = features.dropna()

        return features

    def create_labels(self, df: pd.DataFrame, horizon: int) -> pd.Series:
        """
        Gelecekteki fiyat yonunu etiketle.
        1 = fiyat yukseldi (UP)
        0 = fiyat dustu (DOWN)
        """
        close = df["close"]
        future_return = close.shift(-horizon) / close - 1
        labels = (future_return > 0).astype(int)
        return labels

    # ============================================================
    # 2. MODEL EGITIMI
    # ============================================================

    def train(self, df: pd.DataFrame, symbol: str) -> bool:
        """
        Verilen veri ile modeli egitir.
        Ensemble: Random Forest + Gradient Boosting
        """
        if not ML_AVAILABLE:
            return False

        features = self.create_features(df)
        if len(features) < ML_CONFIG["min_training_samples"]:
            logger.debug(f"ML {symbol}: Yetersiz veri ({len(features)} < {ML_CONFIG['min_training_samples']})")
            return False

        self.models[symbol] = {}
        self.accuracies[symbol] = {}

        for horizon_name, horizon_hours in ML_CONFIG["horizons"].items():
            labels = self.create_labels(df, horizon_hours)

            # Ortak index
            common_idx = features.index.intersection(labels.dropna().index)
            X = features.loc[common_idx]
            y = labels.loc[common_idx]

            if len(X) < ML_CONFIG["min_training_samples"]:
                continue

            # Train/test split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=ML_CONFIG["test_size"], shuffle=False
            )

            # Normalize
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            # Ensemble model
            rf = RandomForestClassifier(
                n_estimators=100, max_depth=10, random_state=42, n_jobs=-1
            )
            gb = GradientBoostingClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42
            )

            ensemble = VotingClassifier(
                estimators=[("rf", rf), ("gb", gb)],
                voting="soft",
            )
            ensemble.fit(X_train_scaled, y_train)

            # Test dogrulugu
            y_pred = ensemble.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)

            self.models[symbol][horizon_name] = ensemble
            self.scalers[symbol] = scaler
            self.accuracies[symbol][horizon_name] = round(accuracy * 100, 1)

            logger.info(
                f"  ML {symbol} [{horizon_name}]: "
                f"Dogruluk: %{accuracy*100:.1f} "
                f"(egitim: {len(X_train)}, test: {len(X_test)})"
            )

        self.last_train[symbol] = datetime.now()
        return True

    # ============================================================
    # 3. TAHMIN
    # ============================================================

    def predict(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Egitilmis model ile fiyat yonu tahmini yapar.
        
        Returns:
            predictions: {1h: {direction: UP/DOWN, confidence: 0-100}, ...}
            score: -30 ile +30 arasi (trade sinyaline eklenir)
        """
        if not ML_AVAILABLE:
            return {"score": 0, "signal": "NEUTRAL", "predictions": {}}

        # Modeli yeniden egitmek gerekiyor mu?
        needs_training = (
            symbol not in self.models or
            symbol not in self.last_train or
            (datetime.now() - self.last_train.get(symbol, datetime.min)).total_seconds()
            > ML_CONFIG["retrain_hours"] * 3600
        )

        if needs_training:
            self.train(df, symbol)

        if symbol not in self.models or not self.models[symbol]:
            return {"score": 0, "signal": "NEUTRAL", "predictions": {}}

        # Feature cikart
        features = self.create_features(df)
        if features.empty:
            return {"score": 0, "signal": "NEUTRAL", "predictions": {}}

        # Son veri noktasi
        X_latest = features.iloc[[-1]]
        scaler = self.scalers.get(symbol)
        if scaler is None:
            return {"score": 0, "signal": "NEUTRAL", "predictions": {}}

        X_scaled = scaler.transform(X_latest)

        predictions = {}
        total_score = 0

        for horizon_name, model in self.models[symbol].items():
            try:
                proba = model.predict_proba(X_scaled)[0]
                pred_class = model.predict(X_scaled)[0]

                confidence = max(proba) * 100
                direction = "UP" if pred_class == 1 else "DOWN"

                predictions[horizon_name] = {
                    "direction": direction,
                    "confidence": round(confidence, 1),
                    "accuracy": self.accuracies.get(symbol, {}).get(horizon_name, 0),
                }

                # Skora ekle (sadece yeterli guven varsa)
                if confidence >= ML_CONFIG["prediction_threshold"] * 100:
                    weight = {"1h": 0.3, "4h": 0.4, "24h": 0.3}.get(horizon_name, 0.3)
                    if direction == "UP":
                        total_score += int(15 * weight)
                    else:
                        total_score -= int(15 * weight)

            except Exception as e:
                logger.debug(f"ML tahmin hatasi {symbol} {horizon_name}: {e}")

        # Sinyal
        if total_score >= 8:
            signal = "BUY"
        elif total_score <= -8:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        return {
            "score": total_score,
            "signal": signal,
            "predictions": predictions,
        }
