"""
Trade Gates — Alım Filtre Sistemi

CryptoBot ana döngüsündeki 8 gate filtresini merkezi bir modülde toplar.
Her gate bağımsız çalışır, herhangi biri blok ederse alım yapılmaz.

Gates:
1. EMA200 Trend Gate
2. Zaman Filtresi (düşük likidite saatleri)
3. Kayıp Serisi Koruyucu
4. Coin Filtresi (ardışık zarar)
5. R:R Gate (Risk/Ödül oranı)
6. Multi-Timeframe Onay
7. Volatilite Filtresi
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

from ta.trend import EMAIndicator

from utils.logger import logger


class TradeGates:
    """Alım öncesi tüm güvenlik filtrelerini kontrol eder."""

    def __init__(self, bot):
        self.bot = bot

    def check_all_gates(self, symbol: str, analysis: Dict, config: Dict) -> Tuple[bool, str]:
        """
        Tüm gate'leri kontrol eder.
        
        Returns:
            (passed: bool, block_reason: str)
            passed=True ise alım yapılabilir
        """
        if analysis["signal"] != "BUY":
            return True, ""  # Gate'ler sadece BUY sinyallerini filtreler

        # 1. EMA200 Trend Gate
        if config.get("ema200_trend_gate", True):
            if not analysis.get("above_ema200", True):
                logger.debug(f"  {symbol} EMA200 GATE: Fiyat EMA200 altinda, BUY engellendi")
                return False, "EMA200"

        # 2. Zaman Filtresi
        if config.get("time_filter_enabled", True):
            utc_hour = datetime.now(timezone.utc).hour
            start_h = config.get("time_filter_start_utc", 0)
            end_h = config.get("time_filter_end_utc", 6)
            if start_h <= utc_hour < end_h:
                logger.debug(f"  {symbol} ZAMAN GATE: UTC {utc_hour}:00 dusuk likidite, BUY engellendi")
                return False, "TIME"

        # 3. Kayıp Serisi Koruyucu
        blocked, reason = self._check_loss_streak(symbol, analysis, config)
        if blocked:
            return False, reason

        # 4. Coin Filtresi
        if config.get("coin_filter_enabled", True):
            coin_losses = getattr(self.bot, '_coin_consecutive_losses', {}).get(symbol, 0)
            max_coin_losses = config.get("coin_max_consecutive_losses", 3)
            if coin_losses >= max_coin_losses:
                logger.info(f"  {symbol} COIN FILTRE: {coin_losses} ardisik zarar, bu coin devre disi")
                return False, "COIN_FILTER"

        # 5. R:R Gate
        if config.get("rr_gate_enabled", True):
            blocked, reason = self._check_rr_gate(symbol, analysis, config)
            if blocked:
                return False, reason

        # 6. Multi-Timeframe Onay
        if config.get("multi_tf_enabled", True):
            blocked, reason = self._check_mtf(symbol, config)
            if blocked:
                return False, reason

        # 7. Volatilite Filtresi
        if config.get("volatility_filter_enabled", True):
            atr_val = analysis.get("atr", 0)
            cur_price = analysis.get("price", 1)
            if atr_val > 0 and cur_price > 0:
                atr_pct = atr_val / cur_price
                max_atr = config.get("max_atr_pct", 0.06)
                if atr_pct > max_atr:
                    logger.debug(f"  {symbol} VOL GATE: ATR={atr_pct:.1%} > {max_atr:.0%}, cok volatil BUY engellendi")
                    return False, "VOLATILITY"

        return True, ""

    def _check_loss_streak(self, symbol: str, analysis: Dict, config: Dict) -> Tuple[bool, str]:
        """Kayıp serisi kontrolü."""
        bot = self.bot
        if not config.get("loss_streak_enabled", True):
            return False, ""

        loss_streak_count = getattr(bot, '_consecutive_losses', 0)

        # 5+ ardışık zarar → alım yasağı
        if loss_streak_count >= config.get("loss_streak_halt", 5):
            halt_until = getattr(bot, '_loss_halt_until', None)
            if halt_until is None or datetime.now() < halt_until:
                if halt_until is None:
                    halt_hours = config.get("loss_streak_halt_hours", 6)
                    bot._loss_halt_until = datetime.now() + timedelta(hours=halt_hours)
                    logger.warning(f"  ⚠️ {loss_streak_count} ardisik zarar! {halt_hours} saat alim yasagi")
                return True, "LOSS_STREAK_HALT"
            else:
                # Yasak bitti, sıfırla
                bot._consecutive_losses = 0
                bot._loss_halt_until = None

        # 3+ ardışık zarar → güven eşiği yükselt
        elif loss_streak_count >= config.get("loss_streak_warn", 3):
            elevated_conf = config.get("loss_streak_elevated_conf", 70)
            if analysis["confidence"] < elevated_conf:
                logger.info(
                    f"  {symbol} KAYIP KORUYUCU: {loss_streak_count} ardisik zarar, "
                    f"guven {analysis['confidence']}% < {elevated_conf}% gerekli"
                )
                return True, "LOSS_STREAK_WARN"

        return False, ""

    def _check_rr_gate(self, symbol: str, analysis: Dict, config: Dict) -> Tuple[bool, str]:
        """Risk/Ödül oranı kontrolü."""
        sl_pct = analysis.get("atr", 0)
        price = analysis.get("price", 0)
        tp_pct = config.get("take_profit_pct", 0.04)

        if sl_pct > 0 and price > 0:
            atr_pct = sl_pct / price
            actual_sl = atr_pct * config.get("atr_stop_multiplier", 1.5)
            actual_sl = max(actual_sl, config.get("stop_loss_pct", 0.015))
            actual_sl = min(actual_sl, config.get("stop_loss_max_pct", 0.04))
            rr_ratio = tp_pct / actual_sl if actual_sl > 0 else 0
            min_rr = config.get("min_rr_ratio", 2.0)
            if rr_ratio < min_rr:
                logger.debug(f"  {symbol} R:R GATE: {rr_ratio:.1f}:1 < {min_rr}:1, BUY engellendi")
                return True, "RR_GATE"

        return False, ""

    def _check_mtf(self, symbol: str, config: Dict) -> Tuple[bool, str]:
        """Multi-Timeframe onay kontrolü."""
        try:
            df_1h = self.bot.get_crypto_bars(symbol, days=14)
            if not df_1h.empty and len(df_1h) >= 50:
                df_4h = df_1h.resample('4h').agg({
                    'open': 'first', 'high': 'max',
                    'low': 'min', 'close': 'last',
                    'volume': 'sum'
                }).dropna()
                if len(df_4h) >= 20:
                    ema9_4h = EMAIndicator(df_4h['close'], window=9).ema_indicator().iloc[-1]
                    ema21_4h = EMAIndicator(df_4h['close'], window=21).ema_indicator().iloc[-1]
                    if ema9_4h < ema21_4h:
                        logger.debug(f"  {symbol} MTF GATE: 4h trend dususte (EMA9 < EMA21), BUY engellendi")
                        return True, "MTF"
        except Exception:
            pass  # Veri alınamazsa filtre uygulanmaz
        return False, ""
