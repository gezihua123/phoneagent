# Claude Code 执行轨迹完整分析

> **任务**: 打开设置，关闭蓝牙
> **模型**: deepseek-v4-pro[1m] (1M context window)
> **结果**: ✅ 成功 | 16 turns | 90.2s | $0.453
> **Tokens**: in=27,726 | out=2,823 | cache_read=212,864

---

## 一、完整消息流水线


CC 的每次 LLM 调用包含以下消息结构：

```
SYSTEM:  ~27,000 tokens (CC 内置行为规则 + 安全策略 + 27个工具定义)
USER:    "使用 phonefast skill 完成：打开设置，关闭蓝牙。完成后输出摘要。"
ASSISTANT: [thinking] → [tool_use: Skill("phonefast-skill")]
USER:    [tool_result: "Launching skill: phonefast-skill"]
  ↑ Skill 工具返回后，~8K token 的 phonefast 技能手册被注入到上下文
ASSISTANT: [thinking 336 chars] → [text: "步骤1: 检查设备"] → [tool_use: Bash("adb devices")]
USER:    [tool_result: "13709314CF044927 device"]
ASSISTANT: [thinking 25 chars] → [text: "步骤2: 确保phonefast就绪"] → [tool_use: Bash("which phonefast...")]
USER:    [tool_result: "phonefast v1.0.10"]
ASSISTANT: [thinking 31 chars] → [text: "步骤3: 打开设置"] → [tool_use: Bash("launch com.android.settings")]
USER:    [tool_result: "Launched: com.android.settings"]
ASSISTANT: [thinking 27 chars] → [text: "步骤4: 观察屏幕"] → [tool_use: Bash("sleep 2 && observe")]
USER:    [tool_result: <4687 chars 原始文本元素列表>]
ASSISTANT: [thinking 342 chars: 解析bounds → 计算坐标] → [text] → [tool_use: Bash("tap 360 599")]
USER:    [tool_result: "Tapped at (360, 599)"]
ASSISTANT: [thinking 222 chars] → [text] → [tool_use: Bash("observe")]
USER:    [tool_result: <20 chars: observe失败>]
ASSISTANT: [thinking 57 chars: 重试] → [tool_use: Bash("observe")]
USER:    [tool_result: <1616 chars 蓝牙页面元素>]
ASSISTANT: [thinking 827 chars: 深度分析Switch状态] → [text] → [tool_use: Bash("tap 616 280")]
  ... (多次盲试tap + observe循环) ...
ASSISTANT: [thinking 1895 chars: 逐行分析4578 chars observe] → [text: markdown表格摘要]
```

## 二、Phase 1: 启动准备 (Turn 1-7, ~55 tokens thinking)

### 实际 LLM 消息序列

| 消息 | 角色 | 内容 | Token |
|------|------|------|-------|
| 1 | user | "使用 phonefast skill 完成：打开设置，关闭蓝牙。完成后输出摘要。" | ~50 |
| 2 | assistant | [thinking 149]: "The user wants me to use the phonefast skill to open Settings and turn off Bluetooth..." → Skill("phonefast-skill", {"args": "打开手机设置，关闭蓝牙"}) | ~200 |
| 3 | user | [tool_result]: "Launching skill: phonefast-skill" | ~10 |
| 4 | assistant | [thinking 336]: "Let me follow the phonefast skill workflow: 1. Check device 2. Ensure phonefast ready 3. Launch Settings 4. Observe to find Bluetooth 5. Turn off Bluetooth 6. Confirm and output summary" → TEXT("步骤1：检查设备连接") → Bash("adb devices") | ~500 |
| 5 | user | [tool_result]: "List of devices attached\n13709314CF044927 device" | ~20 |
| 6 | assistant | [thinking 25]: "设备已连接。接下来确保 phonefast 可用。" → TEXT("设备已连接。步骤2：确保 phonefast 就绪") → Bash(install/check script) | ~300 |
| 7 | user | [tool_result]: "phonefast v1.0.10" | ~15 |

### 关键发现

- **Skill() 工具** 返回的不是 phonefast 手册内容，而是 "Launching skill: phonefast-skill"。手册是在 Skill 工具执行过程中被**注入到后续消息的上下文**中的。

- CC 的 Bash 工具使用了完整的 shell 脚本（if/else + curl 安装命令），而不是简单的单行命令。这是 CC 灵活性的体现——它可以写任意复杂的 shell 逻辑。

- CC 在每一步操作前都输出 TEXT（"步骤X: ..."），这是给用户看的进度提示，但**对完成任务无实际价值**，纯浪费 token。


## 三、Phase 2: 观察 + 定位 + 点击 (Turn 8-12, ~400 chars thinking)

### LLM 消息

