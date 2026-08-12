#!/usr/bin/env bash
# Urdu pipeline — CUSTOM handlers (Soniox STT + Uplift TTS) + vLLM LLM.
#
# Prerequisite: the custom handlers must be registered so `--stt soniox` /
# `--tts uplift` resolve. Do ONE of (see docs/integration.md):
#   (a) drop-in:  copy mari_s2s/handlers/*.py into the s2s STT/ and TTS/ dirs and
#       add the two registry lines, OR
#   (b) runtime:  ensure `python -c "import mari_s2s.register as r; r.try_autoregister()"`
#       succeeds against your pinned s2s commit (a launcher can call it before build).
set -euo pipefail
set -a; [ -f .env ] && . ./.env; set +a

python -m speech_to_speech.s2s_pipeline \
  --mode websocket \
  --stt soniox \
  --soniox_stt_api_key "${APP_SONIOX_API_KEY}" \
  --soniox_stt_language ur \
  --llm_backend chat-completions \
  --model_name "${APP_VLLM_MODEL:-qwen3.5}" \
  --chat_completions_base_url "${APP_VLLM_API_BASE}" \
  --chat_completions_api_key "${APP_VLLM_API_KEY:-EMPTY}" \
  --tts uplift \
  --uplift_tts_api_key "${APP_UPLIFT_API_KEY}" \
  --uplift_tts_voice_id "${APP_UPLIFT_VOICE_ID:-v_8eelc901v6}"
