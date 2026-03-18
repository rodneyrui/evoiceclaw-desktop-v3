"""配置加载：YAML + 环境变量替换 + Secrets 分离存储

存储分离原则:
- config.yaml: 非敏感配置（可入版本控制）
- secrets.yaml: API Key 等敏感数据（.gitignore 排除）
- load_config() 在内存中合并两者供运行时使用
"""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger("evoiceclaw.config")

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent
SECRETS_PATH = _DEFAULT_CONFIG_DIR / "secrets.yaml"


CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.yaml"


def _load_yaml(path: Path) -> dict:
    """加载 YAML 文件，支持 ${ENV_VAR} 环境变量替换。"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", str(value))
    return yaml.safe_load(raw) or {}


def load_secrets() -> dict:
    """加载 secrets.yaml — 仅包含 API key 等敏感数据。

    格式示例:
        llm:
          api_key: sk-xxx
        providers:
          deepseek:
            api_key: sk-yyy
          qwen:
            api_key: sk-zzz
        services:
          bocha:
            api_key: sk-aaa
    """
    return _load_yaml(SECRETS_PATH)


def save_secrets(secrets: dict) -> None:
    """写入 secrets.yaml。"""
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(secrets, f, allow_unicode=True, default_flow_style=False)
    logger.info("[Secrets] 已保存 secrets.yaml")


def load_config(config_path: str | None = None) -> dict:
    """加载 config.yaml 并合并 secrets.yaml 中的 API key。"""
    if config_path is None:
        config_path = _DEFAULT_CONFIG_DIR / "config.yaml"
    else:
        config_path = Path(config_path)

    config = _load_yaml(config_path)
    secrets = load_secrets()

    # 合并 llm.api_key
    if "llm" in secrets and "api_key" in secrets["llm"]:
        config.setdefault("llm", {})["api_key"] = secrets["llm"]["api_key"]

    # 合并 providers.*.api_key
    secret_providers = secrets.get("providers", {})
    for pid, secret_cfg in secret_providers.items():
        if isinstance(secret_cfg, dict) and "api_key" in secret_cfg:
            config.setdefault("providers", {}).setdefault(pid, {})["api_key"] = secret_cfg["api_key"]

    # 合并 services.*.api_key
    secret_services = secrets.get("services", {})
    for sid, secret_cfg in secret_services.items():
        if isinstance(secret_cfg, dict) and "api_key" in secret_cfg:
            config.setdefault("services", {}).setdefault(sid, {})["api_key"] = secret_cfg["api_key"]

    return config


def strip_secrets_from_config(config: dict) -> dict:
    """从 config dict 中移除所有 api_key 字段（用于写回 config.yaml）。"""
    out = dict(config)

    # 清除 llm.api_key
    if "llm" in out and isinstance(out["llm"], dict):
        out["llm"] = {k: v for k, v in out["llm"].items() if k != "api_key"}

    # 清除 providers.*.api_key
    if "providers" in out and isinstance(out["providers"], dict):
        cleaned = {}
        for pid, pcfg in out["providers"].items():
            if isinstance(pcfg, dict):
                cleaned[pid] = {k: v for k, v in pcfg.items() if k != "api_key"}
            else:
                cleaned[pid] = pcfg
        out["providers"] = cleaned

    # 清除 services.*.api_key
    if "services" in out and isinstance(out["services"], dict):
        cleaned = {}
        for sid, scfg in out["services"].items():
            if isinstance(scfg, dict):
                cleaned[sid] = {k: v for k, v in scfg.items() if k != "api_key"}
            else:
                cleaned[sid] = scfg
        out["services"] = cleaned

    return out


def validate_config() -> list[str]:
    """检查配置文件是否存在、关键字段是否完整，返回警告列表。

    不抛异常，只记录日志。调用方根据返回的警告列表决定是否继续启动。
    """
    warnings: list[str] = []

    # 检查 config.yaml 是否存在
    if not CONFIG_PATH.exists():
        # 尝试找到可用的示例文件
        examples = sorted(CONFIG_PATH.parent.glob("config.example.*.yaml"))
        example_names = ", ".join(f.name for f in examples) if examples else "config.example.*.yaml"
        warnings.append(
            f"config.yaml 不存在。请从示例文件复制：\n"
            f"  cp {example_names.split(',')[0].strip()} config.yaml\n"
            f"  可用示例: {example_names}"
        )

    # 检查 secrets.yaml 是否存在
    if not SECRETS_PATH.exists():
        warnings.append(
            f"secrets.yaml 不存在，所有 LLM 调用将因缺少 API Key 而失败。请复制示例文件：\n"
            f"  cp secrets.yaml.example secrets.yaml\n"
            f"  然后填入你的 API Key"
        )

    # 如果文件存在，检查关键字段
    if CONFIG_PATH.exists():
        config = _load_yaml(CONFIG_PATH)
        if not config.get("llm", {}).get("model"):
            warnings.append("config.yaml 中 llm.model 未配置，LLM 调用将使用空模型名")
        if not config.get("providers"):
            warnings.append("config.yaml 中 providers 为空，未配置任何模型提供商")

    if SECRETS_PATH.exists():
        secrets = _load_yaml(SECRETS_PATH)
        has_any_key = False
        if secrets.get("llm", {}).get("api_key"):
            has_any_key = True
        for _, pcfg in secrets.get("providers", {}).items():
            if isinstance(pcfg, dict) and pcfg.get("api_key"):
                has_any_key = True
                break
        if not has_any_key:
            warnings.append("secrets.yaml 中未配置任何 API Key")

    return warnings
