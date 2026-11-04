# syntax=docker/dockerfile:1
# MARI backend — FastAPI web server (server/app.py). CPU image by default: local English
# STT (faster-whisper) and everything else is plain HTTP/WebSocket calls to external
# providers (vLLM, Soniox, Uplift) plus gRPC to the Audio2Face-3D NIM. No GPU needed,
# unless INSTALL_CUDA=true puts the STT model on one (docker-compose.cuda.yml).
#
# Layers run from slowest-changing to fastest, so a code change rebuilds only the last
# one. Exact version pinned so the early layers stay cached between builds.
FROM python:3.11.17-slim-bookworm

# 1. System packages. Change almost never.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libavformat59 libavcodec59 libavdevice59 libavutil57 libswresample4 libswscale6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Dependencies. Rebuilt only when requirements.txt or the vendored wheel changes; the
#    cache mount keeps already-downloaded wheels out of the image and across rebuilds.
#    INSTALL_KOKORO opts into the local Kokoro English voice (torch, transformers,
#    spacy); default off, so the normal build and the deployed image stay without them.
#    INSTALL_CUDA opts into running the English STT model on the GPU (cuBLAS, cuDNN);
#    also default off, for the same reason.
ARG INSTALL_KOKORO=false
ARG INSTALL_CUDA=false
COPY requirements.txt requirements-kokoro.txt requirements-cuda.txt /app/
COPY vendor /app/vendor
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && pip install --no-deps /app/vendor/nvidia_ace-1.2.0-py3-none-any.whl \
    && if [ "$INSTALL_KOKORO" = "true" ]; then pip install -r requirements-kokoro.txt; fi \
    && if [ "$INSTALL_CUDA" = "true" ]; then pip install -r requirements-cuda.txt; fi

# ctranslate2 dlopen()s cuBLAS and cuDNN by bare soname, and pip puts them under the
# nvidia/* packages rather than on the default loader path. Harmless when INSTALL_CUDA
# is false: the directories simply do not exist and the loader skips them.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib

# 3. Source code. The knowledge base, prompts and normalization all live inside server/.
COPY server /app/server

ENV MARI_HOST=0.0.0.0
ENV MARI_PORT=8010
EXPOSE 8010

# Ready, not merely alive: 503 when the LLM is unconfigured or Qdrant is unreachable.
# urlopen raises on a 503, so the check fails. No curl in this image, hence python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health/ready', timeout=4)"]

# No uvicorn access log: the app logs every request itself, with its request ID and
# duration, and keeps the 30 s health probes out of the log (server/app.py).
CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
