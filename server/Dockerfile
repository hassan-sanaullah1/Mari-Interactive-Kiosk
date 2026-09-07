# MARI backend — FastAPI web server (server/app.py). CPU image: local English STT
# (faster-whisper) and everything else is plain HTTP/WebSocket calls to external
# providers (vLLM, Soniox, Uplift) plus gRPC to the Audio2Face-3D NIM. No GPU needed
# here even though faster-whisper *can* use one — see mari_s2s' own Dockerfile
# (repo root) for the GPU-oriented local speech-to-speech pipeline instead.
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libavformat59 libavcodec59 libavdevice59 libavutil57 libswresample4 libswscale6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-web.txt /app/requirements-web.txt
COPY vendor /app/vendor
RUN pip install --no-cache-dir -r requirements-web.txt \
    && pip install --no-cache-dir --no-deps /app/vendor/nvidia_ace-1.2.0-py3-none-any.whl

COPY server /app/server
# the knowledge base ships inside server/data/, so `COPY server` above already has it
# Persona prompts, the abbreviation glossary and the spoken-form fixes. server/ imports
# these through a try/except ImportError with a working fallback, so leaving this out
# does not crash the app — it silently serves the pre-voice_config behaviour instead,
# which is exactly the kind of "my changes aren't live" bug that is hard to spot.
COPY voice_config /app/voice_config
COPY web /app/web

ENV MARI_HOST=0.0.0.0
ENV MARI_PORT=8010
EXPOSE 8010

CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8010"]
