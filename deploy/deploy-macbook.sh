#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# eVoiceClaw Desktop v3 — MacBook Pro 远程部署脚本
#
# 目标：macOS 远程 Mac（nohup 管理服务）
#
# 用法：
#   bash deploy/deploy-macbook.sh                  # 完整部署（前端+后端）
#   bash deploy/deploy-macbook.sh --backend-only   # 仅部署后端
#   bash deploy/deploy-macbook.sh --frontend-only  # 仅构建和部署前端
#   bash deploy/deploy-macbook.sh --stop           # 停止远程服务
#   bash deploy/deploy-macbook.sh --dry-run        # 试运行（不实际执行）
#   bash deploy/deploy-macbook.sh --help           # 查看帮助
#
# 环境变量（可覆盖默认值）：
#   DEPLOY_HOST  远程主机地址（必填，如 192.168.1.100）
#   DEPLOY_USER  远程用户名（必填，如 deploy）
#   DEPLOY_PORT  SSH 端口（默认 22）
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# ─── 颜色定义 ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
step()    { echo -e "\n${CYAN}${BOLD}══════ $* ══════${NC}"; }

# ─── 默认配置 ────────────────────────────────────────────────
REMOTE_HOST="${DEPLOY_HOST:-}"
REMOTE_USER="${DEPLOY_USER:-}"
SSH_PORT="${DEPLOY_PORT:-22}"
REMOTE_PATH="evoiceclaw-desktop-v3"   # 相对于远程用户 HOME 的路径
REMOTE_PYTHON=""                       # 自动检测远程 Mac 上的 Python（见前置检查）
SERVICE_PORT=8000
HEALTH_ENDPOINT="/api/v1/system/health"
HEALTH_TIMEOUT=60
HEALTH_RETRY_INTERVAL=2

# ─── 模式标志 ────────────────────────────────────────────────
DO_FRONTEND=true
DO_BACKEND=true
STOP_ONLY=false
NO_RESTART=false
NO_HEALTH_CHECK=false
DRY_RUN=false
COMPILE_RULES=false   # --compile-rules 时编译 evaluation/rules/ 为 .so

# ─── 项目路径 ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
FRONTEND_DIST_DIR="${BACKEND_DIR}/frontend_dist"

# ─── 帮助信息 ────────────────────────────────────────────────
show_help() {
    cat <<EOF
${BOLD}eVoiceClaw Desktop v3 — MacBook Pro 远程部署脚本${NC}

${BOLD}用法:${NC}
  bash deploy/deploy-macbook.sh [选项]

${BOLD}选项:${NC}
  --backend-only      仅部署后端（跳过前端构建）
  --frontend-only     仅构建和部署前端
  --stop              停止远程服务（不部署）
  --compile-rules     部署后编译 evaluation/rules/（Cython → .so，IP 保护）
  --no-restart        部署后不重启服务
  --no-health-check   跳过健康检查
  --dry-run           仅显示将要执行的操作，不实际执行
  --host <地址>        远程主机（必填，或设置 \$DEPLOY_HOST）
  --user <用户名>      远程用户名（必填，或设置 \$DEPLOY_USER）
  --port <端口>        SSH 端口（默认: ${SSH_PORT}）
  -h, --help          显示此帮助

${BOLD}示例:${NC}
  bash deploy/deploy-macbook.sh                      # 完整部署
  bash deploy/deploy-macbook.sh --backend-only       # 仅后端
  bash deploy/deploy-macbook.sh --compile-rules      # 部署 + 编译规则引擎
  bash deploy/deploy-macbook.sh --stop               # 停止服务
  bash deploy/deploy-macbook.sh --dry-run            # 试运行
EOF
    exit 0
}

# ─── 参数解析 ────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend-only)    DO_FRONTEND=false; shift ;;
        --frontend-only)   DO_BACKEND=false;  shift ;;
        --stop)            STOP_ONLY=true;    shift ;;
        --compile-rules)   COMPILE_RULES=true; shift ;;
        --no-restart)      NO_RESTART=true;   shift ;;
        --no-health-check) NO_HEALTH_CHECK=true; shift ;;
        --dry-run)         DRY_RUN=true;      shift ;;
        --host)            REMOTE_HOST="$2";  shift 2 ;;
        --user)            REMOTE_USER="$2";  shift 2 ;;
        --port)            SSH_PORT="$2";     shift 2 ;;
        -h|--help)         show_help ;;
        *) error "未知参数: $1"; echo "使用 --help 查看帮助"; exit 1 ;;
    esac
