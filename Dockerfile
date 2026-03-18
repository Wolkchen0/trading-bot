FROM python:3.12-slim

WORKDIR /app

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyaları
COPY . .

# Log klasörünü oluştur
RUN mkdir -p logs

# LIVE MOD: Watchdog ile botu calistir (--live parametresi)
CMD ["python", "-u", "run_bot.py", "--live"]
