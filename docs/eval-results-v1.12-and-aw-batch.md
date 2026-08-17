# fastaget 评测结果总结（v1.12 + aw_batch）

> 日期：2026-08-06
> 数据源：`build/eval/fa_v1.12_complete_opt/` + `build/aw_batch/`（机器原始 report.json/report.txt）
> 作用：本文是上述两批评测数据的**人工沉淀**。沉淀后，`build/` 内对应原始数据可随时删除重建。

---

## 一、总览

| 评测批次 | 通过 | 总数 | 成功率 | 成本 | 备注 |
|----------|------|------|--------|------|------|
| `fa_v1.11_ds_116` | 103 | 116 | 88.8% | $2.22 | 基线（对比文档见 `docs/fa-vs-cc-v1.11-full.md`）|
| `fa_v1.12_complete_opt` | 106 | 116 | **91.4%** | $2.34 | complete 时机优化后 |
| `aw_batch`（Markor 专项） | 8 | 17 | 47.1% | — | 最近 batch，Markor 系列 8/8 失败 |

**v1.11 → v1.12 净变化**：+3 PASS（`AW-ClockStopWatchRunning`、`AW-ClockTimerEntry`、`AW-MarkorTranscribeVideo`），0 退化。complete 时机优化有效，无副作用。

---

## 二、失败模式归因（核心沉淀）

v1.12 的 10 个失败 case 按根因分两类，aw_batch 的 9 个 Markor 失败同根因。

### 根因 A：Markor 界面下 observe 链路系统性失效（最大短板）

**涉及 case**（v1.12 失败 6 + aw_batch 失败 8，高度重叠）：
`AW-MarkorAddNoteHeader`、`AW-MarkorChangeNoteContent`、`AW-MarkorCreateFolder`、`AW-MarkorCreateNote`、`AW-MarkorEditNote`、`AW-MarkorMoveNote`、`AW-MarkorDeleteAllNotes`、`AW-MarkorDeleteNote`、`AW-MarkorTranscribeVideo`（v1.12 已修好）、`AW-MarkorTranscribeReceipt`、`AW-MarkorCreateNoteAndSms`、`AW-MarkorCreateNoteFromClipboard`、`AW-MarkorDeleteNewestNote`、`AW-MarkorMergeNotes`。

**根因链（trajectory 证据）**：
1. `phonefast observe` 反复返回 `[FAILED] observe failed: phonefast observe: observ...`——Markor 的文本编辑/列表界面**不返回 a11y 元素**（国产/定制 ROM 的 accessibility 残缺，或 Markor Canvas 渲染无 a11y 节点）。
2. LLM 收到 observe 失败后，**退化到自愈兜底**：`shell(uiautomator dump)`、`screenshot()` + OCR、甚至 `sandbox` 里 `tools.ocr()`。
3. 兜底全部失败：
   - OCR 多数返回 `OCR: 0 text regions found`（Markor 编辑区是纯文本，OCR 无文字识别或截图异常）。
   - sandbox 里 `import base64` / `import json` → `ImportError: __import__ not found`（**sandbox 不支持 import，LLM 不知道这个限制**，反复尝试）。
4. 最终堆满 `max_steps` 或触发"屏幕停滞过久"终止，任务未完成。

**判据**：trajectory 里出现 `observe failed: phonefast observe` + `ImportError: __import__ not found` + `OCR: 0 text regions` 三连，即为本根因。

**已知例外**：`AW-MarkorMoveNote` 是另一种失败——agent 用 `shell('mv ...')` 直接移动文件（**违反宪法第二条"shell 不得冒充 app 操作"**），verify 检查 `ls /sdcard/Documents/Markor/` 不匹配（路径错了），属作弊失败。见根因 C。

### 根因 B：Canvas/WebView 类应用 a11y 完全缺失

**涉及 case**：`AW-BrowserDraw`、`AW-BrowserMaze`、`AW-BrowserMultiply`、`AW-SimpleDrawProCreateDrawing`。

**根因**：
- Browser 游戏（Canvas 绘制）和 SimpleDrawPro（画板）的 UI 是 Canvas/WebView 渲染，**a11y 树无任何可交互元素**。
- OCR 也无法识别 Canvas 上的游戏元素（图形/迷宫，非文字）。
- agent observe 到 0 元素，无法操作，`verify: ·`（验证未执行，agent 未声称完成）。

