#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# eVoiceClaw Desktop v3 — 本地开发重启脚本
#
# 用法：
#   bash deploy/restart-local.sh            # 重启前端 + 后端
#   bash deploy/restart-local.sh --backend  # 仅重启后端
#   bash deploy/restart-local.sh --frontend # 仅重启前端
#   bash deploy/restart-local.sh --stop     # 停止所有服务
#
# 日志输出：
#   backend/logs/uvicorn.log   后端日志
#   frontend/logs/vite.log     前端日志
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# ─── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── 路径 ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"

BACKEND_PORT=8000
FRONTEND_PORT=5173

# ─── 参数解析 ──────────────────────────────────────────────
DO_BACKEND=true
DO_FRONTEND=true
STOP_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend)  DO_FRONTEND=false; shift ;;
        --frontend) DO_BACKEND=false;  shift ;;
        --stop)     STOP_ONLY=true;    shift ;;
        -h|--help)
            echo "用法: bash deploy/restart-local.sh [--backend|--frontend|--stop]"
            exit 0
            ;;
        *) error "未知参数: $1"; exit 1 ;;
    esac
done

# ─── 停止函数 ──────────────────────────────────────────────
stop_backend() {
    info "停止后端 (port ${BACKEND_PORT})..."
    # 按端口精确匹配
    local pids
    pids=$(lsof -ti :${BACKEND_PORT} 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "$pids" | xargs kill -TERM 2>/dev/null || true
        sleep 1
        # 确认已停止
        pids=$(lsof -ti :${BACKEND_PORT} 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs kill -9 2>/dev/null || true
            sleep 1
        fi
        success "后端已停止"
    else
        info "后端未在运行"
    fi
}

stop_frontend() {
    info "停止前端 (port ${FRONTEND_PORT})..."
    local pids
    pids=$(lsof -ti :${FRONTEND_PORT} 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "$pids" | xargs kill -TERM 2>/dev/null || true
        sleep 1
        pids=$(lsof -ti :${FRONTEND_PORT} 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs kill -9 2>/dev/null || true
            sleep 1
        fi
        success "前端已停止"
    else
        info "前端未在运行"
    fi
}

# ─── 停止 ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}eVoiceClaw Desktop v3 — 本地重启${NC}"
echo ""

$DO_BACKEND  && stop_backend
$DO_FRONTEND && stop_frontend

if $STOP_ONLY; then
    success "所有服务已停止"
    exit 0
fi

# ─── 启动后端 ──────────────────────────────────────────────
if $DO_BACKEND; then
    info "启动后端..."

    mkdir -p "${BACKEND_DIR}/logs"

    # 使用项目内的 .venv
    if [[ -f "${BACKEND_DIR}/.venv/bin/uvicorn" ]]; then
        UVICORN="${BACKEND_DIR}/.venv/bin/uvicorn"
    elif command -v uvicorn &>/dev/null; then
        UVICORN="uvicorn"
    else
        error "找不到 uvicorn，请先安装: cd backend && pip install -r requirements.txt"
        exit 1
    fi

    cd "${BACKEND_DIR}"
    nohup "${UVICORN}" app.main:app --reload --reload-dir app --host 0.0.0.0 --port ${BACKEND_PORT} \
        > logs/uvicorn.log 2>&1 &
    BACKEND_PID=$!
    cd "${PROJECT_ROOT}"

    # 等待后端就绪
    info "等待后端就绪..."
    for i in $(seq 1 15); do
        if curl -s -o /dev/null "http://localhost:${BACKEND_PORT}/api/v1/health" 2>/dev/null; then
            success "后端已启动 (PID: ${BACKEND_PID}, port: ${BACKEND_PORT})"
            break
        fi
        if [[ $i -eq 15 ]]; then
            warn "后端启动较慢，请检查日志: tail -f backend/logs/uvicorn.log"
        fi
        sleep 1
    done
fi

# ─── 启动前端 ──────────────────────────────────────────────
if $DO_FRONTEND; then
    info "启动前端..."

    mkdir -p "${FRONTEND_DIR}/logs"

    cd "${FRONTEND_DIR}"
    nohup npm run dev > logs/vite.log 2>&1 &
    FRONTEND_PID=$!
    cd "${PROJECT_ROOT}"

    sleep 2
    if kill -0 "${FRONTEND_PID}" 2>/dev/null; then
        success "前端已启动 (PID: ${FRONTEND_PID}, port: ${FRONTEND_PORT})"
    else
        error "前端启动失败，查看日志: cat frontend/logs/vite.log"
        exit 1
    fi
fi

# ─── 汇总 ──────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}重启完成${NC}"
$DO_FRONTEND && info "前端: http://localhost:${FRONTEND_PORT}"
$DO_BACKEND  && info "后端: http://localhost:${BACKEND_PORT}"
echo ""
info "查看日志:"
$DO_BACKEND  && echo "  tail -f ${BACKEND_DIR}/logs/uvicorn.log"
$DO_FRONTEND && echo "  tail -f ${FRONTEND_DIR}/logs/vite.log"
echo ""
