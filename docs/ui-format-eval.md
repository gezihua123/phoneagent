# UI 格式评测报告

## 一、实验数据

- **评测规模**：3 轮 × 6 格式 × 22 题 = 396 次调用
- **模型**：deepseek-v4-flash
- **数据集**：wd2 (Google Play 搜索结果), wd3 (5 应用安装按钮), wd4 (设置页), ui2 (文章详情)
- **失败分布**：396 次调用中共 30 次非 exact，**全部集中在"安装/下载按钮"类问题**

---

## 二、格式对比数据（3 轮 × 22 题 = 66 次/格式）

### 准确率与 Token 汇总

| 格式 | RUN1 strict | RUN2 strict | RUN3 strict | 3轮均值 | 3轮exact总计 | Avg Tokens | 文件大小(wd2) | 失败模式 |
|------|-----------|-----------|-----------|--------|------------|------------|-------------|---------|
| **.yml** | 90.9% (20) | 100% (22) | 95.5% (21) | 95.5% | 63/66 | **11,276** | 95,868 B | center_in 为主 |
| **.jsonl** | 95.5% (21) | 100% (22) | 100% (22) | **98.5%** | **65/66** | 12,776 | 45,683 B | center_in（极少）|
| **.simplexml** | 100% (22) | 90.9% (20) | 90.9% (20) | 93.9% | 62/66 | 4,432 | 20,011 B | center_in + near |
| **.flatref** | 95.5% (21) | 86.4% (19) | 100% (22) | 93.9% | 62/66 | **3,485** | 9,270 B | center_in + near |
| **.flattext** | 95.5% (21) | 90.9% (20) | 95.5% (21) | 93.9% | 62/66 | **2,772** | 9,645 B | near（Button节点）|
| **.compact** | 81.8% (18) | 77.3% (17) | 77.3% (17) | 78.8% | 52/66 | **1,816** | 2,991 B | center_in（最多）|

### Token 效率 vs 准确率象限

```
高准确率(>95%)
    ↑
    │  jsonl (98.5%, 12776 tok) ★最优准确率
    │  yml (95.5%, 11276 tok)
    │
    │       simplexml (93.9%, 4432 tok)
    │       flatref (93.9%, 3485 tok)
    │       flattext (93.9%, 2772 tok) ★最优性价比
    │
    │                 compact (78.8%, 1816 tok) 最省token但准确率低
    └──────────────────────────────────→ 高Token效率(低token)
```

---

## 三、各格式深度对比

### 1. jsonl — 准确率王者

```jsonl
{"id": 19, "parent": 17, "depth": 16, "clickable": true, "bounds": "[857,399][1017,525]"}
```

**优势**：
- `clickable` 作为独立 JSON 字段，LLM 做字段级推理最清晰
- 不可点击节点也有 `"clickable": false`，信息完整
- 3 轮仅 1 次失败（65/66），最稳定

**劣势**：
- Token 最大（12,776），是 flattext 的 4.6 倍
- 每行包含所有 18 个属性，大量冗余（`password: false` 等无用字段）

**使用边界**：适合对准确率要求极高、不关心成本的场景（如离线批量标注、评测基准）

---

### 2. yml — 完整结构化

```yaml
- index: 0
  text: ''
  class: android.widget.FrameLayout
  clickable: false
  bounds: '[0,0][1080,2194]'
  children:
  - index: 0
    ...
```

**优势**：
- 保留完整层级结构，缩进直观
- 所有属性都是 `key: value`，LLM 易解析
- 准确率与 jsonl 接近（95.5%）

**劣势**：
- Token 最大（11,276），和 jsonl 一个量级
- 缩进导致深度越深 token 越多
- 保留了 `password: false` 等无用字段

**使用边界**：适合需要人类可读 + LLM 可解析的调试场景，不适合生产环境

---

### 3. simplexml — 原生 XML 精简版

```xml
<node index="1" class="View" bounds="[857,399][1017,525]" clickable="True">
  <node class="View" content-desc="安装" bounds="[899,432][975,491]" />
  <node class="Button" bounds="[857,409][1017,514]" />
</node>
```

**优势**：
- 保留原生 XML 属性格式，兼容现有 XML 解析工具
- 只保留非空/true 属性，比原生 XML 小很多
- Token 中等（4,432）

