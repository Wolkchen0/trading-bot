"""
Loglama Sistemi - Tüm bot aktivitelerini loglar.
Process ID ekleyerek çift instance sorunlarını tespit eder.
"""
import logging
import os
import sys
from datetime import datetime
from config import LOG_CONFIG


def setup_logger(name: str = "TradingBot") -> logging.Logger:
    """Ana logger'ı oluşturur ve yapılandırır. PID ile çoklu instance tespiti."""
    log_dir = LOG_CONFIG["log_dir"]
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_CONFIG["log_level"]))

    # Dosya handler - her gün ayrı log
    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"bot_{today}.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)

    # Konsol handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Format — PID eklendi (çift instance tespiti için)
    pid = os.getpid()
    formatter = logging.Formatter(
        f"%(asctime)s | %(levelname)-8s | %(name)s[{pid}] | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


# Global logger instance
logger = setup_logger()
