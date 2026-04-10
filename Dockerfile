FROM python:3.12-slim

# Python stdout buffer'ını kapat — loglar anında Docker'a yazılsın
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Python bağımlılıkları (torch CPU-only: ~400MB vs full ~2.5GB)
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Uygulama dosyaları
COPY . .

# Log klasörünü oluştur
RUN mkdir -p logs

# STOCK BOT: Ana botu çalıştır
CMD ["python", "-u", "stock_bot.py"]
