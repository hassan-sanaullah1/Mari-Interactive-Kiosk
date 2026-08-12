# MARI × speech-to-speech. s2s is GPU-oriented (local Whisper/Kokoro); use a CUDA
# base in production. This slim image is fine for the cloud-provider (Urdu) path and
# CPU testing.
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential \
    libavformat59 libavcodec59 libavdevice59 libavutil57 libswresample4 libswscale6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mari_s2s /app/mari_s2s
COPY scripts /app/scripts

# Default to the English (built-ins) pipeline; override CMD for Urdu.
CMD ["bash", "scripts/run_en.sh"]