**判据**：`verify: ·`（非 ✗ 也非 ✓）+ observe 0 元素，即 a11y 缺失死局。此类**当前架构无解**，需视觉模式（截图喂多模态模型）才能突破，但视觉坐标对齐是独立大问题（见 `docs/arch-fusion.md` 视觉坐标契约）。

### 根因 C：shell 冒充 app 操作（作弊失败）

**涉及 case**：`AW-MarkorMoveNote`。

**根因**：goal 要求"In Markor, move the note"，agent 用 `shell('mv /sdcard/Documents/test_note_xbdw.md /sdcard/Markor/')` 直接移动文件，没走 Markor UI。verify 检查目标路径不匹配（agent 猜错了目录）。

**违规**：宪法第二条明确禁止"shell 冒充 app 操作"。这是 prompt 引导或 LLM 决策问题，需在 baseline.txt 强化（已有"禁止 shell 冒充 app"规则，但 Markor 系列下 observe 失效后 LLM 被迫走 shell）。

---

## 三、关键洞察

1. **Markor 失败的真正瓶颈是 observe，不是 prompt**：所有 Markor case 的 trajectory 第一步几乎都是 `observe failed`。如果 observe 能返回元素，LLM 本可正常操作。当前 Markor 8/8 全失败是**设备层 a11y 残缺**问题，不是 agent 决策问题。
2. **自愈兜底链有缺陷**：observe 失败后，LLM 尝试 OCR/sandbox/shell，但：
   - sandbox 不支持 import（LLM 反复 `ImportError`，浪费步数）→ 应在工具描述里写明 sandbox 限制。
   - OCR 在 Markor 编辑区返回 0 → OCR 对纯文本编辑区无效，应考虑直接 `uiautomator dump` 或 shell 读文件。
3. **v1.12 complete 优化有效**：+3 case、0 退化，证明"complete 时机优化（A prompt + B 框架信号 + C assert 联动）"方向正确。
4. **aw_batch 的 8/17 反映 Markor 专项短板**：17 个 case 里 8 个是 Markor，全失败；非 Markor 的 9 个全过。批次成功率低是**样本偏科**，不是整体退化。

---

## 四、与历史评测的对照

| 版本 | 成功率 | 关键变化 | 文档 |
|------|--------|---------|------|
| fa_aw_24 | 6/24 (25%) ｜ 验证 14/16 (87.5%) | 早期 24 子集 | `docs/fa-vs-cc-aw24.md` |
| fa_v1.11 | 103/116 (88.8%) ｜验证 92.8% | 116 全量基线 | `docs/fa-vs-cc-v1.11-full.md` |
| **fa_v1.12** | **106/116 (91.4%)** | +complete 时机优化 | **本文** |
| aw_batch | 8/17 (47.1%) | Markor 专项，样本偏科 | **本文** |

> 注：fa_aw_24 的"声称 25% / 验证 87.5%"差距，与 v1.11 的"53% 做完不说"是同一类问题（agent 达成目标但不主动 complete），v1.12 的 complete 优化正是在修这个。

---

## 五、后续建议（供 TL 排期）

1. **Markor observe 失效**（根因 A，最高优先级）：
   - 排查 `phonefast observe` 在 Markor 界面为何返回失败——是 a11y 服务未启用、Markor 不导出 a11y 节点，还是 daemon 连接问题。
   - 若 a11y 确实缺失，加 `uiautomator dump` 作为 observe 的 fallback（shell 查询，不冒充操作）。
2. **sandbox 限制写进工具描述**：sandbox 不支持 `import`，应在工具描述里明确告知 LLM，避免反复 `ImportError` 浪费步数。
3. **Canvas/WebView 类**（根因 B）：当前无解，列入视觉模式规划，不阻塞当前评测。
4. **shell 冒充**（根因 C）：Markor 系列下 observe 失效是诱因，修根因 A 后应自然减少；同时 baseline.txt 已有规则，加强 observe 失败时的引导（"observe 失败时不要用 shell 直接操作文件"）。
