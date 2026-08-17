#!/bin/bash
# ============================================================================
# FA vs CC 对比评测脚本
# ============================================================================
# 用法：
#   1. FA 评测：
#      bash scripts/eval_compare.sh fa --model deepseek-v4-pro
#
#   2. CC 评测（需安装 Claude Code CLI）：
#      bash scripts/eval_compare.sh cc
#
#   3. FA vs CC 对比（依次跑两边）：
#      bash scripts/eval_compare.sh compare --model deepseek-v4-pro
#
#   4. 只生成对比报告（已有两边的结果）：
#      bash scripts/eval_compare.sh report
#
# 前置条件：
#   - 设备已连接（adb devices 可见）
#   - phonefast daemon 已启动
#   - ANTHROPIC_AUTH_TOKEN 已设置（FA 用）
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# scripts/ → 项目根距离与旧 agents_tests/ 一致（都是 1 层）
CASES_FILE="$PROJECT_DIR/fastaget/fastaget/meta/eval_cases.yml"
REPORT_DIR="$PROJECT_DIR/build/eval"
FA_REPORT="$REPORT_DIR/fa_v1.7"
CC_REPORT="$REPORT_DIR/cc"
COMPARE_REPORT="$REPORT_DIR/fa-vs-cc-v1.7.md"

mkdir -p "$REPORT_DIR"

run_fa() {
    local model="${1:-deepseek-v4-pro}"
    echo "=== FA v1.7 评测（model=$model）==="
    cd "$PROJECT_DIR"
    python3 -m fastaget.cli run \
        -f "$CASES_FILE" \
        --model "$model" \
        --max-steps 30 \
        --report-dir "$FA_REPORT" \
        --verbose
    echo "FA 报告已写入 $FA_REPORT"
}

run_cc() {
    echo "=== Claude Code 评测 ==="
    echo "⚠️ 需要手动在 Claude Code 中逐条执行 fastaget/meta/eval_cases.yml 中的用例"
    echo "   用例文件: $CASES_FILE"
    echo ""
    echo "CC 手动测试记录表格（复制到 $CC_REPORT/cc_manual.md）："
    echo ""
    echo "| ID | 用例 | CC 结果 | 步数 | 耗时 | 备注 |"
    echo "|----|------|---------|------|------|------|"
    grep "name:" "$CASES_FILE" | while read -r line; do
        name=$(echo "$line" | sed 's/.*name: //')
        echo "| $name | ... | ? | ? | ?s | |"
    done
}

generate_report() {
    echo "=== 生成对比报告 ==="
    cat > "$COMPARE_REPORT" << 'REPORT_HEADER'
# fastaget v1.7 vs Claude Code 对比报告

> 日期: TODO
> 模型: TODO
> 设备: TODO

## 总体对比

| 指标 | fastaget v1.7 | Claude Code | 倍率 |
|------|---------------|-------------|------|
| 成功率 | TODO% (TODO/TODO) | TODO% (TODO/TODO) | — |
| 平均步数 | TODO | TODO | — |
| 平均 LLM 调用 | TODO | TODO | — |
| 平均耗时 | TODOs | TODOs | — |
| 平均成本 | $TODO | $TODO | — |
| 首次成功率 | TODO% | TODO% | — |

## L1 简单用例（7个）

| ID | 用例 | FA | CC | 备注 |
|----|------|----|----|------|
REPORT_HEADER

    grep "name:" "$CASES_FILE" | grep "L1" | while read -r line; do
        name=$(echo "$line" | sed 's/.*name: //' | sed 's/ tags.*//')
        echo "| $name | ? | ? | |"
    done >> "$COMPARE_REPORT"

    cat >> "$COMPARE_REPORT" << 'REPORT_MID'

## L2 中等用例（8个）

| ID | 用例 | FA | CC | 备注 |
|----|------|----|----|------|
REPORT_MID

    grep "name:" "$CASES_FILE" | grep "L2" | while read -r line; do
        name=$(echo "$line" | sed 's/.*name: //' | sed 's/ tags.*//')
        echo "| $name | ? | ? | |"
    done >> "$COMPARE_REPORT"

    cat >> "$COMPARE_REPORT" << 'REPORT_MID2'

## L3 复杂用例（4个）

| ID | 用例 | FA | CC | 备注 |
|----|------|----|----|------|
REPORT_MID2

    grep "name:" "$CASES_FILE" | grep "L3" | while read -r line; do
        name=$(echo "$line" | sed 's/.*name: //' | sed 's/ tags.*//')
        echo "| $name | ? | ? | |"
    done >> "$COMPARE_REPORT"

    cat >> "$COMPARE_REPORT" << 'REPORT_FOOTER'

## 失败归因

### FA 失败用例

| ID | 失败原因 | 根因分类 | CC 是否成功 |
|----|---------|---------|-------------|
| — | — | — | — |

### 分类统计

| 根因 | 数量 | 占比 |
|------|------|------|
| 模型推理错误 | TODO | TODO% |
| 架构限制 | TODO | TODO% |
| 设备状态污染 | TODO | TODO% |
| 工具描述误导 | TODO | TODO% |

## 结论

TODO: 本次评测结论

---

## v1.0 基线（参考）

| 指标 | fastaget v1.0 | Claude Code | 倍率 |
|------|---------------|-------------|------|
| 成功率 | 100% (14/14) | 100% (5/5) | 持平 |
| 平均耗时 | 16.3s | 55s | FA 3.4x |
| 平均成本 | $0.004 | $0.494 | FA 115x |
| LLM 调用 | 4.6 次 | 11 turn | FA -58% |
REPORT_FOOTER

    echo "对比报告已写入 $COMPARE_REPORT"
}

# ── 主入口 ──
case "${1:-}" in
    fa)
        run_fa "${2:-deepseek-v4-pro}"
        ;;
    cc)
        run_cc
        ;;
    compare)
        run_fa "${2:-deepseek-v4-pro}"
        echo ""
        run_cc
        echo ""
        generate_report
        ;;
    report)
        generate_report
        ;;
    *)
        echo "用法: $0 {fa|cc|compare|report} [model]"
        echo ""
        echo "  fa <model>    运行 fastaget 评测"
        echo "  cc            打印 Claude Code 手动评测指引"
        echo "  compare <m>   FA + CC 对比（先FA自动，再CC手动）"
        echo "  report        生成对比报告模板"
        exit 1
        ;;
esac
