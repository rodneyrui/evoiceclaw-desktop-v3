#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# eVoiceClaw Desktop v3 — 远程部署脚本
#
# 功能：本地构建前端 → rsync 同步到远程服务器 → 安装依赖 → 重启服务
#
# 用法：
#   bash deploy/deploy-remote.sh                  # 完整部署（前端+后端）
#   bash deploy/deploy-remote.sh --backend-only   # 仅部署后端
#   bash deploy/deploy-remote.sh --frontend-only  # 仅构建和部署前端
#   bash deploy/deploy-remote.sh --help           # 查看帮助
#
# 环境变量：
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
NC='\033[0m' # 重置颜色

# ─── 辅助函数 ────────────────────────────────────────────────
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
step()    { echo -e "\n${CYAN}${BOLD}══════ $* ══════${NC}"; }

# ─── 默认配置 ────────────────────────────────────────────────
REMOTE_HOST="${DEPLOY_HOST:-}"
REMOTE_USER="${DEPLOY_USER:-}"
SSH_PORT="${DEPLOY_PORT:-22}"
REMOTE_PATH="/opt/evoiceclaw-desktop-v3"
SERVICE_NAME="evoiceclaw-desktop-v3"
SERVICE_PORT=28771
HEALTH_ENDPOINT="/api/v1/health"
HEALTH_TIMEOUT=30        # 健康检查超时（秒）
HEALTH_RETRY_INTERVAL=2  # 健康检查重试间隔（秒）

# ─── 模式标志 ────────────────────────────────────────────────
DO_FRONTEND=true
DO_BACKEND=true

# ─── 项目根目录（脚本所在目录的上一级） ─────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
FRONTEND_DIST_DIR="${BACKEND_DIR}/frontend_dist"

# ─── SSH/rsync 公共选项 ──────────────────────────────────────
SSH_OPTS="-p ${SSH_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
SSH_CMD="ssh ${SSH_OPTS} ${REMOTE_USER}@${REMOTE_HOST}"
RSYNC_SSH="ssh ${SSH_OPTS}"

# ─── 帮助信息 ────────────────────────────────────────────────
show_help() {
    cat <<EOF
${BOLD}eVoiceClaw Desktop v3 — 远程部署脚本${NC}

${BOLD}用法:${NC}
  bash deploy/deploy-remote.sh [选项]

${BOLD}选项:${NC}
  --backend-only      仅部署后端（跳过前端构建）
  --frontend-only     仅构建和部署前端（跳过后端依赖安装和服务重启）
  --host <地址>        远程主机地址（必填，或设置 \$DEPLOY_HOST）
  --user <用户名>      远程用户名（必填，或设置 \$DEPLOY_USER）
  --port <端口>        SSH 端口（默认: \$DEPLOY_PORT 或 22）
  --path <路径>        远程部署路径（默认: /opt/evoiceclaw-desktop-v3）
  --no-restart        部署后不重启服务
  --no-health-check   跳过健康检查
  --dry-run           仅显示将要执行的操作，不实际执行
  -h, --help          显示帮助信息

${BOLD}环境变量:${NC}
  DEPLOY_HOST         远程主机地址
  DEPLOY_USER         远程用户名
  DEPLOY_PORT         SSH 端口

${BOLD}示例:${NC}
  # 完整部署
  bash deploy/deploy-remote.sh

  # 仅更新后端代码
  bash deploy/deploy-remote.sh --backend-only

  # 指定远程主机
  bash deploy/deploy-remote.sh --host 192.168.1.100 --user deploy

  # 试运行（不实际执行）
  bash deploy/deploy-remote.sh --dry-run
EOF
    exit 0
}

