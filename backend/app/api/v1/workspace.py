"""工作区管理 REST API

端点：
  GET    /workspaces          — 列出所有工作区
  POST   /workspaces          — 注册新工作区
  GET    /workspaces/active   — 获取当前激活工作区
  GET    /workspaces/{id}     — 获取单个工作区详情
  POST   /workspaces/{id}/activate  — 激活工作区
  DELETE /workspaces/{id}     — 注销工作区
  GET    /workspaces/{id}/tree      — 获取文件树
  PATCH  /workspaces/{id}     — 更新工作区字段（name/description/shell_enabled/shell_level/network_whitelist/env_vars）
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.workspace_service import get_workspace_service

logger = logging.getLogger("evoiceclaw.api.workspace")

router = APIRouter()


# ── 请求/响应模型 ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    path: str
    description: str = ""


class PatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    shell_enabled: bool | None = None
    shell_level: str | None = None
    network_whitelist: list[str] | None = None
    env_vars: dict[str, str] | None = None


def _ws_to_dict(ws) -> dict[str, Any]:
    """将 Workspace dataclass 转为 API 响应字典"""
    return {
        "id": ws.id,
        "name": ws.name,
        "path": ws.path,
        "description": ws.description,
        "created_at": ws.created_at,
        "last_accessed": ws.last_accessed,
        "active": ws.active,
        "shell_enabled": ws.shell_enabled,
        "shell_level": ws.shell_level,
        "network_whitelist": ws.network_whitelist,
        "env_vars": ws.env_vars,
    }


# ── 端点 ───────────────────────────────────────────────────────────────────────

@router.get("")
def list_workspaces():
    """列出所有工作区"""
    svc = get_workspace_service()
    return [_ws_to_dict(ws) for ws in svc.list_workspaces()]


@router.post("", status_code=201)
def register_workspace(req: RegisterRequest):
    """注册新工作区"""
    svc = get_workspace_service()
    try:
        ws = svc.register_workspace(req.name, req.path, req.description)
        return _ws_to_dict(ws)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotADirectoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("注册工作区失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
def get_active_workspace():
    """获取当前激活工作区，无激活工作区返回 null"""
    svc = get_workspace_service()
    ws = svc.get_active_workspace()
    return _ws_to_dict(ws) if ws else None


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str):
    """获取单个工作区详情"""
    svc = get_workspace_service()
    ws = svc.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区不存在: {workspace_id}")
    return _ws_to_dict(ws)


@router.post("/{workspace_id}/activate")
def activate_workspace(workspace_id: str):
    """激活工作区"""
    svc = get_workspace_service()
    try:
        ws = svc.activate_workspace(workspace_id)
        return _ws_to_dict(ws)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("激活工作区失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{workspace_id}", status_code=204)
def unregister_workspace(workspace_id: str):
    """注销工作区（仅删除元数据，不删除项目文件）"""
    svc = get_workspace_service()
    ok = svc.unregister_workspace(workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"工作区不存在: {workspace_id}")


@router.get("/{workspace_id}/tree")
def get_file_tree(workspace_id: str):
    """获取工作区项目文件树"""
    svc = get_workspace_service()
    try:
        tree = svc.get_file_tree(workspace_id)
        return {"tree": tree}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("获取文件树失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{workspace_id}")
def patch_workspace(workspace_id: str, req: PatchRequest):
    """更新工作区字段"""
    svc = get_workspace_service()
    ws = svc.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区不存在: {workspace_id}")

    updates = req.model_dump(exclude_none=True)
    for field_name, value in updates.items():
        svc.update_workspace_field(workspace_id, field_name, value)

    return _ws_to_dict(svc.get_workspace(workspace_id))
