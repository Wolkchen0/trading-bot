FROM python:3.12-slim

# Python stdout buffer'ını kapat — loglar anında Docker'a yazılsın
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Python bağımlılıkları (ONNX Runtime — PyTorch yok, RAM 150MB)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FinBERT ONNX modelini build sırasında indir (container başlarken bekleme yok)
RUN python -c "\
from huggingface_hub import hf_hub_download; \
import os; \
cache_dir = '/app/models/finbert'; \
os.makedirs(cache_dir, exist_ok=True); \
print('Downloading FinBERT tokenizer...'); \
hf_hub_download('ProsusAI/finbert', 'tokenizer.json', local_dir=cache_dir); \
hf_hub_download('ProsusAI/finbert', 'tokenizer_config.json', local_dir=cache_dir); \
hf_hub_download('ProsusAI/finbert', 'vocab.txt', local_dir=cache_dir); \
hf_hub_download('ProsusAI/finbert', 'special_tokens_map.json', local_dir=cache_dir); \
print('FinBERT tokenizer cached.'); \
" || echo "Tokenizer pre-download failed, will download at runtime"

# ONNX model export (optimum ile — build sırasında bir kere)
RUN pip install --no-cache-dir optimum[onnxruntime] && \
    python -c "\
from optimum.onnxruntime import ORTModelForSequenceClassification; \
from transformers import AutoTokenizer; \
print('Exporting FinBERT to ONNX...'); \
model = ORTModelForSequenceClassification.from_pretrained('ProsusAI/finbert', export=True); \
model.save_pretrained('/app/models/finbert'); \
tokenizer = AutoTokenizer.from_pretrained('ProsusAI/finbert'); \
tokenizer.save_pretrained('/app/models/finbert'); \
print('FinBERT ONNX export complete.'); \
" && \
    pip uninstall -y optimum torch transformers && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/huggingface /root/.cache/pip || \
    echo "ONNX export failed, will use VADER fallback"

# Uygulama dosyaları
COPY . .

# Log klasörünü oluştur
RUN mkdir -p logs

# STOCK BOT: Ana botu çalıştır
CMD ["python", "-u", "stock_bot.py"]