| 消息 | 内容 | Token |
|------|------|-------|
| 8 | [thinking 31] → TEXT("步骤3：打开设置") → Bash("phonefast --daemon launch com.android.settings") | ~150 |
| 9 | [tool_result]: "Launched: com.android.settings" | ~10 |
| 10 | [thinking 27] → TEXT("步骤4：观察屏幕找蓝牙") → Bash("sleep 2 && phonefast --daemon observe") | ~150 |
| 11 | [tool_result]: 4687 chars 原始元素文本 | ~2000 |
| 12 | [thinking 342]: 解析 bounds → 计算中心坐标 → 决定 tap | ~350 |

### Thinking 块完整内容（手工坐标计算）

```
I can see the Settings main page. Bluetooth option is at index [26] with text "蓝牙".

The Bluetooth item has bounds=[40,547][680,651].
Center point calculation:
  x = (40 + 680) / 2 = 360
  y = (547 + 651) / 2 = 599

Let me tap on it with: phonefast --daemon tap 360 599
```

**FA 等价**: `tap_element(index=26)` — processor 自动调用 `el.center()` 返回 (360, 599)。CC 用 342 chars thinking 做 FA 一行代码的事。


## 四、Phase 3: 盲试 Switch (Turn 13-28, ~1200 chars thinking) ⚠️

### 问题根因

CC 从 observe 返回的原始文本中**看不到 Switch 的 checked 状态**：

```
[6] id="switch_bar" (LinearLayout) [clickable] bounds=[0,212][720,356]
[7] text="蓝牙" (TextView) bounds=[40,224][96,343]
[8] id="switch_widget" (Switch) bounds=[576,212][656,356]
```

原始文本中没有 `checked=true` 或 `checked=false` 属性。CC 只能通过**对比前后两次 observe 的差异**来推断状态变化。


### Blind Tap 循环

| Turn | 操作 | 推理 |
|------|------|------|
| 13 | Bash("observe") → [20 chars] | observe 返回空，可能页面未加载 |
| 14 | Bash("observe") → [1616 chars] | 重试成功，看到 Switch 元素 |
| 15 | [thinking 827]: "Bluetooth is OFF — I can't directly see its state from the text output. Let me tap the Switch at (616,280) to toggle it." | **盲试第1次** |
| 16 | Bash("tap 616 280") | 点击 Switch |
| 17 | [thinking 83]: "Not sure if toggle worked. Let me observe and verify." | 不确定是否成功 |
| 18 | Bash("observe") | 再次观察 |
| 19 | [thinking 156]: "Screen looks similar. Let me try tapping again." | **盲试第2次** |
| 20 | Bash("tap 616 280") | 再次点击 |
| 21 | [thinking 61]: "Still uncertain. Let me try screenshot." | 尝试视觉回退 |
| 22 | Bash("screenshot /tmp/bluetooth_screen.png") | 截图 |
| 23 | Read("/tmp/bluetooth_screen.png") → ❌ 权限被拒 | 视觉回退失败 |
| 24 | [thinking 304]: "Screenshot denied. Let me observe again." | 回退到文本 |
| 25 | Bash("observe") → [4578 chars] | 大量元素文本 |
| 26 | [thinking 1895!!!]: 逐行分析4578 chars | **最深推理** |
| 27 | Bash("tap 616 280") | **盲试第3次** |
| 28 | Bash("observe") | 最终确认 |

### FA 等价对比

```
FA: processor.process(raw.elements_text) → UIState
    → element.checked = True/False (Switch属性)
    → tap_element(index=9)  # 精确点击 Switch
    → observe → element.checked = not 原状态  # 确认翻转
    → assert(description='蓝牙已关闭', passed=True)
    → complete(success=True)

CC: Bash("observe") → 读取原始文本 → "can't see Switch state"
    → Bash("tap 616 280") → "不确定" → Bash("tap 616 280") → "还是不确定"
    → Bash("screenshot") → Read → 权限拒绝
    → Bash("observe") → 对比文本差异 → Bash("tap 616 280")
    → 最终还是不确定，继续分析...
```

## 五、Token 消耗归因

### 完整分布

| 类别 | Token | 占比 | 是否有用 |
|------|-------|------|---------|
| System Prompt | ~27,000 | 89% | 部分有用（工具定义+行为规则） |
| Phonefast Skill 手册 | ~8,000 | 注入后 | 部分有用（CLI命令参考） |
| Observe 文本 (4次) | ~15,000 | — | 有用（但含冗余格式信息） |
| Tool Results | ~3,000 | — | 冗余（"Launched: xxx" 比需要长 3x） |
| Thinking (total) | ~5,000 | 18% | **60%在重复FA processor的工作** |
| Text 输出 (TEXT) | ~700 | 2.5% | 冗余（markdown表格 vs FA 50字符摘要） |
| Tool Calls | ~500 | 1.8% | 有用 |