done

# 参数解析完毕后构造 SSH 命令（以防 --host/--user 在 --port 之后指定）
# 必填参数检查
if [[ -z "$REMOTE_HOST" ]]; then
    error "未指定远程主机地址。请使用 --host <地址> 或设置 DEPLOY_HOST 环境变量"
    exit 1
fi
if [[ -z "$REMOTE_USER" ]]; then
    error "未指定远程用户名。请使用 --user <用户名> 或设置 DEPLOY_USER 环境变量"
    exit 1
fi
SSH_OPTS="-p ${SSH_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
SSH_CMD="ssh ${SSH_OPTS} ${REMOTE_USER}@${REMOTE_HOST}"
RSYNC_SSH="ssh ${SSH_OPTS}"

# ─── HuggingFace 模型缓存（本机 → 远程，避免远程下载失败）────
HF_CACHE_DIR="${HOME}/.cache/huggingface/hub"
# 需要同步的模型目录（相对于 HF_CACHE_DIR）
HF_MODELS=(
    "models--BAAI--bge-small-zh-v1.5"
    "models--BAAI--bge-m3"
)

# ─── 计算总步骤数 ─────────────────────────────────────────────
TOTAL_STEPS=6
$COMPILE_RULES && TOTAL_STEPS=7
CURRENT_STEP=0
next_step() { CURRENT_STEP=$((CURRENT_STEP + 1)); step "步骤 ${CURRENT_STEP}/${TOTAL_STEPS}: $*"; }

# ─── 打印配置 ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}┌─────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}│   eVoiceClaw Desktop v3 — MacBook 远程部署   │${NC}"
echo -e "${BOLD}└─────────────────────────────────────────────┘${NC}"
echo ""
info "远程主机:       ${REMOTE_USER}@${REMOTE_HOST}:${SSH_PORT}"
info "部署路径:       ~/${REMOTE_PATH}"
info "服务端口:       ${SERVICE_PORT}"
info "远程 Python:    自动检测"
info "部署前端:       ${DO_FRONTEND}"
info "部署后端:       ${DO_BACKEND}"
info "编译规则引擎:   ${COMPILE_RULES}"
$DRY_RUN && warn "试运行模式 — 仅显示操作，不实际执行"
echo ""

# ══════════════════════════════════════════════════════════════
# 停止服务
# ══════════════════════════════════════════════════════════════
stop_remote_service() {
    info "停止远程服务 (port ${SERVICE_PORT})..."
    if ! $DRY_RUN; then
        $SSH_CMD "pkill -f 'uvicorn app.main:app' 2>/dev/null || true; sleep 1; lsof -ti :${SERVICE_PORT} | xargs kill -9 2>/dev/null || true"
        sleep 1
        # 验证已停止
        if $SSH_CMD "lsof -ti :${SERVICE_PORT} 2>/dev/null | grep -q ." 2>/dev/null; then
            warn "仍有进程占用端口 ${SERVICE_PORT}，尝试强制终止"
            $SSH_CMD "lsof -ti :${SERVICE_PORT} | xargs kill -9 2>/dev/null || true"
            sleep 1
        fi
        success "远程服务已停止"
    else
        info "[试运行] ssh ... pkill -f 'uvicorn app.main:app'"
    fi
}

if $STOP_ONLY; then
    step "停止远程服务"
    if ! $DRY_RUN; then
        if ! $SSH_CMD "echo '连接测试'" 2>/dev/null; then
            error "无法连接到 ${REMOTE_USER}@${REMOTE_HOST}:${SSH_PORT}"
            exit 1
        fi
    fi
    stop_remote_service
    success "完成"
    exit 0
fi

# ══════════════════════════════════════════════════════════════
# 步骤 1: 前置检查
# ══════════════════════════════════════════════════════════════
next_step "前置检查"

[[ ! -d "$BACKEND_DIR" ]] && { error "后端目录不存在: ${BACKEND_DIR}"; exit 1; }
success "后端目录: ${BACKEND_DIR}"

