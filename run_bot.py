"""
Stock Bot Watchdog — Botu 7/24 canlı tutar.
Bot çökerse otomatik yeniden başlatır.

Kullanım:
    python run_bot.py              # Paper trading
    python run_bot.py --live       # Gerçek para (dikkat!)

Durdurmak için:
    Ctrl+C veya STOP_BOT dosyası oluştur
"""
import os
import sys
import time
import subprocess
import signal
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "stock_bot.py")
STOP_FILE = os.path.join(SCRIPT_DIR, "STOP_BOT")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")

MAX_RESTARTS = 50          # Gunluk max yeniden baslatma
RESTART_DELAY_BASE = 30    # Ilk bekleme 30 saniye
RESTART_DELAY_MAX = 600    # Max bekleme 10 dakika
HEALTH_CHECK_INTERVAL = 60 # Her 60 saniyede kontrol

os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[WATCHDOG {ts}] {msg}"
    print(line, flush=True)  # Docker/Coolify loglarında anında görünsün
    log_file = os.path.join(LOG_DIR, f"watchdog_{datetime.now().strftime('%Y-%m-%d')}.log")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Container'da dosya yazılamazsa devam et


def should_stop():
    """STOP_BOT dosyasi varsa dur."""
    return os.path.exists(STOP_FILE)


def run_bot(live_mode=False):
    """Botu başlat ve izle."""
    args = [sys.executable, "-u", BOT_SCRIPT]
    if live_mode:
        args.append("--live")

    log(f"Bot baslatiliyor: {' '.join(args)}")

    try:
        process = subprocess.Popen(
            args,
            cwd=SCRIPT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        log(f"Bot PID: {process.pid}")

        # Çıktıyı oku ve logla
        last_heartbeat = time.time()
        while process.poll() is None:
            if should_stop():
                log("STOP_BOT dosyasi algilandi, bot durduruluyor...")
                process.terminate()
                process.wait(timeout=10)
                return "STOPPED"

            line = process.stdout.readline()
            if line:
                # Bot çıktısını stdout'a yaz + flush (Docker/Coolify uyumlu)
                print(line.rstrip(), flush=True)

            # Heartbeat: her 5 dakikada bir watchdog'un yaşadığını logla
            now = time.time()
            if now - last_heartbeat > 300:  # 5 dakika
                log(f"HEARTBEAT: Watchdog alive, bot PID={process.pid}")
                last_heartbeat = now

        exit_code = process.returncode
        log(f"Bot kapandi - Exit code: {exit_code}")
        return exit_code

    except KeyboardInterrupt:
        log("Ctrl+C algilandi, bot durduruluyor...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return "INTERRUPTED"

    except Exception as e:
        log(f"HATA: {e}")
        return "ERROR"


def main():
    live_mode = "--live" in sys.argv

    mode_str = "CANLI (GERCEK PARA!)" if live_mode else "PAPER (SANAL)"
    log("=" * 60)
    log(f"  STOCK BOT WATCHDOG BASLATILDI")
    log(f"  Mod: {mode_str}")
    log(f"  Max yeniden baslatma: {MAX_RESTARTS}/gun")
    log(f"  Durdurmak icin: STOP_BOT dosyasi olustur veya Ctrl+C")
    log("=" * 60)

    if should_stop():
        os.remove(STOP_FILE)
        log("Eski STOP_BOT dosyasi silindi")

    restart_count = 0
    last_reset = datetime.now()
    consecutive_fails = 0

    while True:
        # Gunluk sayac sifirla
        if (datetime.now() - last_reset).total_seconds() > 86400:
            restart_count = 0
            last_reset = datetime.now()
            log("Gunluk yeniden baslatma sayaci sifirlandi")

        if restart_count >= MAX_RESTARTS:
            log(f"KRITIK: Gunluk max yeniden baslatma ({MAX_RESTARTS}) asildi!")
            log("Bot otomatik olarak yarın sıfırlanacak. Manuel kontrol gerekli.")
            time.sleep(3600)  # 1 saat bekle
            continue

        if should_stop():
            log("STOP_BOT dosyasi mevcut, cikiliyor...")
            break

        # Botu calistir
        result = run_bot(live_mode)

        if result == "STOPPED" or result == "INTERRUPTED":
            log("Bot kullanici tarafindan durduruldu")
            break

        # Yeniden baslatma mantigi
        restart_count += 1

        if result == 0:
            # Normal cikis (kill switch tetiklendi vs.)
            consecutive_fails = 0
            delay = RESTART_DELAY_BASE
            log(f"Bot normal kapandi, {delay}s sonra yeniden baslatilacak...")
        else:
            # Hata ile cikis
            consecutive_fails += 1
            delay = min(RESTART_DELAY_BASE * (2 ** consecutive_fails), RESTART_DELAY_MAX)
            log(f"Bot hata ile kapandi (#{consecutive_fails}), {delay}s sonra yeniden baslatilacak...")

        log(f"Yeniden baslatma #{restart_count}/{MAX_RESTARTS}")

        # Bekleme (STOP_BOT kontrolu ile)
        waited = 0
        while waited < delay:
            if should_stop():
                log("Bekleme sirasinda STOP_BOT algilandi")
                break
            time.sleep(5)
            waited += 5

        if should_stop():
            break

    log("Watchdog kapaniyor")

    # Temizlik
    if should_stop() and os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)


if __name__ == "__main__":
    main()
