"""phonefast shim——AW 评测代码的设备访问层（adb 全部走 pf.shell()）。

模块：
- interface.py             AsyncEnv + execute_adb_call 翻译
- android_world_controller.py  controller（pull/push_file、click_element、send_sms）
- adb_utils.py             AW 原版 adb_utils（vendored，经 env.execute_adb_call 走 phonefast）
- setup.py                 install_app_if_not_installed（emulator_setup 已装 app）
- android_env_stub/        android_env 类型/常量最小 stub
"""