if $DO_FRONTEND; then
    [[ ! -d "$FRONTEND_DIR" ]] && { error "前端目录不存在: ${FRONTEND_DIR}"; exit 1; }
    command -v npm &>/dev/null || { error "缺少 npm，无法构建前端"; exit 1; }
    success "前端目录: ${FRONTEND_DIR} | npm: $(npm --version)"
fi

command -v rsync &>/dev/null || { error "缺少 rsync"; exit 1; }
success "rsync 已就绪"

info "测试 SSH 连接..."
if ! $DRY_RUN; then
    if ! $SSH_CMD "echo '连接成功'" 2>/dev/null; then
        error "无法连接到 ${REMOTE_USER}@${REMOTE_HOST}:${SSH_PORT}"
        error "请确认："
        echo "  1. 目标 Mac 已开启「系统设置 → 通用 → 共享 → 远程登录」"
        echo "  2. SSH 密钥已配置: ssh-copy-id -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_HOST}"
        exit 1
    fi
    success "SSH 连接正常"

    # 自动检测远程 Python 版本（优先高版本）
    info "检测远程 Python..."
    REMOTE_PYTHON=""
    for py_cmd in python3.12 python3.11 python3.10 python3; do
        if $SSH_CMD "command -v ${py_cmd}" &>/dev/null; then
            REMOTE_PYTHON="${py_cmd}"
            break
        fi
    done
    if [[ -z "$REMOTE_PYTHON" ]]; then
        error "远程 Mac 未安装 Python3"
        error "请在目标 Mac 上安装: brew install python@3.12 或从 python.org 下载"
        exit 1
    fi
    REMOTE_PY_VER=$($SSH_CMD "${REMOTE_PYTHON} --version" 2>&1)
    success "远程 Python: ${REMOTE_PY_VER} (${REMOTE_PYTHON})"
else
    info "[试运行] 跳过 SSH 连接测试"
    REMOTE_PYTHON="python3"  # dry-run 时使用默认值
fi

