#!/usr/bin/env bash
# English pipeline — 100% s2s BUILT-INS, no custom handlers.
#   STT: faster-whisper   LLM: chat-completions -> vLLM (Qwen3.5)   TTS: kokoro-82m
#
# NOTE: s2s's exact flag names evolve between commits. Confirm them once with:
#   python -m speech_to_speech.s2s_pipeline --help
# then adjust below. Values are read from .env (APP_* vars).
set -euo pipefail
set -a; [ -f .env ] && . ./.env; set +a

python -m speech_to_speech.s2s_pipeline \
  --mode websocket \
  --stt faster-whisper \
  --stt_model_name "${APP_ASR_MODEL_SIZE:-large-v3-turbo}" \
  --llm_backend chat-completions \
  --model_name "${APP_VLLM_MODEL:-qwen3.5}" \
  --chat_completions_base_url "${APP_VLLM_API_BASE}" \
  --chat_completions_api_key "${APP_VLLM_API_KEY:-EMPTY}" \
  --tts kokoro