**劣势**：
- `class="Button"` 和 `clickable="True"` 竞争注意力，LLM 偶尔被 Button 误导
- 属性顺序固定，clickable 不在第一个，不够显眼
- 准确率波动大（100% → 90.9% → 90.9%）

**使用边界**：适合需要兼容 XML 解析工具链的场景，或从原生 XML 平滑迁移

---

### 4. flatref — 扁平带引用

```flatref
#19 parent=#17 depth=16 [1] (View) [clickable] bounds=[857,399][1017,525]
#20 parent=#19 depth=17 [0] desc="安装" (View) bounds=[899,432][975,491]
#22 parent=#19 depth=17 [1] (Button) bounds=[857,409][1017,514]
```

**优势**：
- Token 极小（3,485），仅为 jsonl 的 1/4
- `#id parent=#M` 显式表达层级，LLM 可做祖先链推理
- 无缩进，深度不影响 token

**劣势**：
- `[clickable]` 行内标记不如 jsonl 字段清晰
- `(Button)` 类名仍会干扰 LLM
- 准确率波动较大（95.5% → 86.4% → 100%）

**使用边界**：适合 token 敏感但需要层级推理的场景（如手机端实时推理、大批量调用）

---

### 5. flattext — 缩进文本

```flattext
[1] (View) [clickable] bounds=[857,399][1017,525]
  [0] desc="安装" (View) bounds=[899,432][975,491]
  [1] (Button) bounds=[857,409][1017,514]
```

**优势**：
- Token 最小（2,772），性价比最高
- 缩进直观，人类可读
- 准确率稳定在 93.9%

**劣势**：
- `(Button)` 类名语义干扰最严重——LLM 倾向返回 Button 节点而非 clickable 容器
- 失败模式固定为 `near`（返回 Button bounds，偏差 10px）
- 无 `#id` 引用，无法做祖先链推理

**使用边界**：适合 token 极度敏感且问题不涉及"按钮类元素层级选择"的场景

---

### 6. compact — 极致压缩

```compact
▶  [857,399][1017,525] + View
   [899,432][975,491] View D<安装>
```

**优势**：
- Token 最小（1,816），仅为 jsonl 的 1/7
- `▶` 高亮 clickable 容器

**劣势**：
- 过度过滤导致 clickable 容器（text/desc 为空）被弱化
- 准确率最低（78.8%），安装按钮问题每轮稳定失败 4-5 次
- 信息丢失严重，LLM 缺乏判断依据

**使用边界**：仅适合简单界面（无嵌套按钮）+ 极端 token 限制的场景

---

## 四、使用边界决策矩阵

| 场景 | 推荐格式 | 理由 |
|------|---------|------|
| 评测基准/离线标注 | **jsonl** | 准确率最高（98.5%），不计成本 |
| 生产环境（准确率优先）| **jsonl** 或 **yml** | 准确率稳定 >95% |
| 生产环境（成本优先）| **flattext** | 准确率 93.9%，token 仅 2,772 |
| 手机端实时推理 | **flattext** 或 **flatref** | token 小，延迟低 |
| 需要 XML 工具链兼容 | **simplexml** | 原生 XML 格式 |
| 需要层级祖先推理 | **flatref** | `#id parent=#M` 显式引用 |
| 极端 token 限制 | **compact** | token 最小，但准确率风险大 |
| 调试/人类可读 | **yml** 或 **flattext** | 缩进直观 |

---

## 五、失败根因分析

### 失败问题清单（3 轮中至少失败 1 次的）

| 文件 | 问题 | GT bounds |
|------|------|-----------|
| wd2 | 我想下载那个生活兴趣社区app，返回下载按钮的位置 | `[857,399][1017,525]` |
| wd2 | 那个分享生活方式的app怎么下载，找一下 | `[857,966][1017,1092]` |
| wd3 | 页面有5个应用的安装按钮，找到第1个小红书应用的安装按钮可点击区域 | `[857,399][1017,525]` |
| wd3 | 找到第3个应用Lemon8的安装按钮可点击区域 | `[857,1289][1017,1415]` |
| wd3 | 找到最后一个应用Instagram的安装按钮可点击区域 | `[857,2179][1017,2305]` |

### 错误返回的 bounds 类型

所有 30 次失败只返回了两种错误 bounds：

