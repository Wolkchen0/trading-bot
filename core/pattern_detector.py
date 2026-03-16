"""
Pattern Detector — Grafik Formasyonları & Fibonacci Analizi
Bot bu modülle "grafik okuyabilen" bir analist seviyesine çıkar.

Desteklenen analizler:
  1. Fibonacci Retracement seviyeleri (23.6%, 38.2%, 50%, 61.8%, 78.6%)
  2. Destek / Direnç seviyeleri (pivot noktaları)
  3. Grafik formasyonları: İkili Tepe/Dip (Double Top/Bottom)
  4. Mum çubuk desenleri: Doji, Hammer, Engulfing, Morning Star
  5. Trend çizgisi analizi
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from utils.logger import logger


class PatternDetector:
    """Grafik formasyonları ve Fibonacci analizi."""

    def __init__(self):
        logger.info("PatternDetector baslatildi - Formasyon takibi aktif")

    # ============================================================
    # 1. FİBONACCİ RETRACEMENT
    # ============================================================

    def fibonacci_levels(self, df: pd.DataFrame, lookback: int = 50) -> Dict:
        """
        Fibonacci retracement seviyelerini hesaplar.
        
        Fibonacci seviyeleri, fiyatın geri çekilme noktalarını tahmin eder.
        - %23.6: Zayıf geri çekilme (trend güçlü)
        - %38.2: Normal geri çekilme
        - %50.0: Orta seviye (psikolojik)
        - %61.8: Altın oran (en kritik seviye)
        - %78.6: Derin geri çekilme (trend zayıflıyor)
        """
        if len(df) < lookback:
            lookback = len(df)

        recent = df.tail(lookback)
        high = recent["high"].max()
        low = recent["low"].min()
        diff = high - low
        current_price = df["close"].iloc[-1]

        # Trend yönünü belirle
        high_idx = recent["high"].idxmax()
        low_idx = recent["low"].idxmin()
        is_uptrend = low_idx < high_idx  # Düşük önce geldiyse yükseliş trendi

        # Fibonacci seviyeleri
        ratios = {
            "0.0": 0.0,
            "23.6": 0.236,
            "38.2": 0.382,
            "50.0": 0.500,
            "61.8": 0.618,
            "78.6": 0.786,
            "100.0": 1.0,
        }

        levels = {}
        for name, ratio in ratios.items():
            if is_uptrend:
                # Yükseliş trendinde: geri çekilme seviyeleri
                levels[name] = high - (diff * ratio)
            else:
                # Düşüş trendinde: toparlanma seviyeleri
                levels[name] = low + (diff * ratio)

        # Fiyatın en yakın Fibonacci seviyesini bul
        nearest_level = None
        nearest_dist = float("inf")
        for name, level in levels.items():
            dist = abs(current_price - level) / current_price
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_level = name

        # Sinyal üret
        signal = "NEUTRAL"
        score = 0

        if nearest_dist < 0.01:  # Fiyat bir Fibonacci seviyesine %1 yakın
            if nearest_level in ("61.8", "78.6") and is_uptrend:
                signal = "BUY"
                score = 20  # Altın orana yakın geri çekilme → güçlü destek
            elif nearest_level in ("38.2", "50.0") and is_uptrend:
                signal = "BUY"
                score = 15
            elif nearest_level in ("23.6", "38.2") and not is_uptrend:
                signal = "SELL"
                score = -15  # Toparlanma zayıf → düşüş devam

        return {
            "levels": levels,
            "current_price": current_price,
            "nearest_level": nearest_level,
            "nearest_distance_pct": round(nearest_dist * 100, 2),
            "trend": "UP" if is_uptrend else "DOWN",
            "swing_high": high,
            "swing_low": low,
            "signal": signal,
            "score": score,
        }

    # ============================================================
    # 2. DESTEK / DİRENÇ SEVİYELERİ
    # ============================================================

    def support_resistance(
        self, df: pd.DataFrame, window: int = 10, num_levels: int = 3
    ) -> Dict:
        """
        Pivot noktalarından destek ve direnç seviyelerini tespit eder.
        
        Destek: Fiyatın düşüp geri döndüğü seviyeler (taban)
        Direnç: Fiyatın yükselip geri döndüğü seviyeler (tavan)
        """
        if len(df) < window * 2:
            return {"supports": [], "resistances": [], "signal": "NEUTRAL", "score": 0}

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        current_price = closes[-1]

        # Yerel tepe ve dip noktalarını bul
        local_highs = []
        local_lows = []

        for i in range(window, len(df) - window):
            # Yerel tepe: etrafındaki 'window' bar'dan yüksek
            if highs[i] == max(highs[i - window:i + window + 1]):
                local_highs.append(highs[i])

            # Yerel dip: etrafındaki 'window' bar'dan düşük
            if lows[i] == min(lows[i - window:i + window + 1]):
                local_lows.append(lows[i])

        # Kümeleme: Yakın seviyeleri birleştir
        supports = self._cluster_levels(local_lows, current_price, num_levels)
        resistances = self._cluster_levels(local_highs, current_price, num_levels)

        # Fiyatın destek/direnç yakınlığını kontrol et
        signal = "NEUTRAL"
        score = 0
        nearest_support = None
        nearest_resistance = None

        for s in supports:
            dist = (current_price - s) / current_price
            if 0 < dist < 0.02:  # Desteğe %2 yakın ve üstünde
                signal = "BUY"
                score = 15
                nearest_support = s
                break

        for r in resistances:
            dist = (r - current_price) / current_price
            if 0 < dist < 0.02:  # Dirence %2 yakın ve altında
                if signal != "BUY":
                    signal = "SELL"
                    score = -10
                nearest_resistance = r
                break

        return {
            "supports": supports,
            "resistances": resistances,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "signal": signal,
            "score": score,
        }

    def _cluster_levels(
        self, levels: List[float], current_price: float, n: int
    ) -> List[float]:
        """Yakın fiyat seviyelerini kümeleyerek birleştir."""
        if not levels:
            return []

        levels = sorted(levels)
        clusters = []
        current_cluster = [levels[0]]

        threshold = current_price * 0.01  # %1 yakınlık

        for i in range(1, len(levels)):
            if levels[i] - current_cluster[-1] < threshold:
                current_cluster.append(levels[i])
            else:
                clusters.append(np.mean(current_cluster))
                current_cluster = [levels[i]]

        clusters.append(np.mean(current_cluster))

        # En yakın n seviyeyi döndür
        clusters.sort(key=lambda x: abs(x - current_price))
        return [round(c, 6) for c in clusters[:n]]

    # ============================================================
    # 3. GRAFİK FORMASYONLARI
    # ============================================================

    def detect_double_top(self, df: pd.DataFrame, tolerance: float = 0.02) -> Dict:
        """
        İkili Tepe (Double Top) formasyonu - DÜŞÜŞ sinyali.
        
        İki kez aynı seviyeye çıkıp düşerse → satış baskısı artar.
        M şeklinde görünür.
        """
        if len(df) < 30:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}

        highs = df["high"].values
        closes = df["close"].values

        # Son 30 bar'da yerel tepeleri bul
        peaks = []
        for i in range(5, len(df) - 5):
            if highs[i] == max(highs[i-5:i+6]):
                peaks.append((i, highs[i]))

        # En az 2 tepe olmalı
        if len(peaks) < 2:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}

        # Son 2 tepeyi karşılaştır
        peak1, peak2 = peaks[-2], peaks[-1]
        price_diff = abs(peak1[1] - peak2[1]) / peak1[1]

        # Tepeler arasında yeterli mesafe olmalı (en az 5 bar)
        bar_diff = peak2[0] - peak1[0]

        if price_diff < tolerance and bar_diff > 5:
            # Boyun çizgisi (iki tepe arası minimum)
            neckline_idx = range(peak1[0], peak2[0] + 1)
            neckline = min(df["low"].iloc[list(neckline_idx)])

            # Fiyat boyun çizgisine yaklaşıyor mu?
            current = closes[-1]
            if current < neckline * 1.01:
                return {
                    "detected": True,
                    "pattern": "DOUBLE_TOP",
                    "signal": "SELL",
                    "score": -25,
                    "peak_price": round(float(peak1[1]), 6),
                    "neckline": round(float(neckline), 6),
                    "description": "Ikili Tepe - Dusus bekleniyor",
                }

        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    def detect_double_bottom(self, df: pd.DataFrame, tolerance: float = 0.02) -> Dict:
        """
        İkili Dip (Double Bottom) formasyonu - YÜKSELME sinyali.
        
        İki kez aynı seviyeye düşüp yükselirse → alım baskısı artar.
        W şeklinde görünür.
        """
        if len(df) < 30:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}

        lows = df["low"].values
        closes = df["close"].values

        # Son 30 bar'da yerel dipleri bul
        valleys = []
        for i in range(5, len(df) - 5):
            if lows[i] == min(lows[i-5:i+6]):
                valleys.append((i, lows[i]))

        if len(valleys) < 2:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}

        valley1, valley2 = valleys[-2], valleys[-1]
        price_diff = abs(valley1[1] - valley2[1]) / valley1[1]
        bar_diff = valley2[0] - valley1[0]

        if price_diff < tolerance and bar_diff > 5:
            neckline_idx = range(valley1[0], valley2[0] + 1)
            neckline = max(df["high"].iloc[list(neckline_idx)])

            current = closes[-1]
            if current > neckline * 0.99:
                return {
                    "detected": True,
                    "pattern": "DOUBLE_BOTTOM",
                    "signal": "BUY",
                    "score": 25,
                    "valley_price": round(float(valley1[1]), 6),
                    "neckline": round(float(neckline), 6),
                    "description": "Ikili Dip - Yukselis bekleniyor",
                }

        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    # ============================================================
    # 4. MUM ÇUBUK DESENLERİ
    # ============================================================

    def detect_candlestick_patterns(self, df: pd.DataFrame) -> Dict:
        """
        Klasik mum çubuk formasyonlarını algılar.
        
        - Doji: Kararsızlık (açılış ≈ kapanış)
        - Hammer: Düşüş sonrası toparlanma sinyali
        - Engulfing: Güçlü trend dönüşü
        - Morning/Evening Star: 3 mumlu dönüş formasyonu
        """
        if len(df) < 3:
            return {"patterns": [], "signal": "NEUTRAL", "score": 0}

        patterns = []
        total_score = 0

        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values

        # Son mum analizi
        i = -1  # Son mum
        body = abs(c[i] - o[i])
        upper_shadow = h[i] - max(o[i], c[i])
        lower_shadow = min(o[i], c[i]) - l[i]
        total_range = h[i] - l[i]

        if total_range == 0:
            return {"patterns": [], "signal": "NEUTRAL", "score": 0}

        body_ratio = body / total_range

        # --- DOJI ---
        if body_ratio < 0.1:
            patterns.append({
                "name": "DOJI",
                "type": "reversal",
                "description": "Kararsizlik - trend donusu olabilir",
            })
            # Doji'nin yönünü önceki trende göre belirle
            if c[-2] > c[-3]:  # Önceki trend yukarı idi
                total_score -= 5  # Yükselişten sonra doji = potansiyel düşüş
            else:
                total_score += 5  # Düşüşten sonra doji = potansiyel yükseliş

        # --- HAMMER (Düşüş sonrası) ---
        if (lower_shadow > body * 2 and
            upper_shadow < body * 0.5 and
            c[-2] < o[-2]):  # Önceki mum düşüş
            patterns.append({
                "name": "HAMMER",
                "type": "bullish",
                "description": "Cekic - Dip alim sinyali",
            })
            total_score += 15

        # --- INVERTED HAMMER (Düşüş sonrası) ---
        if (upper_shadow > body * 2 and
            lower_shadow < body * 0.5 and
            c[-2] < o[-2]):
            patterns.append({
                "name": "INVERTED_HAMMER",
                "type": "bullish",
                "description": "Ters Cekic - Alim baskisi",
            })
            total_score += 10

        # --- SHOOTING STAR (Yükseliş sonrası) ---
        if (upper_shadow > body * 2 and
            lower_shadow < body * 0.5 and
            c[-2] > o[-2]):  # Önceki mum yükseliş
            patterns.append({
                "name": "SHOOTING_STAR",
                "type": "bearish",
                "description": "Kayan Yildiz - Satis baskisi",
            })
            total_score -= 15

        # --- BULLISH ENGULFING ---
        if (c[i] > o[i] and  # Son mum yeşil
            c[-2] < o[-2] and  # Önceki mum kırmızı
            c[i] > o[-2] and  # Son kapanış > önceki açılış
            o[i] < c[-2]):  # Son açılış < önceki kapanış
            patterns.append({
                "name": "BULLISH_ENGULFING",
                "type": "bullish",
                "description": "Yutan Formasyon - Guclu alis",
            })
            total_score += 20

        # --- BEARISH ENGULFING ---
        if (c[i] < o[i] and  # Son mum kırmızı
            c[-2] > o[-2] and  # Önceki mum yeşil
            c[i] < o[-2] and
            o[i] > c[-2]):
            patterns.append({
                "name": "BEARISH_ENGULFING",
                "type": "bearish",
                "description": "Yutan Formasyon - Guclu satis",
            })
            total_score -= 20

        # --- MORNING STAR (3 mumlu dönüş) ---
        if len(df) >= 4:
            # 1. mum: Uzun kırmızı
            # 2. mum: Küçük gövde (kararsızlık)
            # 3. mum: Uzun yeşil
            body_3 = abs(c[-3] - o[-3])
            body_2 = abs(c[-2] - o[-2])
            body_1 = abs(c[-1] - o[-1])
            range_3 = h[-3] - l[-3] if h[-3] != l[-3] else 1

            if (c[-3] < o[-3] and  # İlk mum kırmızı
                body_2 < body_3 * 0.3 and  # Ortadaki küçük
                c[-1] > o[-1] and  # Son mum yeşil
                body_1 > body_3 * 0.5):  # Son mum yeterince büyük
                patterns.append({
                    "name": "MORNING_STAR",
                    "type": "bullish",
                    "description": "Sabah Yildizi - Guclu donus sinyali",
                })
                total_score += 25

        # --- EVENING STAR (3 mumlu düşüş) ---
        if len(df) >= 4:
            body_3 = abs(c[-3] - o[-3])
            body_2 = abs(c[-2] - o[-2])
            body_1 = abs(c[-1] - o[-1])

            if (c[-3] > o[-3] and  # İlk mum yeşil
                body_2 < body_3 * 0.3 and
                c[-1] < o[-1] and  # Son mum kırmızı
                body_1 > body_3 * 0.5):
                patterns.append({
                    "name": "EVENING_STAR",
                    "type": "bearish",
                    "description": "Aksam Yildizi - Dusus sinyali",
                })
                total_score -= 25

        # Sinyal
        if total_score > 10:
            signal = "BUY"
        elif total_score < -10:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        return {
            "patterns": patterns,
            "signal": signal,
            "score": total_score,
        }

    # ============================================================
    # 5. DISCRETIONARY FORMASYONLAR (INSAN GOZU)
    # ============================================================

    def _find_swing_points(self, df, window=5):
        """Swing High/Low pivot noktalarini bul."""
        highs = df["high"].values
        lows = df["low"].values
        swing_highs = []
        swing_lows = []
        for i in range(window, len(df) - window):
            if highs[i] == max(highs[i-window:i+window+1]):
                swing_highs.append((i, highs[i]))
            if lows[i] == min(lows[i-window:i+window+1]):
                swing_lows.append((i, lows[i]))
        return swing_highs, swing_lows

    def detect_head_shoulders(self, df, tolerance=0.015):
        """Head & Shoulders — guclu dusus formasyonu."""
        if len(df) < 60:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        swing_highs, _ = self._find_swing_points(df, window=5)
        if len(swing_highs) < 3:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        sh1, sh2, sh3 = swing_highs[-3], swing_highs[-2], swing_highs[-1]
        head, left_s, right_s = sh2[1], sh1[1], sh3[1]
        if head > left_s and head > right_s:
            if abs(left_s - right_s) / left_s < tolerance * 2:
                neckline = df["low"].iloc[sh1[0]:sh3[0]+1].min()
                if df["close"].iloc[-1] < neckline * 1.01:
                    return {"detected": True, "pattern": "HEAD_SHOULDERS",
                            "signal": "SELL", "score": -30,
                            "description": "Head & Shoulders - Guclu dusus!"}
        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    def detect_inverse_head_shoulders(self, df, tolerance=0.015):
        """Inverse H&S — guclu yukselis formasyonu."""
        if len(df) < 60:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        _, swing_lows = self._find_swing_points(df, window=5)
        if len(swing_lows) < 3:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        sl1, sl2, sl3 = swing_lows[-3], swing_lows[-2], swing_lows[-1]
        head, left_s, right_s = sl2[1], sl1[1], sl3[1]
        if head < left_s and head < right_s:
            if abs(left_s - right_s) / left_s < tolerance * 2:
                neckline = df["high"].iloc[sl1[0]:sl3[0]+1].max()
                if df["close"].iloc[-1] > neckline * 0.99:
                    return {"detected": True, "pattern": "INVERSE_H_S",
                            "signal": "BUY", "score": 30,
                            "description": "Ters H&S - Guclu yukselis!"}
        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    def detect_triangle(self, df):
        """Ascending/Descending Triangle formasyonu."""
        if len(df) < 40:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        swing_highs, swing_lows = self._find_swing_points(df, window=4)
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        hv = [h[1] for h in swing_highs[-3:]]
        lv = [l[1] for l in swing_lows[-3:]]
        h_flat = all(abs(hv[i] - hv[0]) / hv[0] < 0.015 for i in range(len(hv)))
        l_rising = all(lv[i] <= lv[i+1] for i in range(len(lv)-1))
        h_falling = all(hv[i] >= hv[i+1] for i in range(len(hv)-1))
        l_flat = all(abs(lv[i] - lv[0]) / lv[0] < 0.015 for i in range(len(lv)))
        if h_flat and l_rising:
            if df["close"].iloc[-1] > np.mean(hv) * 0.99:
                return {"detected": True, "pattern": "ASC_TRIANGLE",
                        "signal": "BUY", "score": 25,
                        "description": "Yukselen Ucgen - Breakout!"}
        if l_flat and h_falling:
            if df["close"].iloc[-1] < np.mean(lv) * 1.01:
                return {"detected": True, "pattern": "DESC_TRIANGLE",
                        "signal": "SELL", "score": -25,
                        "description": "Dusen Ucgen - Breakdown!"}
        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    def detect_flag(self, df, trend_bars=15, flag_bars=10):
        """Bull/Bear Flag — devam formasyonu."""
        if len(df) < trend_bars + flag_bars + 5:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        trend_end = -flag_bars
        trend_start = -(trend_bars + flag_bars)
        trend_chg = (df["close"].iloc[trend_end] - df["close"].iloc[trend_start]) / df["close"].iloc[trend_start]
        flag_data = df.iloc[-flag_bars:]
        flag_range = (flag_data["high"].max() - flag_data["low"].min()) / flag_data["close"].mean()
        if trend_chg > 0.05 and flag_range < 0.03:
            if df["close"].iloc[-1] > flag_data["high"].max() * 0.995:
                return {"detected": True, "pattern": "BULL_FLAG",
                        "signal": "BUY", "score": 20,
                        "description": f"Boga Bayragi - %{trend_chg*100:.0f} devam!"}
        if trend_chg < -0.05 and flag_range < 0.03:
            if df["close"].iloc[-1] < flag_data["low"].min() * 1.005:
                return {"detected": True, "pattern": "BEAR_FLAG",
                        "signal": "SELL", "score": -20,
                        "description": f"Ayi Bayragi - %{abs(trend_chg)*100:.0f} devam!"}
        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    def detect_cup_handle(self, df, lookback=60):
        """Cup & Handle — guclu yukselis formasyonu."""
        if len(df) < lookback:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        closes = df.tail(lookback)["close"].values
        cup_start = np.mean(closes[:5])
        cup_end = np.mean(closes[-10:-5]) if len(closes) > 15 else closes[-1]
        cup_bottom = min(closes[10:-10]) if len(closes) > 25 else min(closes)
        cup_depth = (cup_start - cup_bottom) / cup_start if cup_start > 0 else 0
        edge_diff = abs(cup_start - cup_end) / cup_start if cup_start > 0 else 1
        if 0.03 < cup_depth < 0.30 and edge_diff < 0.03:
            handle = closes[-5:]
            handle_drop = (max(handle) - min(handle)) / max(handle) if max(handle) > 0 else 1
            if handle_drop < cup_depth * 0.5 and closes[-1] > max(cup_start, cup_end) * 0.98:
                return {"detected": True, "pattern": "CUP_HANDLE",
                        "signal": "BUY", "score": 30,
                        "description": f"Fincan & Kulp - %{cup_depth*100:.0f} derinlik!"}
        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    def detect_wedge(self, df, lookback=30):
        """Rising/Falling Wedge formasyonu."""
        if len(df) < lookback:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        recent = df.tail(lookback)
        sh, sl = self._find_swing_points(recent, window=3)
        if len(sh) < 3 or len(sl) < 3:
            return {"detected": False, "signal": "NEUTRAL", "score": 0}
        hv = [h[1] for h in sh[-3:]]
        lv = [l[1] for l in sl[-3:]]
        h_up = all(hv[i] < hv[i+1] for i in range(len(hv)-1))
        l_up = all(lv[i] < lv[i+1] for i in range(len(lv)-1))
        h_dn = all(hv[i] > hv[i+1] for i in range(len(hv)-1))
        l_dn = all(lv[i] > lv[i+1] for i in range(len(lv)-1))
        narrowing = (hv[-1] - lv[-1]) < (hv[0] - lv[0]) * 0.7
        if h_up and l_up and narrowing:
            return {"detected": True, "pattern": "RISING_WEDGE",
                    "signal": "SELL", "score": -20,
                    "description": "Yukselen Kama - Dusus bekleniyor!"}
        if h_dn and l_dn and narrowing:
            return {"detected": True, "pattern": "FALLING_WEDGE",
                    "signal": "BUY", "score": 20,
                    "description": "Dusen Kama - Yukselis bekleniyor!"}
        return {"detected": False, "signal": "NEUTRAL", "score": 0}

    # ============================================================
    # 6. KAPSAMLI ANALIZ (TUM DESENLER)
    # ============================================================

    def analyze_all(self, df: pd.DataFrame) -> Dict:
        """Tum desen analizlerini calistirir ve birlestirilmis skor verir."""
        total_score = 0
        reasons = []

        # Temel analizler
        for name, func in [
            ("Fib", lambda: self.fibonacci_levels(df)),
            ("S/R", lambda: self.support_resistance(df)),
            ("DT", lambda: self.detect_double_top(df)),
            ("DB", lambda: self.detect_double_bottom(df)),
            ("Mum", lambda: self.detect_candlestick_patterns(df)),
        ]:
            try:
                r = func()
                total_score += r.get("score", 0)
                if name == "Fib" and r["score"] != 0:
                    reasons.append(f"Fib:{r.get('nearest_level','?')}%")
                elif name == "S/R" and r["score"] > 0:
                    reasons.append(f"Destek")
                elif name == "S/R" and r["score"] < 0:
                    reasons.append(f"Direnc")
                elif name == "DT" and r.get("detected"):
                    reasons.append("IKILI_TEPE!")
                elif name == "DB" and r.get("detected"):
                    reasons.append("IKILI_DIP!")
                elif name == "Mum":
                    for p in r.get("patterns", []):
                        reasons.append(f"Mum:{p['name']}")
            except Exception:
                pass

        # Discretionary formasyonlar
        for func in [
            self.detect_head_shoulders,
            self.detect_inverse_head_shoulders,
            self.detect_triangle,
            self.detect_flag,
            self.detect_cup_handle,
            self.detect_wedge,
        ]:
            try:
                r = func(df)
                total_score += r.get("score", 0)
                if r.get("detected"):
                    reasons.append(f"{r['pattern']}!")
            except Exception:
                pass

        # Sinyal
        if total_score >= 25:
            sig = "STRONG_BUY"
        elif total_score >= 10:
            sig = "BUY"
        elif total_score <= -25:
            sig = "STRONG_SELL"
        elif total_score <= -10:
            sig = "SELL"
        else:
            sig = "NEUTRAL"

        return {"pattern_score": total_score, "pattern_signal": sig, "reasons": reasons}

