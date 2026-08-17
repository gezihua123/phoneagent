#!/usr/bin/env bash
# fastaget 测试脚本：打开 Google Play → 搜索小红书 → 下载
# 用 deepseek Anthropic 兼容端点 + HTTP 直连（比子进程方式快 3-5x，无 max_turns 崩溃）
set -euo pipefail

export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
: "${ANTHROPIC_AUTH_TOKEN:?ANTHROPIC_AUTH_TOKEN 未设置——请 export 后重跑}"
export DISABLE_COST_WARNINGS=1

echo "解锁 + 回桌面..."
phonefast home 2>/dev/null
sleep 1
# 上滑解锁（锁屏状态下 launch 会失败，agent 看到 keyguard 以为应用没启动）
phonefast swipe 540 2000 540 300 150 2>/dev/null || true
sleep 1
phonefast swipe 540 2000 540 300 150 2>/dev/null || true
sleep 1

echo ""
echo "===== FastAgent ReAct: 打开 Google Play → 小红书下载 ====="
echo "（deepseek-v4-flash + HTTP 直连 + 拼音搜索 + key 回车）"
echo ""

fastaget run "打开google play，搜索小红书并点击下载安装" \
    --max-steps 15 \
    --model deepseek-v4-flash \
    --delegate http \
    --verbose-timing