| 错误类型 | Pred bounds | 对应节点 | 偏差 | 匹配结果 |
|----------|-------------|----------|------|----------|
| ① 文字节点 | `[899,432][975,491]` | desc="安装" / text="安装" | 中心在GT内 | `center_in` |
| ② Button节点 | `[857,409][1017,514]` | class="Button" | top+10, bottom-11 | `near` |

### 三层根因

#### 一、数据原因（根本原因）★★★

安装按钮被 Compose 渲染成 **4 个嵌套节点、3 种不同 bounds**：

```
id=19 clickable=True  [857,399][1017,525]  text=""  desc=""      ← GT 期望（clickable 容器）
id=20 clickable=False [899,432][975,491]   text=""  desc="安装"   ← 错误返回①
id=21 clickable=False [899,432][975,491]   text="安装" desc=""    ← 错误返回①
id=22 clickable=False [857,409][1017,514]  class="Button"          ← 错误返回②
```

**核心矛盾**：
- GT 期望的是 `clickable=True` 的容器（id=19），但它的 text 和 content_desc **都为空**
- 有 "安装" 语义的节点（id=20/21）和 Button 类型节点（id=22）都**不可点击**
- LLM 看到问题说"安装按钮"，自然倾向返回有"安装"文字的节点

这是 Android Compose 应用（如 Google Play）的结构特点：clickable 容器本身不携带文本，文本在不可点击的子节点上。

#### 二、问题原因（措辞歧义）★★

问题中混合了两种表述：

1. **明确要求"可点击区域"**（wd3 的 3 个问题）：
   - "找到第1个小红书应用的安装按钮**可点击区域**，返回bounds"
   - LLM 理解了"可点击"，但数据中没有 clickable=True 且有"安装"文字的节点
   - LLM 在 clickable 容器（空 text）和文字节点（有"安装"）之间犹豫

2. **未要求"可点击区域"**（wd2 的 2 个问题）：
   - "我想下载那个生活兴趣社区app，返回**下载按钮的位置**"
   - "那个分享生活方式的app怎么下载，找一下"
   - 问题说"下载按钮"但数据里没有"下载"文字，只有"安装"
   - 问题说"找一下"非常模糊，LLM 需要推理"分享生活方式"→ Lemon8

#### 三、LLM 原因（概率性选错）★★

LLM 面对多候选时的选择不稳定：

- **compact** 格式失败率最高（3 轮 77.3%/77.3%/77.3%）：因为 compact 过滤了信息，LLM 更难判断哪个是 clickable 容器
- **flattext** 格式失败率较低（3 轮 95.5%/90.9%/95.5%）：因为 flattext 保留了 `[clickable]` 标记和完整层级
- 同一格式同一问题，3 轮中有时 exact 有时失败 → LLM 的选择是**概率性**的

#### 四、Prompt 原因（缺引导）★

当前 prompt 没有明确告诉 LLM：
- 应优先返回 `clickable=true` 的容器 bounds
- 不要返回内部文字/按钮的 bounds
- 当问题说"按钮"时，应理解为可点击区域而非文字标签

---

## 六、各格式失败统计

| 格式 | RUN1 exact | RUN2 exact | RUN3 exact | 失败模式 |
|------|-----------|-----------|-----------|----------|
| .yml | 20/22 | 22/22 | 21/22 | center_in 为主 |
| .jsonl | 21/22 | 22/22 | 22/22 | center_in 为主 |
| .flattext | 21/22 | 20/22 | 21/22 | near 为主（返回 Button 节点）|
| .simplexml | 22/22 | 20/22 | 20/22 | center_in + near |
| .flatref | 21/22 | 19/22 | 22/22 | center_in + near |
| .compact | 18/22 | 17/22 | 17/22 | center_in 为主（4-5次/轮）|

**关键发现**：
- jsonl 在 RUN1 失败 1 次，RUN2/RUN3 全 exact
- compact 每轮稳定失败 4-5 次，是格式本身信息不足
- flattext 偏向返回 Button 节点（near），其他格式偏向返回文字节点（center_in）

---

## 七、jsonl 失败专项分析

### jsonl 在安装按钮区域的完整输出

