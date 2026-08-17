"""CredentialManager：凭证管理——密钥/密码脱敏注入。

原则：密钥值永不出现在 LLM prompt 或 message history 中。
LLM 只看到 secret_id（如 "WIFI_PASSWORD"），实际值在工具执行时由 manager 解析。

YAML 格式（meta/credentials.yml）：
    secrets:
      WIFI_PASSWORD:
        value: "mysecret"
        enabled: true
      SIMPLE_KEY: "simple_value"  # 简写，自动 enabled
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class CredentialNotFoundError(KeyError):
    """请求的 secret_id 不存在。"""


@dataclass
class CredentialManager:
    """凭证管理器：加载 YAML/dict，按 secret_id 安全解析。

    Usage:
        cm = CredentialManager()
        cm.load_yaml("fastaget/meta/credentials.yml")
        value = cm.resolve("WIFI_PASSWORD")  # → "mysecret"
        cm.list_ids()  # → ["WIFI_PASSWORD", "SIMPLE_KEY"]
    """

    _secrets: dict[str, str] = field(default_factory=dict)

    # ── 加载 ──

    def load_yaml(self, path: str | Path) -> int:
        """从 YAML 文件加载凭证。返回成功加载的条目数。"""
        fpath = Path(path)
        if not fpath.is_file():
            return 0
        try:
            data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(data, dict) or "secrets" not in data:
            return 0
        return self._load_secrets_block(data["secrets"])

    def load_dict(self, raw: dict[str, str]) -> int:
        """从 dict 加载凭证（用于测试/代码注入）。返回成功加载的条目数。"""
        return self._load_secrets_block(raw)

    def _load_secrets_block(self, secrets_block: dict | None) -> int:
        """解析 secrets 块：支持展开格式 {value, enabled} 和简写格式。"""
        if not secrets_block:
            return 0
        count = 0
        for sid, spec in secrets_block.items():
            if isinstance(spec, dict):
                enabled = spec.get("enabled", True)
                value = spec.get("value", "")
            else:
                enabled = True
                value = str(spec)
            if enabled and value:
                self._secrets[sid] = value
                count += 1
        return count

    # ── 解析 ──

    def resolve(self, secret_id: str) -> str:
        """安全解析凭证值。找不到抛 CredentialNotFoundError。"""
        if secret_id not in self._secrets:
            available = sorted(self._secrets.keys())
            raise CredentialNotFoundError(
                f"Secret '{secret_id}' not found. Available: {available}"
            )
        return self._secrets[secret_id]

    def list_ids(self) -> list[str]:
        """列出所有可用的 secret_id（供工具描述注入）。"""
        return sorted(self._secrets.keys())

    # ── 查询 ──

    def __len__(self) -> int:
        return len(self._secrets)

    def __contains__(self, secret_id: str) -> bool:
        return secret_id in self._secrets

    def __repr__(self) -> str:
        ids = self.list_ids()
        return f"<CredentialManager secrets={len(ids)} ids={ids[:5]}{'...' if len(ids) > 5 else ''}>"
