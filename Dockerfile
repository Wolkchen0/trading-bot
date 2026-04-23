FROM python:3.12-slim

# Python stdout buffer'ını kapat — loglar anında Docker'a yazılsın
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Python bağımlılıkları (ONNX Runtime — PyTorch yok, RAM 150MB)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FinBERT ONNX modelini build sırasında indir (container başlarken bekleme yok)
# PyTorch/optimum KULLANILMIYOR — sadece pre-exported model indiriliyor
# RAM kullanımı: ~200MB (eskiden 2GB+ idi)
RUN python -c "\
from huggingface_hub import hf_hub_download; \
import os, shutil; \
cache_dir = '/app/models/finbert'; \
os.makedirs(cache_dir, exist_ok=True); \
print('Downloading FinBERT tokenizer files...'); \
for f in ['tokenizer.json', 'tokenizer_config.json', 'vocab.txt', 'special_tokens_map.json']: \
    try: \
        hf_hub_download('ProsusAI/finbert', f, local_dir=cache_dir); \
        print(f'  ✓ {f}'); \
    except Exception as e: \
        print(f'  ✗ {f}: {e}'); \
print('Downloading pre-exported ONNX model...'); \
try: \
    onnx_file = hf_hub_download('philschmid/finbert-onnx', 'model.onnx', cache_dir='/tmp/onnx'); \
    shutil.copy2(onnx_file, os.path.join(cache_dir, 'model.onnx')); \
    print('  ✓ model.onnx (pre-exported, no PyTorch needed)'); \
except Exception as e: \
    print(f'  ✗ ONNX model download failed: {e}'); \
    print('  Will use VADER fallback at runtime'); \
" || echo "Model pre-download failed, will download at runtime"

# HuggingFace cache temizle (Docker image küçültsün)
RUN rm -rf /root/.cache/huggingface /tmp/onnx

# Uygulama dosyaları
COPY . .

# Log klasörünü oluştur
RUN mkdir -p logs

# STOCK BOT: Ana botu çalıştır
CMD ["python", "-u", "stock_bot.py"]