# ─── 参数解析 ────────────────────────────────────────────────
NO_RESTART=false
NO_HEALTH_CHECK=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend-only)
            DO_FRONTEND=false
            DO_BACKEND=true
            shift
            ;;
        --frontend-only)
            DO_FRONTEND=true
            DO_BACKEND=false
            shift
            ;;
        --host)
            REMOTE_HOST="$2"
            shift 2
            ;;
        --user)
            REMOTE_USER="$2"
            shift 2
            ;;
        --port)
            SSH_PORT="$2"
            # 重新构造 SSH 相关命令
            SSH_OPTS="-p ${SSH_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
            SSH_CMD="ssh ${SSH_OPTS} ${REMOTE_USER}@${REMOTE_HOST}"
            RSYNC_SSH="ssh ${SSH_OPTS}"
            shift 2
            ;;
        --path)
            REMOTE_PATH="$2"
            shift 2
            ;;
        --no-restart)
            NO_RESTART=true
            shift
            ;;
        --no-health-check)
            NO_HEALTH_CHECK=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            error "未知参数: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 参数解析完毕后，重新构造 SSH 命令（以防 --host/--user 在 --port 之后指定）
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

# ─── 打印部署配置 ────────────────────────────────────────────
echo ""
echo -e "${BOLD}┌─────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}│   eVoiceClaw Desktop v3 — 远程部署           │${NC}"
echo -e "${BOLD}└─────────────────────────────────────────────┘${NC}"
echo ""
info "远程主机:     ${REMOTE_USER}@${REMOTE_HOST}:${SSH_PORT}"
info "部署路径:     ${REMOTE_PATH}"
info "服务端口:     ${SERVICE_PORT}"
info "部署前端:     ${DO_FRONTEND}"
info "部署后端:     ${DO_BACKEND}"
info "试运行模式:   ${DRY_RUN}"
echo ""

if $DRY_RUN; then
    warn "试运行模式 — 仅显示操作，不实际执行"
    echo ""
fi

# ─── 前置检查 ────────────────────────────────────────────────
step "前置检查"

# 检查项目目录是否存在
if [[ ! -d "$BACKEND_DIR" ]]; then
    error "后端目录不存在: ${BACKEND_DIR}"
    exit 1
fi
success "后端目录存在: ${BACKEND_DIR}"

if $DO_FRONTEND && [[ ! -d "$FRONTEND_DIR" ]]; then
    error "前端目录不存在: ${FRONTEND_DIR}"
    exit 1
fi
$DO_FRONTEND && success "前端目录存在: ${FRONTEND_DIR}"

# 检查必要工具
for cmd in rsync ssh; do
    if ! command -v "$cmd" &>/dev/null; then
        error "缺少必要工具: ${cmd}"
        exit 1
    fi
done
success "必要工具已就绪 (rsync, ssh)"

if $DO_FRONTEND; then
    if ! command -v npm &>/dev/null; then
        error "缺少 npm，无法构建前端"
        exit 1
    fi
    success "npm 已就绪: $(npm --version)"
fi

# 检查 SSH 连接
info "测试 SSH 连接..."
if ! $DRY_RUN; then
    if ! $SSH_CMD "echo '连接成功'" 2>/dev/null; then
        error "无法连接到远程主机 ${REMOTE_USER}@${REMOTE_HOST}:${SSH_PORT}"
        error "请检查网络连接、SSH 密钥配置和防火墙规则"
        exit 1
    fi
    success "SSH 连接正常"
else
    info "[试运行] 跳过 SSH 连接测试"
fi

