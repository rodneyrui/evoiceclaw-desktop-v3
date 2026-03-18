"""Config API：配置读写 + Secrets 管理

安全原则：
- GET /config 返回的 api_key 一律脱敏为 "***"
- PUT /config 写入前自动剥离 api_key 字段
- PUT /secrets 仅接受 api_key 更新
- GET /secrets/status 仅返回是否已配置，不返回实际值
"""

import logging
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_config
from app.core.config import (
    load_config,
    load_secrets,
    save_secrets,
    strip_secrets_from_config,
    _DEFAULT_CONFIG_DIR,
)

logger = logging.getLogger("evoiceclaw.api.config")

router = APIRouter()

ConfigDep = Annotated[dict, Depends(get_config)]


def _mask_api_keys(config: dict) -> dict:
    """将所有 api_key 字段替换为 '***'"""
    import copy
    masked = copy.deepcopy(config)

    if "llm" in masked and isinstance(masked["llm"], dict) and "api_key" in masked["llm"]:
        masked["llm"]["api_key"] = "***"

    for section in ("providers", "services"):
        if section in masked and isinstance(masked[section], dict):
            for key, val in masked[section].items():
                if isinstance(val, dict) and "api_key" in val:
                    val["api_key"] = "***"

    return masked


@router.get("")
async def get_config_api(config: ConfigDep):
    """获取当前配置（api_key 已脱敏）"""
    return _mask_api_keys(config)


class ConfigUpdateRequest(BaseModel):
    config: dict


@router.put("")
async def update_config(body: ConfigUpdateRequest, request: Request):
    """更新非敏感配置（自动剥离 api_key 字段）"""
    cleaned = strip_secrets_from_config(body.config)

    config_path = _DEFAULT_CONFIG_DIR / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cleaned, f, allow_unicode=True, default_flow_style=False)

    # 刷新运行时配置（合并最新的 config.yaml + secrets.yaml）
    request.app.state.config = load_config()
    logger.info("[Config API] config.yaml 已更新，运行时配置已刷新")
    return {"status": "ok", "message": "配置已保存"}


@router.get("/secrets/status")
async def get_secrets_status():
    """获取 Secrets 配置状态（仅返回是否已配置，不返回实际值）"""
    secrets = load_secrets()

    status: dict[str, bool] = {}

    # llm
    if "llm" in secrets and secrets["llm"].get("api_key"):
        status["llm"] = True

    # providers
    for pid, pcfg in secrets.get("providers", {}).items():
        if isinstance(pcfg, dict) and pcfg.get("api_key"):
            status[f"providers.{pid}"] = True

    # services
    for sid, scfg in secrets.get("services", {}).items():
        if isinstance(scfg, dict) and scfg.get("api_key"):
            status[f"services.{sid}"] = True

    return {"configured": status}


class SecretsUpdateRequest(BaseModel):
    secrets: dict


_MAX_MERGE_DEPTH = 5  # 递归合并最大深度，防止嵌套攻击


@router.put("/secrets")
async def update_secrets(body: SecretsUpdateRequest, request: Request):
    """更新 Secrets（API Key 等敏感数据）

    仅接受非 "***" 的 api_key 值（脱敏值不覆盖真实值）。
    """
    existing = load_secrets()

    def _merge_secrets(existing: dict, incoming: dict, depth: int = 0) -> dict:
        """递归合并，跳过 '***' 值，限制递归深度"""
        if depth > _MAX_MERGE_DEPTH:
            logger.warning("[Config API] secrets 合并超过最大深度 %d，跳过", _MAX_MERGE_DEPTH)
            return existing
        for key, val in incoming.items():
            # SA-11: key 必须是字符串
            if not isinstance(key, str):
                continue
            if isinstance(val, dict):
                existing.setdefault(key, {})
                if isinstance(existing[key], dict):
                    _merge_secrets(existing[key], val, depth + 1)
            elif isinstance(val, str) and val != "***" and val:
                existing[key] = val
        return existing

    merged = _merge_secrets(existing, body.secrets)
    save_secrets(merged)

    # 刷新运行时配置（合并最新的 config.yaml + secrets.yaml）
    request.app.state.config = load_config()
    logger.info("[Config API] secrets.yaml 已更新，运行时配置已刷新")
    return {"status": "ok", "message": "Secrets 已保存"}
