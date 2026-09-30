FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY deploy/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r /tmp/requirements-runtime.txt
COPY backend /app/backend
COPY css /app/css
COPY js /app/js
COPY assets/paintings /app/assets/paintings
COPY reader.html index.html /app/
USER 1000:1000
ENV HF_HOME=/models OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    MELOS_PUBLIC_DEPLOYMENT=1
EXPOSE 8791
CMD ["python", "-m", "uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8791", "--workers", "1", "--limit-concurrency", "8", "--timeout-keep-alive", "5", "--no-access-log"]
