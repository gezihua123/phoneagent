# Prompts 硬编码检查方案

> 适用：每次修改 prompts 后、发版前、CR 审查时执行。
> 目标：确保所有 prompt 文件零硬编码坐标/包名/UI 假设/场景特判/shell 冒充模式。

---

## 一、自动化扫描（grep 5 维度）

```bash
PROMPT_DIR=fastaget/meta/prompts

# 1. 坐标/纯数字（≥3 位数字可能为像素坐标）
grep -nP '\b\d{3,4}\b' $PROMPT_DIR/baseline.txt $PROMPT_DIR/optimized.txt \
  $PROMPT_DIR/feedback/feedback.txt $PROMPT_DIR/kb/ui.txt \
  | grep -v 'count\|step\|limit\|elapsed\|token\|cache\|ms\|http\|width\|height'

# 2. 包名格式（com.xxx.yyy）
grep -nP 'com\.\w+\.\w+' $PROMPT_DIR/baseline.txt $PROMPT_DIR/optimized.txt \
  $PROMPT_DIR/feedback/feedback.txt $PROMPT_DIR/kb/tasks.txt $PROMPT_DIR/kb/ui.txt $PROMPT_DIR/route_config.yml
# 注意：kb/apps.txt 中包名是预期存在的参考知识，不在扫描范围

# 3. shell 冒充操作（echo/mkdir/mv/rm/content insert 等直写命令）
grep -nP '(echo|mkdir|content insert|mv |rm -f|cp )' $PROMPT_DIR/baseline.txt \
  $PROMPT_DIR/optimized.txt $PROMPT_DIR/kb/tasks.txt $PROMPT_DIR/kb/ui.txt

# 4. 设备/机型特定名称
grep -nPi 'RF8R|TECNO|emulator|pixel|nexus|samsung|xiaomi|huawei' \
  $PROMPT_DIR/*.txt $PROMPT_DIR/kb/*.txt $PROMPT_DIR/feedback/*.txt

# 5. case/goal 特判关键词
grep -nPi '如果.*goal|if.*goal|case.*特|特殊处理|这个case|这个任务' \
  $PROMPT_DIR/*.txt $PROMPT_DIR/kb/*.txt $PROMPT_DIR/feedback/*.txt
```

---

## 二、手动语义审查（7 项）

| # | 检查项 | 说明 | 违规示例 | 合法示例 |
|---|--------|------|---------|---------|
| 1 | **坐标硬编码** | 任何像素坐标出现在操作指引中（非 kb 参考） | `tap (540, 960)`、`x=720` | `约 2/3 宽度`、`屏幕中间` |
| 2 | **包名在操作上下文** | 非 kb 文件出现 `com.xxx.yyy` 且不含"参考/示例"字样 | `launch com.google.android.deskclock` | kb/apps.txt 中的 App 参考 |
| 3 | **UI 布局假设** | 假设特定 app 的按钮位置/顺序/tab 名称 | "设置页第三个开关是蓝牙" | "底部导航栏通常有 3-5 个图标" |
| 4 | **shell 冒充 app** | 提示词引导用 shell 达成任务目标（非查询） | "用 `echo > file` 创建笔记" | "用 `settings get` 查询状态" |
| 5 | **场景特判** | 对 goal 内容做 if-else 分支引导 | "如果 goal 提到 wifi，先调 svc" | "开关类任务 shell 优先"（通用原则） |
| 6 | **死引用** | 引用不存在的文件/章节 | "见 _universal.txt" | "见 kb/ui.txt §1"（文件存在） |
| 7 | **过时统计** | 多余数字统计干扰 LLM | "人类 2582 次这样做" | 纯规则描述 |

---

## 三、CR 审查集成

在 `CLAUDE.md` CR 检查清单中追加 prompt 专用项：

```
- [ ] prompts 自动化扫描 5 维度全绿（0 命中）
- [ ] 手动语义审查 7 项通过
- [ ] 无新增硬编码坐标/包名/UI 假设
- [ ] 无死引用（引用文件存在且章节名匹配）
- [ ] shell 命令仅用于查询或系统设置（开关/亮度/飞行模式），不冒充 app 操作
```

---

## 四、修复指引

| 发现类型 | 修复方法 |
|---------|---------|
| 坐标 | 改为比例描述（"屏幕中间"、"下半部"、"约 1/3 宽度"） |
| 包名 | 移到 kb/apps.txt 并标注 `参考`；操作层改为通用描述 |
| UI 假设 | 改为通用原则（"底部 FAB"代替"右下角 540,2100 的 + 按钮"） |
| shell 冒充 | 加上红线警告 `⚠️ 红线: 禁止 shell echo/mkdir 冒充 app 操作` |
| 场景特判 | 提取为通用分类规则，写入 route_config.yml task_types |
| 死引用 | 更新为当前文件名+章节名 |
| 过时统计 | 删除数字，保留规则描述 |
