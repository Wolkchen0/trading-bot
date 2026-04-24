FROM python:3.12-slim

# Python stdout buffer'ını kapat — loglar anında Docker'a yazılsın
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Python bağımlılıkları (ONNX Runtime — PyTorch yok, RAM 150MB)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FinBERT ONNX modelini build sırasında indir (container başlarken bekleme yok)
# PyTorch/optimum KULLANILMIYOR — sadece pre-exported model indiriliyor
# Kaynak: jonngan/finbert-onnx (~440MB, BERT ONNX + tokenizer)
# RAM kullanımı: ~200MB (eskiden 2GB+ idi)
RUN python -c "\
from huggingface_hub import hf_hub_download; \
import os; \
cache_dir = '/app/models/finbert'; \
os.makedirs(cache_dir, exist_ok=True); \
repo = 'jonngan/finbert-onnx'; \
files = ['model.onnx', 'tokenizer.json', 'tokenizer_config.json', 'vocab.txt', 'special_tokens_map.json', 'config.json']; \
print(f'Downloading FinBERT ONNX from {repo}...'); \
for f in files: \
    try: \
        hf_hub_download(repo, f, local_dir=cache_dir); \
        size = os.path.getsize(os.path.join(cache_dir, f)); \
        print(f'  ✓ {f} ({size/1024/1024:.1f}MB)'); \
    except Exception as e: \
        print(f'  ✗ {f}: {e}'); \
print('FinBERT ONNX download complete.'); \
# Kritik dosyalari dogrula \
model_ok = os.path.exists(os.path.join(cache_dir, 'model.onnx')); \
tok_ok = os.path.exists(os.path.join(cache_dir, 'tokenizer.json')); \
print(f'Dogrulama: model.onnx={model_ok}, tokenizer.json={tok_ok}'); \
if not model_ok or not tok_ok: \
    print('UYARI: Kritik dosyalar eksik! FinBERT VADER fallback ile calisacak.'); \
" || echo "Model pre-download failed, will download at runtime"

# HuggingFace cache temizle (Docker image küçültsün)
RUN rm -rf /root/.cache/huggingface

# Uygulama dosyaları
COPY . .

# Log klasörünü oluştur
RUN mkdir -p logs

# STOCK BOT: Ana botu çalıştır
CMD ["python", "-u", "stock_bot.py"]
