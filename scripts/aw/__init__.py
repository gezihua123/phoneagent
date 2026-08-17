"""fastaget AndroidWorld 对齐桥接模块。

提供：
  data.py   — 固定测试数据（从 AndroidWorld schema 提取）
  init.py   — initialize 命令生成器（shell/SQLite/content provider）
  verify.py — verify 命令 + 判定逻辑

原则：
  - 数据固化（不随机生成），保证可重复评测
  - 零 android_env 依赖，纯 shell/python 标准库
  - 命令通过 phonefast.shell() 或 adb shell 执行
"""