# ══════════════════════════════════════════════════════════════
# 步骤 1: 本地前端构建
# ══════════════════════════════════════════════════════════════
if $DO_FRONTEND; then
    step "步骤 1/5: 本地构建前端"

    if ! $DRY_RUN; then
        # 安装前端依赖（如有需要）
        info "检查前端依赖..."
        if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
            info "安装前端依赖 (npm install)..."
            (cd "$FRONTEND_DIR" && npm install)
        fi

        # 执行构建
        info "执行前端构建 (npm run build)..."
        (cd "$FRONTEND_DIR" && npm run build)

        if [[ ! -d "${FRONTEND_DIR}/dist" ]]; then
            error "前端构建失败: dist 目录不存在"
            exit 1
        fi

        # 复制构建产物到 backend/frontend_dist
        info "复制构建产物到 backend/frontend_dist..."
        mkdir -p "$FRONTEND_DIST_DIR"
        rm -rf "${FRONTEND_DIST_DIR:?}"/*
        cp -r "${FRONTEND_DIR}/dist/"* "$FRONTEND_DIST_DIR/"

        success "前端构建完成，产物已复制到 frontend_dist/"
    else
        info "[试运行] cd ${FRONTEND_DIR} && npm run build"
        info "[试运行] cp -r ${FRONTEND_DIR}/dist/* ${FRONTEND_DIST_DIR}/"
    fi
else
    info "跳过前端构建 (--backend-only)"
fi

# ══════════════════════════════════════════════════════════════
# 步骤 2: 创建远程目录
# ══════════════════════════════════════════════════════════════
step "步骤 2/5: 准备远程环境"

if ! $DRY_RUN; then
    info "确保远程目录存在..."
    $SSH_CMD "mkdir -p ${REMOTE_PATH}/frontend_dist ${REMOTE_PATH}/data ${REMOTE_PATH}/logs"
    success "远程目录已就绪"
else
    info "[试运行] ssh ... mkdir -p ${REMOTE_PATH}/{frontend_dist,data,logs}"
fi

# ══════════════════════════════════════════════════════════════
# 步骤 3: rsync 同步文件
# ══════════════════════════════════════════════════════════════
step "步骤 3/5: 同步文件到远程服务器"

# rsync 排除规则
RSYNC_EXCLUDES=(
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='.venv'
    --exclude='venv'
    --exclude='.env'
    --exclude='*.db'
    --exclude='*.db-journal'
    --exclude='.git'
    --exclude='.DS_Store'
    --exclude='node_modules'
    --exclude='.pytest_cache'
    --exclude='.mypy_cache'
    --exclude='.ruff_cache'
    --exclude='data/'
    --exclude='logs/'
    --exclude='secrets.yaml'
)

if $DO_BACKEND || $DO_FRONTEND; then
    if ! $DRY_RUN; then
        info "同步后端代码..."
        rsync -avz --delete \
            -e "${RSYNC_SSH}" \
            "${RSYNC_EXCLUDES[@]}" \
            "${BACKEND_DIR}/" \
            "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"

        success "文件同步完成"
    else
        info "[试运行] rsync -avz --delete ${BACKEND_DIR}/ → ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"
        info "[试运行] 排除: __pycache__, .venv, data/, *.db, secrets.yaml 等"
    fi
fi

# ══════════════════════════════════════════════════════════════
# 步骤 4: 远程安装依赖 + 重启服务
# ══════════════════════════════════════════════════════════════
if $DO_BACKEND; then
    step "步骤 4/5: 安装 Python 依赖"

    if ! $DRY_RUN; then
        info "远程安装/更新 Python 依赖..."
        $SSH_CMD "cd ${REMOTE_PATH} && pip install -r requirements.txt --quiet 2>&1 | tail -5"
        success "Python 依赖安装完成"
    else
        info "[试运行] ssh ... pip install -r ${REMOTE_PATH}/requirements.txt"
    fi

    # 重启服务
    if ! $NO_RESTART; then
        step "步骤 4.5/5: 重启服务"

        if ! $DRY_RUN; then
            info "重启 ${SERVICE_NAME} 服务..."

            # 尝试使用 systemd 管理服务
            if $SSH_CMD "systemctl is-enabled ${SERVICE_NAME} 2>/dev/null"; then
                # systemd 服务已配置，使用 systemctl 重启
                info "使用 systemd 重启服务..."
                $SSH_CMD "systemctl restart ${SERVICE_NAME}"
                sleep 2

                # 检查服务状态
                if $SSH_CMD "systemctl is-active ${SERVICE_NAME}" 2>/dev/null | grep -q "active"; then
                    success "服务已通过 systemd 重启"
                else
                    error "服务启动失败，查看日志:"
                    $SSH_CMD "journalctl -u ${SERVICE_NAME} --no-pager -n 20"
                    exit 1
                fi
            else
                # fallback: 使用 nohup 启动
                warn "systemd 服务未配置，使用 nohup 方式启动"
                info "提示: 可将 deploy/evoiceclaw-desktop-v3.service 复制到远程 /etc/systemd/system/ 并启用"

                # 停止旧进程
                info "停止旧进程..."
                $SSH_CMD "pkill -f 'uvicorn app.main:app.*${SERVICE_PORT}' 2>/dev/null || true"
                sleep 2

                # 启动新进程
                info "使用 nohup 启动服务..."
                $SSH_CMD "cd ${REMOTE_PATH} && nohup uvicorn app.main:app --host 0.0.0.0 --port ${SERVICE_PORT} > logs/uvicorn.log 2>&1 &"
                sleep 2

                # 检查进程是否存活
                if $SSH_CMD "pgrep -f 'uvicorn app.main:app.*${SERVICE_PORT}'" &>/dev/null; then
                    success "服务已通过 nohup 启动 (PID: $($SSH_CMD "pgrep -f 'uvicorn app.main:app.*${SERVICE_PORT}'"))"
                else
                    error "服务启动失败，查看日志:"
                    $SSH_CMD "tail -20 ${REMOTE_PATH}/logs/uvicorn.log 2>/dev/null || echo '日志文件不存在'"
                    exit 1
                fi
            fi
        else
            info "[试运行] systemctl restart ${SERVICE_NAME} 或 nohup uvicorn ..."
        fi
    else
        info "跳过服务重启 (--no-restart)"
    fi
else
    info "跳过 Python 依赖安装和服务重启 (--frontend-only)"

    # 仅前端模式下，如果服务正在运行，也需要重启以加载新的前端文件
    if ! $NO_RESTART; then
        step "步骤 4/5: 重启服务（加载新前端）"

        if ! $DRY_RUN; then
            info "重启服务以加载新的前端构建产物..."
            if $SSH_CMD "systemctl is-enabled ${SERVICE_NAME} 2>/dev/null"; then
                $SSH_CMD "systemctl restart ${SERVICE_NAME}"
                sleep 2
                success "服务已重启"
            else
                $SSH_CMD "pkill -f 'uvicorn app.main:app.*${SERVICE_PORT}' 2>/dev/null || true"
                sleep 2
                $SSH_CMD "cd ${REMOTE_PATH} && nohup uvicorn app.main:app --host 0.0.0.0 --port ${SERVICE_PORT} > logs/uvicorn.log 2>&1 &"
                sleep 2
                success "服务已重启"
            fi
        else
            info "[试运行] 重启服务"
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════
# 步骤 5: 健康检查
# ══════════════════════════════════════════════════════════════
if ! $NO_HEALTH_CHECK && ! $NO_RESTART; then
    step "步骤 5/5: 健康检查"

    if ! $DRY_RUN; then
        HEALTH_URL="http://${REMOTE_HOST}:${SERVICE_PORT}${HEALTH_ENDPOINT}"
        info "等待服务就绪: ${HEALTH_URL}"

        ELAPSED=0
        HEALTHY=false

        while [[ $ELAPSED -lt $HEALTH_TIMEOUT ]]; do
            HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "${HEALTH_URL}" 2>/dev/null || echo "000")

            if [[ "$HTTP_CODE" == "200" ]]; then
                HEALTHY=true
                break
            fi

            echo -n "."
            sleep "$HEALTH_RETRY_INTERVAL"
            ELAPSED=$((ELAPSED + HEALTH_RETRY_INTERVAL))
        done

        echo "" # 换行

        if $HEALTHY; then
            success "健康检查通过 (HTTP ${HTTP_CODE})"

            # 打印服务响应
            info "服务响应:"
            curl -s "${HEALTH_URL}" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
        else
            error "健康检查失败（等待 ${HEALTH_TIMEOUT} 秒后超时）"
            error "最后一次 HTTP 状态码: ${HTTP_CODE}"
            warn "请手动检查服务状态:"
            echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} -p ${SSH_PORT} 'journalctl -u ${SERVICE_NAME} -n 30'"
            echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} -p ${SSH_PORT} 'tail -30 ${REMOTE_PATH}/logs/uvicorn.log'"
            exit 1
        fi
    else
        info "[试运行] curl http://${REMOTE_HOST}:${SERVICE_PORT}${HEALTH_ENDPOINT}"
    fi
else
    info "跳过健康检查"
fi

# ─── 部署完成 ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}┌─────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}${BOLD}│           部署完成!                           │${NC}"
echo -e "${GREEN}${BOLD}└─────────────────────────────────────────────┘${NC}"
echo ""
info "访问地址: http://${REMOTE_HOST}:${SERVICE_PORT}"
info "服务管理: ssh ${REMOTE_USER}@${REMOTE_HOST} -p ${SSH_PORT} 'systemctl status ${SERVICE_NAME}'"
echo ""
