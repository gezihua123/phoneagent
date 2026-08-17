# 提示词原则与 meta/prompts 目录结构

## 提示词原则

- 工具描述加示例优于加 system prompt 段落
- 领域知识 → `kb/*.txt`（声明式 #k/#pull-on 块），不要写进 baseline.txt
- 反馈模板 → `feedback/*.txt`
- 路由配置 → `route_config.yml`（goal 关键词 → task type → 加载哪些 kb 文件）
- 明确「禁止」行为（如"禁止未验证就 complete"）比说"应该"更有效
- 告诉 LLM 报错信息中的 `available indices` 可直接选用（一步自愈）
- Prompt 规则通用化：不针对特定 App，写通用原则让 LLM 自己适应

## Prompts 目录结构

```
meta/prompts/             # 7 个文件（从 26 个压缩而来）
├── baseline.txt          # System prompt（唯一）。核心规则+元素选择策略+验证范式+异常处理
├── judge.txt             # 语义判定 LLM 的 system prompt（flow 层 SemanticJudge 用）
├── route_config.yml      # 路由配置：goal 关键词→task type→触发词 + 错误类型→恢复建议
│
├── kb/                   # 知识库（3 个文件）
│   ├── apps.txt          # App 参考：各 app 入口模式+shell 命令+RAG 统计（30 个 #k 块）
│   ├── tasks.txt         # 任务打法+图标语义+恢复模式+通用原则（12 个 #k 块 + 1 个 #pull-on）
│   └── ui.txt            # 界面类型+组件+a11y+验证/闭环/恢复（合并自 4 个旧文件，#pull-on 块）
│
└── feedback/
    └── feedback.txt      # 反馈模板集合（9 个 section：plan_first/require_complete/...）
                          # Capability 按名 load_feedback("plan_first") 加载对应 section
```

## 合并历史（archive/ 保留备查）

- `apps.txt` ← apps.txt + apps_rag.txt(28489eps蒸馏)
- `tasks.txt` ← categories_rag.txt(27MB JSON蒸馏) + recovery_knowledge.txt(system_knowledge提取)
- `ui.txt` ← _universal.txt + ui_types.txt + interaction_primer.txt + operation_modes.txt + components.txt + accessibility.txt
- `feedback.txt` ← 9 个独立 txt 合并
- `route_config.yml` ← route_config.yml + error_types.yml
- plans/ 全部归档（内容已并入 kb）

## 注入时机

- **启动注入（turn 1）**：`load_startup_knowledge(goal)` → apps.txt + tasks.txt 的 #k 块按 goal 关键词匹配
- **转向注入（turn 3/6/9）**：`load_steering_knowledge(goal, turn)` → ui.txt 的 #pull-on 块按触发词匹配
- **反馈注入（运行时）**：Capability 检测异常 → `load_feedback(name)` 从 feedback.txt 加载 → 写 pending_feedback → 下轮注入
