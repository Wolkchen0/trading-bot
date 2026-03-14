FROM python:3.12-slim

WORKDIR /app

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyaları
COPY . .

# Log klasörünü oluştur
RUN mkdir -p logs

# Bot'u başlat
CMD ["python", "-u", "crypto_bot.py"]