### Thinking 内容拆解

| Thinking 块 | Chars | 内容 | FA是否自动化 |
|------------|-------|------|-------------|
| 1 (149) | 任务理解 | "use phonefast to open Settings and turn off Bluetooth" | N/A |
| 2 (336) | 制定工作流 | "1. Check device 2. Ensure phonefast 3. Launch 4. Observe 5. Turn off 6. Confirm" | ✅ Plan融入首轮 |
| 3 (25) | 状态确认 | "设备已连接。接下来确保 phonefast 可用。" | ✅ 自动 |
| 4 (31) | 状态确认 | "phonefast 已就绪。现在打开设置应用。" | ✅ 自动 |
| 5 (27) | 等待策略 | "设置已启动。等待 2 秒后观察屏幕。" | ✅ auto-observe 0.5s |
| **6 (342)** | **手工坐标计算** | **"bounds=[40,547][680,651], center=(40+680)/2=360..."** | **✅ el.center()** |
| 7 (222) | 失败分析 | "observe failed, retry" | ✅ with_retry |
| 8 (57) | 状态确认 | "重试observe" | ✅ 自动 |
| **9 (827)** | **Switch分析** | **"Bluetooth is OFF — can't see state from text. Tap Switch at (616,280)"** | **✅ checked属性** |
| 10 (83) | 不确定性 | "Not sure if toggle worked" | ✅ 自动确认 |
| 11 (156) | 不确定性 | "Screen looks similar, try again" | ✅ 自动确认 |
| 12 (61) | 回退策略 | "Try screenshot" | N/A (视觉模式) |
| 13 (304) | 失败分析 | "Screenshot denied, observe instead" | N/A |
| **14 (1895)** | **深度分析** | **逐行解析4578 chars元素文本** | **✅ processor** |
| 15 (31) | 操作确认 | "Switch tapped, verify" | ✅ 自动 |
| 16 (227) | 最终确认 | "Bluetooth is OFF, summary" | ✅ assert |

## 六、CC Prompt 结构推断

虽然 CC 不暴露 system prompt，但可从行为反推其结构：

```
CC System Prompt (~27,000 tokens):
├── 身份定义 ("You are Claude, an AI assistant...")
├── 行为规则 (~5,000 tokens)
│   ├── Safety & Ethics 策略
│   ├── 隐私保护规则
│   ├── 权限模型 (Harmlessness宪法)
│   └── 输出格式要求 (markdown, tables)
├── 工具定义 (~10,000 tokens)
│   ├── 27个工具的函数签名 + 描述 + 参数schema
│   ├── Bash: 完整的shell执行能力
│   ├── Read/Write/Edit: 文件操作
│   ├── Skill: 技能加载机制
│   └── Task/Agent/Workflow: 多Agent编排
├── Phonefast Skill (~8,000 tokens, 通过Skill()动态注入)
│   ├── CLI命令完整参考表 (observe/tap/swipe/type/key/launch/screenshot)
│   ├── 100+ Keycode映射表
│   ├── 5个场景示例 (打开微信/发消息/滑到底部/.../)
│   ├── 错误处理表 (8种常见error→action映射)
│   └── 工作流程指导 (Check→Ensure→Understand→Act→Confirm)
└── 上下文注入 (~2,000 tokens)
    ├── 当前工作目录
    ├── 平台信息 (macOS)
    └── Session metadata
```

## 七、核心结论

### CC 的 LLM 在做什么

1. **翻译意图** → "打开设置关闭蓝牙" (50 token)
2. **加载技能** → Skill() 注入 8K token 手册
3. **制定计划** → 7步工作流 (336 chars thinking)
4. **设备检查** → adb + which phonefast (3 turns)
5. **执行操作** → launch + sleep + observe (核心操作)
6. **手工解析** → 读 bounded text → 计算坐标 → tap (342 chars)
7. **盲试Switch** → 3次tap + 多次observe (看不清checked状态)
8. **视觉回退** → screenshot + Read (失败)
9. **深度分析** → 1895 chars thinking逐行解析文本
10. **格式化输出** → 351 chars markdown表格

### FA 的 LLM 在做什么

1. **翻译意图+计划** → Plan融入首轮 (1 call)
2. **执行+验证** → launch → tap_element → assert (4 calls)
3. **完成** → complete (1 call)

### 差距不是模型，是架构

```
CC 把 LLM 当解析器用:      读原始文本 → 算坐标 → 判断状态 → 盲试操作
FA 把 processor 当解析器用: 读原始文本 → 结构化UIState → checked属性 → 精准操作

CC = LLM(intelligence) + Bash(shell) + raw_text(interface)
FA = LLM(decision) + Processor(structure) + tool_call(typed interface)
```
