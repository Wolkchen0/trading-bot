"""
TradingView Webhook Receiver
TradingView'dan gelen AL/SAT sinyallerini alır ve otomatik işlem yapar.

Kullanım:
1. TradingView'da strateji oluştur
2. Alert ekle → Webhook URL: http://localhost:5000/webhook
3. Alert mesajı formatı (JSON):
   {
     "action": "buy",
     "symbol": "AAPL",
     "price": 150.50,
     "qty": 10,
     "strategy": "my_strategy"
   }
"""
import json
from datetime import datetime
from typing import Dict, Optional, Callable
from flask import Flask, request, jsonify
from utils.logger import logger
import threading


class WebhookReceiver:
    """TradingView webhook alıcı sınıfı."""

    def __init__(self, port: int = 5000, secret_key: str = ""):
        self.app = Flask(__name__)
        self.port = port
        self.secret_key = secret_key
        self.on_signal_callback: Optional[Callable] = None
        self.received_signals = []
        self._setup_routes()
        logger.info(f"WebhookReceiver oluşturuldu (port: {port})")

    def _setup_routes(self):
        """Flask route'larını ayarlar."""

        @self.app.route("/webhook", methods=["POST"])
        def webhook():
            try:
                data = request.json
                if not data:
                    return jsonify({"error": "JSON body gerekli"}), 400

                # Secret key kontrolü (opsiyonel güvenlik)
                if self.secret_key:
                    token = data.get("secret", "") or request.headers.get("X-Secret", "")
                    if token != self.secret_key:
                        logger.warning("⚠️ Webhook: Geçersiz secret key")
                        return jsonify({"error": "Yetkisiz"}), 401

                # Sinyal parse et
                signal = self._parse_signal(data)
                if signal:
                    self.received_signals.append(signal)
                    logger.info(
                        f"📩 Webhook sinyali: {signal['action'].upper()} "
                        f"{signal.get('qty', '?')} {signal['symbol']} "
                        f"@ ${signal.get('price', '?')}"
                    )

                    # Callback varsa çağır
                    if self.on_signal_callback:
                        self.on_signal_callback(signal)

                    return jsonify({"status": "ok", "signal": signal}), 200
                else:
                    return jsonify({"error": "Geçersiz sinyal formatı"}), 400

            except Exception as e:
                logger.error(f"Webhook hatası: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/health", methods=["GET"])
        def health():
            return jsonify({
                "status": "running",
                "signals_received": len(self.received_signals),
                "timestamp": datetime.now().isoformat(),
            })

        @self.app.route("/signals", methods=["GET"])
        def signals():
            return jsonify(self.received_signals[-50:])  # Son 50 sinyal

    def _parse_signal(self, data: Dict) -> Optional[Dict]:
        """Webhook verisini standart sinyal formatına çevirir."""
        action = data.get("action", "").lower()
        symbol = data.get("symbol", data.get("ticker", ""))

        if not action or not symbol:
            return None

        if action not in ["buy", "sell", "close"]:
            return None

        return {
            "action": action,
            "symbol": symbol.upper().replace("NASDAQ:", "").replace("NYSE:", ""),
            "price": data.get("price", 0),
            "qty": data.get("qty", data.get("quantity", 0)),
            "strategy": data.get("strategy", "tradingview"),
            "message": data.get("message", ""),
            "timestamp": datetime.now().isoformat(),
            "source": "tradingview_webhook",
        }

    def set_callback(self, callback: Callable):
        """Sinyal geldiğinde çağrılacak fonksiyonu ayarlar."""
        self.on_signal_callback = callback

    def start(self, threaded: bool = True):
        """Webhook sunucusunu başlatır."""
        if threaded:
            thread = threading.Thread(
                target=lambda: self.app.run(
                    host="0.0.0.0", port=self.port, debug=False
                ),
                daemon=True,
            )
            thread.start()
            logger.info(f"🌐 Webhook sunucusu başlatıldı: http://localhost:{self.port}/webhook")
        else:
            self.app.run(host="0.0.0.0", port=self.port, debug=False)

    def get_last_signal(self) -> Optional[Dict]:
        """Son alınan sinyali döndürür."""
        return self.received_signals[-1] if self.received_signals else None
