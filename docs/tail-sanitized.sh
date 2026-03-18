#!/bin/bash
# 实时脱敏日志查看器 — 用于 asciinema 录屏
# 用法: bash docs/tail-sanitized.sh

LOG_FILE="${1:-/Volumes/Other/Agent/eVoiceClawDesktop/desktop-v3/backend/logs/uvicorn.log}"

tail -f "$LOG_FILE" \
  | sed -u \
    -e 's|/Volumes/Other/Agent/eVoiceClawDesktop/desktop-v3/backend/app|<project>/backend/app|g' \
    -e 's|/Volumes/Other/Agent/eVoiceClawDesktop/desktop-v3/backend/data|<project>/backend/data|g' \
    -e 's|/Volumes/Other/Agent/eVoiceClawDesktop/desktop-v3/data|<project>/data|g' \
    -e 's|/Volumes/Other/Agent/eVoiceClawDesktop/desktop-v3|<project>|g' \
    -e 's|/Users/[a-zA-Z0-9_-]*/.evoiceclaw-v3|<data_dir>|g' \
    -e 's|/Users/[a-zA-Z0-9_-]*/Desktop/eVoiceClaw|<workspace>|g' \
    -e 's|/Users/[a-zA-Z0-9_-]*|<home>|g'
