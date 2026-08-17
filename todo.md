# 测试脚本
```bash
cd /Users/mulei/Desktop/fastaget && \
  export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" && \
  export ANTHROPIC_AUTH_TOKEN="sk-xxx" && \
  unset ANTHROPIC_MODEL && \
  python3 -m fastaget.cli run \
    --serial  emulator-5554 \
    --model deepseek-v4-flash \
    --max-steps 15 \
    --verbose-timing \
    --trace \
    "打开googleplay,安装instagram" \
    2>&1 | tee logs/baidu_$(date +%Y%m%d_%H%M).log
```

```
cd /Users/mulei/Desktop/fastaget && \
  export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" && \
  export ANTHROPIC_AUTH_TOKEN="sk-xxx" && \
  unset ANTHROPIC_MODEL && \
  python3 -m fastaget.cli run \
    --serial emulator-5554 \
    --model deepseek-v4-flash \
    --max-steps 30 \
    --verbose-timing \
    --trace \
    "打开camera 拍照,并且分享到小红书" \
    2>&1 | tee reports/aw_batch/$(date +%Y%m%d_%H%M).log
```