```
{"id": 19, "parent": 17, "clickable": true,  "bounds": "[857,399][1017,525]", "text": "", "content_desc": ""}
{"id": 20, "parent": 19, "clickable": false, "bounds": "[899,432][975,491]",  "text": "", "content_desc": "安装"}
{"id": 21, "parent": 20, "clickable": false, "bounds": "[899,432][975,491]",  "text": "安装", "content_desc": ""}
{"id": 22, "parent": 19, "clickable": false, "bounds": "[857,409][1017,514]", "class": "Button"}
```

### jsonl 失败的具体原因

1. **信息完整但无优先级指引**
   - jsonl 完整输出了 4 个节点，包括 clickable 字段
   - LLM 能看到 id=19 是 clickable=true，但 prompt 没说"优先返回 clickable 容器"
   - LLM 在"有安装文字的节点"和"clickable 容器"之间概率性选择

2. **jsonl 比 compact 成功率高的原因**
   - jsonl 保留了 `clickable: true` 字段，LLM 有依据判断
   - compact 把 clickable 压缩成 `+` 符号，且 clickable 容器（id=19）text/desc 为空被 compact 标记为"非 meaningful"可能被折叠或弱化
   - jsonl 每行独立、字段名明确，LLM 更容易做字段级推理

3. **jsonl 偶尔失败（1/22）的原因**
   - 当问题说"下载按钮"但数据里只有"安装"文字时，LLM 需要语义推理
   - 推理路径："下载"→"安装"→ 找 content_desc="安装" 的节点 → 返回其 bounds
   - 但 GT 逻辑是：找到 desc="安装" → **向上找 clickable 祖先** → 返回祖先 bounds
   - LLM 没有做"向上找 clickable 祖先"这步，直接返回了文字节点 bounds
   - 这是 **GT 逻辑与 LLM 自然推理路径不一致**

4. **jsonl 失败是概率性的**
   - RUN1 失败 1 次，RUN2/RUN3 全 exact
   - 同一问题同一数据，LLM 有时选 clickable 容器，有时选文字节点
   - 说明 LLM 理解了"可点击"语义但执行不稳定

### jsonl 失败根因总结

| 因素 | 是否根因 | 说明 |
|------|---------|------|
| 数据结构 | ✅ 是 | clickable 容器无文字，文字节点不可点击 |
| GT 逻辑 | ✅ 是 | GT 要求"向上找 clickable 祖先"，LLM 自然推理不会这样做 |
| Prompt | ✅ 是 | 没有引导 LLM 优先返回 clickable 容器 |
| 问题措辞 | 部分 | wd2 问题未明确说"可点击区域" |
| LLM 能力 | 部分 | 概率性选错，理解了但执行不稳定 |
| jsonl 格式 | ❌ 否 | jsonl 已完整保留 clickable 字段，格式本身无缺陷 |

---

## 八、优化建议

### 1. Prompt 优化（最低成本，改 `eval_formats.py`）

在 PROMPT_TEMPLATE 中增加：
```
4. 优先返回 clickable=true 的容器元素的bounds，而非其内部文字/按钮的bounds。
5. 当问题提到"按钮""可点击区域"时，返回可点击容器（clickable=true）的bounds。
```

### 2. 格式优化（改 `convert_meta.py`，针对 compact）

- clickable 容器内的非 clickable 子节点，将 text/desc 合并到父节点标签
- 跳过这些子节点的独立输出
- 这样 LLM 只能看到一个候选 bounds（clickable 容器）

### 3. GT 逻辑优化（改 `eval_formats.py`，可选）

- 当 `use_clickable_parent=True` 且 LLM 返回的 bounds 在 GT 内时，接受为 exact
- 但这会降低评测严格性，仅作参考

---

## 九、关键结论

1. **准确率第一梯队**：jsonl（98.5%）> yml（95.5%）> flattext/flatref/simplexml（93.9%）> compact（78.8%）

2. **Token 效率第一梯队**：compact（1,816）< flattext（2,772）< flatref（3,485）< simplexml（4,432）< yml（11,276）< jsonl（12,776）

3. **性价比最优**：flattext（93.9% 准确率，2,772 token），token 仅为 jsonl 的 1/4.6，准确率差距仅 4.6%

4. **所有格式失败模式一致**：都卡在"clickable 容器 vs 内部文字/Button 子节点"的层级选择歧义，根因是数据结构（Compose 渲染特点）而非格式本身

5. **格式选择不是准确率的决定因素**：prompt 引导（"优先返回 clickable 容器"）比格式选择更能提升准确率
