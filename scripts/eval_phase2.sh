#!/usr/bin/env bash
# fastaget Phase 2 评测脚本：真实 LLM + 状态机模拟真机
# 验证 prompt / format / model 组合效果
set -euo pipefail

# ---- 模型配置（与 test_play.sh 一致） ----
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
: "${ANTHROPIC_AUTH_TOKEN:?ANTHROPIC_AUTH_TOKEN 未设置——请 export 后重跑}"
export DISABLE_COST_WARNINGS=1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# scripts/ → 项目根距离与旧 agents_tests/ 一致（都是 1 层）

cd "$PROJECT_DIR"

# ---- 参数解析 ----
MODE="${1:-quick}"   # quick | standard | full | dry-run

case "$MODE" in
    dry-run)
        echo "=== 环境验证（不调 LLM） ==="
        python3 tests/eval_agent.py \
            --dry-run \
            --stateful \
            --yaml-scenarios \
            --delegate anthropic \
            --model deepseek-v4-flash
        ;;
    quick)
        echo "=== Quick 模式：核心假设验证 ==="
        echo "  7 场景 × 1 变体 × 2 prompt × 2 格式 = ~28 次调用"
        echo ""
        python3 tests/eval_agent.py \
            --quick \
            --stateful \
            --yaml-scenarios \
            --delegate anthropic \
            --model deepseek-v4-flash \
            --max-steps 8
        ;;
    standard)
        echo "=== Standard 模式：格式对比 ==="
        echo "  7 场景 × 1 变体 × 2 prompt × 2 格式 = 28 次调用"
        echo ""
        python3 tests/eval_agent.py \
            --stateful \
            --yaml-scenarios \
            --delegate anthropic \
            --model deepseek-v4-flash \
            --variants baseline \
            --formats region jsonl \
            --max-steps 8
        ;;
    full)
        echo "=== Full 模式：全矩阵 ==="
        echo "  7 场景 × 3 变体 × 2 prompt × 6 格式 = 252 次调用"
        echo ""
        python3 tests/eval_agent.py \
            --stateful \
            --yaml-scenarios \
            --delegate anthropic \
            --model deepseek-v4-flash \
            --max-steps 8
        ;;
    *)
        echo "用法: $0 {dry-run|quick|standard|full}"
        echo ""
        echo "  dry-run   - 仅验证环境，不调 LLM"
        echo "  quick     - 核心假设验证（~28 次）"
        echo "  standard  - 格式对比（28 次）"
        echo "  full      - 全矩阵（252 次）"
        exit 1
        ;;
esac

echo ""
echo "💾 结果: build/eval_agent_results.json"
