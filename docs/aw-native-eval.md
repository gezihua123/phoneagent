# AW 原生评测层（fastaget/aw_native/）

> 评测层完全采用 AndroidWorld 的 TaskEval 体系——goal/params/initialize_task/
> is_successful/tear_down 全部是 AW 原版代码，设备访问经 phonefast shim。

## 动机

旧 shell 体系（scripts/aw + eval_cases_aw_aligned.yml）与 AW 有 4 处机制不等价：

| 缺口 | AW 原生体系 |
|------|------------|
| 评分粒度（旧：二元 all-pass） | ✅ is_successful 返回 0.0-1.0，部分分原生支持 |
| IR 答案校验（旧：只查 activity） | ✅ success_criteria 字段变换 + interaction_cache 原生生效 |
| tear_down（旧：通用状态隔离） | ✅ 每 task 的 tear_down() 原样执行 |
| 判定表达力（旧：shell+expect） | ✅ 任意 Python 判定逻辑 |

## 目录结构

```
fastaget/aw_native/
├── vendor/              # AW 代码（从 ~/Downloads/android_world 拷入，import 改写）
│   ├── task_evals/      # task_eval.py + single/composite/information_retrieval/
│   ├── env/             # device_constants/json_action/representation_utils/tools/
│   ├── registry.py      # TaskRegistry（family: android / information_retrieval）
│   └── utils/           # file_utils/app_snapshot/datetime_utils/contacts_utils
├── shim/                # phonefast 后端的设备访问层（新写）
│   ├── interface.py     # AsyncEnv + execute_adb_call 翻译（AdbRequest → pf 调用）
│   ├── android_world_controller.py  # controller（pull/push_file、click_element、send_sms）
│   ├── adb_utils.py     # AW 原版 adb_utils（vendored，经 env.execute_adb_call）
│   ├── setup.py         # install_app_if_not_installed（emulator_setup 已装 app）
│   └── android_env_stub/  # android_env 类型/常量最小 stub
└── (入口在 scripts/run_eval_native.py)
```

## 关键设计

1. **参数生成走 AW 原生**：`random.seed(FIXED_SEED=42)` → `cls.generate_random_params()`
   → 实例化 → `goal = template.format(params)`。零手工配置，AW 更新自动同步。
2. **设备访问零 adb 直调**：AW 代码里所有 adb 调用最终落到
   `env.execute_adb_call(AdbRequest)`，shim 把它翻译为 `pf.shell()/pf.tap()/pf.key()`。
   多设备安全：Phonefast 由 CLI 层创建注入（`shim.interface.set_pf(pf)`）。
3. **IR 答案通道**：agent 完成后评测入口把 `result.summary` 写入
   `env.interaction_cache` → AW 原生 `proto_utils.check_agent_answer` 校验。
4. **shim 环境适配**（AW 官方镜像正常、本模拟器需要的补丁）：
   - Clipper 剪贴板：API 33 上 clipper.get 广播读剪贴板受限 → shim 缓存 set 内容，
     get 空结果回填缓存（保持 set→get 自检语义）
   - `_create_test_mp3`：pydub 在 Py3.13 不可用 → stdlib wave 写静音
     （.mp3 文件名 + WAV 内容，MediaPlayer 按内容探测）
   - app snapshot：restore_snapshot 找不到快照只 warning 跳过（AW 原行为）

## 使用

```bash
# 枚举可评测 task（116 = android 91 + IR 25）
python3 scripts/run_eval_native.py --list

# 子集（逗号分隔子串）
python3 scripts/run_eval_native.py --only CameraTakePhoto,SmsSend

# 全量 116
python3 scripts/run_eval_native.py

# 实时进度
tail -f build/eval_aw_native/run01/report.txt
```

报告（report.json）含：score（0.0-1.0，AW 原生）、passed（≥1.0）、
agent_success（自报对照）、steps/cost/elapsed、init_err/verify_err。

成功率 = score ≥ 1.0 的占比（AW 定义）。报告同时给 agent 自报率做误报对照。

## 依赖

```bash
python3 -m pip install absl-py protobuf grpcio-tools
```

proto 重编译（task.proto/state.proto 变更时）：
```bash
cd fastaget/aw_native/vendor/task_evals/information_retrieval/proto
python3 -m grpc_tools.protoc -I. --python_out=. task.proto state.proto
# 然后修 task_pb2.py 里的裸 import state_pb2 为包内路径
```

## 宪法合规

- 评测层硬隔离：agent/tools/device/cli 不得 import fastaget.aw_native
- adb 只走 pf.shell()：shim 全量拦截，vendor 代码零 subprocess adb
- 评测环境：emulator-5554
