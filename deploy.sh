#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# Exchange Web Dashboard — 一键部署脚本
# 用法: ./deploy.sh [--restart-only] [--status]
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

WEB_DIR="/root/Exchange/web"
STATIC_SRC="$WEB_DIR/static"
STATIC_DST="/var/www/hellobtc/static"
SERVICE_NAME="exchange-web.service"
VENV_PYTHON="/root/yuce/venv/bin/python"
VENV_PIP="/root/yuce/venv/bin/pip"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }

# ═══ 状态检查 ══════════════════════════════════════════════════
if [[ "${1:-}" == "--status" ]]; then
    echo "══════════════ 服务状态 ══════════════"
    systemctl status "$SERVICE_NAME" --no-pager 2>&1 | head -12
    echo ""
    echo "--- 端口 ---"
    ss -tlnp | grep -E "5000|80|443" || true
    echo ""
    echo "--- Nginx ---"
    nginx -t 2>&1 || true
    echo "--- 绑定挂载 ---"
    mount | grep "Exchange/web/static" || warn "静态文件绑定挂载未生效"
    exit 0
fi

# ═══ 仅重启 ════════════════════════════════════════════════════
if [[ "${1:-}" == "--restart-only" ]]; then
    info "重启 Web 服务..."
    systemctl restart "$SERVICE_NAME"
    sleep 2
    systemctl status "$SERVICE_NAME" --no-pager 2>&1 | head -5
    info "完成！"
    exit 0
fi

# ═══ 正常部署流程 ══════════════════════════════════════════════
echo "══════════════ 部署 Exchange Web Dashboard ══════════════"

# 1. 安装/更新依赖
echo ""
info "检查 Python 依赖..."
"$VENV_PIP" install -q flask pymysql ccxt python-dotenv requests gunicorn 2>&1 | tail -1

# 2. 确保绑定挂载存在
echo ""
if mount | grep -q "hellobtc/static"; then
    info "静态文件绑定挂载已生效"
else
    warn "重新挂载..."
    mkdir -p "$STATIC_DST"
    mount --bind "$STATIC_SRC" "$STATIC_DST"
fi

# 3. 复制 JS 版本文件 (app.js → app.v30.js)
echo ""
if [[ "$STATIC_SRC/app.js" -nt "$STATIC_SRC/app.v30.js" ]]; then
    cp "$STATIC_SRC/app.js" "$STATIC_SRC/app.v30.js"
    info "已同步 app.js → app.v30.js"
else
    info "app.v30.js 已是最新"
fi

# 4. 重启 Web 服务
echo ""
info "重启 Web 服务 (gunicorn)..."
systemctl daemon-reload 2>/dev/null || true
systemctl restart "$SERVICE_NAME"
sleep 2

# 5. 健康检查
echo ""
if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
    info "Web 服务健康检查通过 ✓"
else
    err "Web 服务未正常启动，请检查日志: journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

# 6. API 验证
echo ""
if curl -sf https://hellobtc.duckdns.org/api/tradfi-ai > /dev/null 2>&1; then
    info "公共 API 验证通过 ✓"
else
    warn "公共 API 验证失败（可能是 nginx 问题）"
fi

echo ""
info "══════════════ 部署完成 ══════════════"
echo ""
echo "  Dashboard:  https://hellobtc.duckdns.org/"
echo "  TradFi AI:  https://hellobtc.duckdns.org/tradfi-ai"
echo "  Binance AI: https://hellobtc.duckdns.org/binance-ai"
echo ""
echo "  查看日志: journalctl -u $SERVICE_NAME -n 50 -f"
echo "  快速重启: $0 --restart-only"
echo "  服务状态: $0 --status"