# ══════════════════════════════════════════════════════════════
# 步骤 2: 本地前端构建
# ══════════════════════════════════════════════════════════════
if $DO_FRONTEND; then
    next_step "本地构建前端"

    if ! $DRY_RUN; then
        if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
            info "安装前端依赖..."
            (cd "$FRONTEND_DIR" && npm install)
        fi

        info "构建前端 (npm run build)..."
        (cd "$FRONTEND_DIR" && npm run build)

        [[ ! -d "${FRONTEND_DIR}/dist" ]] && { error "前端构建失败: dist 目录不存在"; exit 1; }

        info "复制构建产物到 backend/frontend_dist..."
        mkdir -p "$FRONTEND_DIST_DIR"
        rm -rf "${FRONTEND_DIST_DIR:?}"/*
        cp -r "${FRONTEND_DIR}/dist/"* "$FRONTEND_DIST_DIR/"
        success "前端构建完成"
    else
        info "[试运行] npm run build → frontend_dist/"
    fi
else
    info "跳过前端构建 (--backend-only)"
    CURRENT_STEP=$((CURRENT_STEP + 1))  # 跳过的步骤也计数
fi

# ══════════════════════════════════════════════════════════════
# 步骤 3: 准备远程目录
# ══════════════════════════════════════════════════════════════
next_step "准备远程环境"

if ! $DRY_RUN; then
    $SSH_CMD "mkdir -p ~/${REMOTE_PATH}/logs ~/${REMOTE_PATH}/data"
    success "远程目录已就绪: ~/${REMOTE_PATH}"
else
    info "[试运行] ssh ... mkdir -p ~/${REMOTE_PATH}/{logs,data}"
fi

# ══════════════════════════════════════════════════════════════
# 步骤 4: rsync 同步文件
# ══════════════════════════════════════════════════════════════
next_step "同步文件到远程 Mac"

RSYNC_EXCLUDES=(
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='.venv'
    --exclude='venv'
    --exclude='.env'
    --exclude='.git'
    --exclude='.DS_Store'
    --exclude='node_modules'
    --exclude='.pytest_cache'
    --exclude='.mypy_cache'
    --exclude='.ruff_cache'
    --exclude='logs/'
    --exclude='secrets.yaml'
    --exclude='*.so'
    --exclude='*.pyd'
    --exclude='data/db/audit.db'
    --exclude='data/db/audit.db-journal'
    --exclude='data/generated_rules/backup/'
)

if ! $DRY_RUN; then
    info "同步后端代码（含 frontend_dist）..."
    rsync -avz --delete \
        -e "${RSYNC_SSH}" \
        "${RSYNC_EXCLUDES[@]}" \
        "${BACKEND_DIR}/" \
        "${REMOTE_USER}@${REMOTE_HOST}:~/${REMOTE_PATH}/"

    # 同步编译脚本到远程（放在部署目录外的 _deploy/ 子目录）
    if $COMPILE_RULES; then
        info "同步编译脚本..."
        $SSH_CMD "mkdir -p ~/${REMOTE_PATH}/_deploy"
        rsync -avz \
            -e "${RSYNC_SSH}" \
            "${SCRIPT_DIR}/compile_rules.py" \
            "${REMOTE_USER}@${REMOTE_HOST}:~/${REMOTE_PATH}/_deploy/"
    fi

    success "文件同步完成"
else
    info "[试运行] rsync -avz --delete ${BACKEND_DIR}/ → ${REMOTE_USER}@${REMOTE_HOST}:~/${REMOTE_PATH}/"
    info "[试运行] 排除: __pycache__, .venv, data/, *.db, *.so, secrets.yaml 等"
fi

# ══════════════════════════════════════════════════════════════
# 步骤 5: 同步 HuggingFace 模型缓存
# ══════════════════════════════════════════════════════════════
next_step "同步 HuggingFace 模型缓存"

if ! $DRY_RUN; then
    SYNCED=0
    for model_dir in "${HF_MODELS[@]}"; do
        local_model="${HF_CACHE_DIR}/${model_dir}"
        if [[ -d "$local_model" ]]; then
            info "同步模型: ${model_dir}"
            $SSH_CMD "mkdir -p ~/.cache/huggingface/hub/${model_dir}"
            rsync -avz \
                -e "${RSYNC_SSH}" \
                "${local_model}/" \
                "${REMOTE_USER}@${REMOTE_HOST}:~/.cache/huggingface/hub/${model_dir}/"
            SYNCED=$((SYNCED + 1))
        else
            warn "本机无模型缓存: ${model_dir}，跳过"
        fi
    done
    if [[ $SYNCED -gt 0 ]]; then
        success "已同步 ${SYNCED} 个模型到远程"
    else
        warn "无模型可同步（本机 HuggingFace 缓存为空）"
    fi
else
    info "[试运行] rsync HuggingFace 模型: ${HF_MODELS[*]}"
fi

# ══════════════════════════════════════════════════════════════
# 步骤 6: 安装依赖 + 重启服务
# ══════════════════════════════════════════════════════════════
if $DO_BACKEND && ! $NO_RESTART; then
    next_step "安装依赖 + 重启服务"

    if ! $DRY_RUN; then
        $SSH_CMD bash <<REMOTE_SCRIPT
set -e
cd ~/evoiceclaw-desktop-v3

# 停止旧进程
pkill -f 'uvicorn app.main:app' 2>/dev/null || true
sleep 1
lsof -ti :${SERVICE_PORT} | xargs kill -9 2>/dev/null || true
sleep 1

# 确保 .venv 存在（使用 ${REMOTE_PYTHON}）
if [[ ! -d ".venv" ]]; then
    echo "[远程] 创建虚拟环境 (${REMOTE_PYTHON})..."
    ${REMOTE_PYTHON} -m venv .venv
fi

# 安装/更新依赖
echo "[远程] 安装 Python 依赖..."
.venv/bin/pip install -r requirements.txt --quiet 2>&1 | tail -5

# 后台启动（HF_HUB_OFFLINE=1 禁止在线下载模型，使用预同步的缓存）
echo "[远程] 启动后端服务..."
HF_HUB_OFFLINE=1 nohup .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${SERVICE_PORT} \
    > logs/uvicorn.log 2>&1 &

echo "[远程] 已后台启动，PID: \$!"
REMOTE_SCRIPT

        success "依赖安装完成，服务已后台启动"
    else
        info "[试运行] 远程创建 .venv (${REMOTE_PYTHON}) → pip install → nohup uvicorn"
    fi
elif $NO_RESTART; then
    next_step "安装依赖（不重启）"
    if ! $DRY_RUN && $DO_BACKEND; then
        info "仅安装依赖..."
        $SSH_CMD "cd ~/${REMOTE_PATH} && [[ -d .venv ]] || ${REMOTE_PYTHON} -m venv .venv && .venv/bin/pip install -r requirements.txt --quiet"
        success "依赖安装完成（服务未重启）"
    else
        info "[试运行] 仅安装依赖"
    fi
else
    info "跳过后端重启 (--frontend-only)"
    CURRENT_STEP=$((CURRENT_STEP + 1))
fi

# ══════════════════════════════════════════════════════════════
# 步骤 6（可选）: Cython 编译 rules/ 源码保护
# ══════════════════════════════════════════════════════════════
if $COMPILE_RULES; then
    next_step "Cython 编译规则引擎（IP 保护）"

    if ! $DRY_RUN; then
        info "在远程 Mac 编译 evaluation/rules/ → .so"
        $SSH_CMD bash <<COMPILE_SCRIPT
set -e
cd ~/evoiceclaw-desktop-v3

# 确保 .venv 存在
if [[ ! -d ".venv" ]]; then
    echo "[远程] 创建虚拟环境..."
    ${REMOTE_PYTHON} -m venv .venv
fi

# 安装 Cython
echo "[远程] 安装 Cython..."
.venv/bin/pip install cython setuptools --quiet

# 编译
echo "[远程] 开始编译..."
.venv/bin/python _deploy/compile_rules.py --clean --verify

# 清理 Cython（运行时不需要）
.venv/bin/pip uninstall -y cython --quiet 2>/dev/null || true

# 清理编译脚本
rm -rf _deploy/

echo "[远程] 规则引擎编译完成"
COMPILE_SCRIPT

        success "规则引擎编译完成（源码已删除，.so 已生成）"

        # 编译后需要重启服务以加载 .so
        if ! $NO_RESTART && $DO_BACKEND; then
            info "重启服务以加载编译后的模块..."
            stop_remote_service
            $SSH_CMD bash <<RESTART_SCRIPT
set -e
cd ~/evoiceclaw-desktop-v3
HF_HUB_OFFLINE=1 nohup .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${SERVICE_PORT} \
    > logs/uvicorn.log 2>&1 &
echo "[远程] 已重启，PID: \$!"
RESTART_SCRIPT
            success "服务已重启"
        fi
    else
        info "[试运行] 远程 pip install cython → compile_rules.py --clean --verify → pip uninstall cython"
    fi
fi

# ══════════════════════════════════════════════════════════════
# 健康检查
# ══════════════════════════════════════════════════════════════
if ! $NO_HEALTH_CHECK && ! $NO_RESTART && $DO_BACKEND; then
    HEALTH_URL="http://${REMOTE_HOST}:${SERVICE_PORT}${HEALTH_ENDPOINT}"
    info "等待服务就绪: ${HEALTH_URL}"

    if ! $DRY_RUN; then
        ELAPSED=0
        HEALTHY=false

        while [[ $ELAPSED -lt $HEALTH_TIMEOUT ]]; do
            HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "${HEALTH_URL}" 2>/dev/null || echo "000")
            if [[ "$HTTP_CODE" == "200" ]]; then
                HEALTHY=true
                break
            fi
            echo -n "."
            sleep "$HEALTH_RETRY_INTERVAL"
            ELAPSED=$((ELAPSED + HEALTH_RETRY_INTERVAL))
        done
        echo ""

        if $HEALTHY; then
            success "健康检查通过 (HTTP ${HTTP_CODE})"
            # 打印服务响应
            info "服务响应:"
            curl -s "${HEALTH_URL}" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
        else
            warn "健康检查超时（${HEALTH_TIMEOUT}s），服务可能仍在启动中"
            warn "查看远程日志: ssh ${REMOTE_USER}@${REMOTE_HOST} 'tail -30 ~/${REMOTE_PATH}/logs/uvicorn.log'"
        fi
    else
        info "[试运行] curl ${HEALTH_URL}"
    fi
fi

# ─── 完成 ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}┌─────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}${BOLD}│           部署完成                            │${NC}"
echo -e "${GREEN}${BOLD}└─────────────────────────────────────────────┘${NC}"
echo ""
info "访问地址:   http://${REMOTE_HOST}:${SERVICE_PORT}"
info "远程日志:   ssh ${REMOTE_USER}@${REMOTE_HOST} 'tail -f ~/${REMOTE_PATH}/logs/uvicorn.log'"
info "停止服务:   bash deploy/deploy-macbook.sh --stop"
echo ""
