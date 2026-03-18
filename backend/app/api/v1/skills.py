"""Skills API：Skill 安装/卸载/列表/详情"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_config
from app.services.skill_service import (
    install_skill,
    update_skill,
    uninstall_skill,
    list_skills,
    get_skill,
)

logger = logging.getLogger("evoiceclaw.api.skills")

router = APIRouter()

ConfigDep = Annotated[dict, Depends(get_config)]


class InstallRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[a-zA-Z0-9_\-]+$',
        description="Skill 名称（只允许字母、数字、下划线和短横线）",
    )
    skill_md: str = Field(
        ...,
        min_length=10,
        max_length=65536,   # 64KB 上限，防止超大内容耗尽 LLM context
        description="SKILL.md 内容",
    )


class SkillResponse(BaseModel):
    name: str
    version: str
    status: str
    content_hash: str
    reviewed_at: str
    gatekeeper_model: str
    actions: list[dict]


class SkillDetailResponse(SkillResponse):
    content: str


@router.get("", response_model=list[SkillResponse])
async def list_all_skills():
    """列出所有已安装的 Skill"""
    skills = list_skills()
    return [s.to_dict() for s in skills]


@router.post("", response_model=SkillResponse, status_code=201)
async def install_new_skill(body: InstallRequest, config: ConfigDep):
    """安装一个新 Skill（经守门员审查）"""
    try:
        meta = await install_skill(body.name, body.skill_md, config)
        return meta.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.put("/{name}", response_model=SkillResponse)
async def update_existing_skill(name: str, body: InstallRequest, config: ConfigDep):
    """更新 Skill（内容变化时重新审查）"""
    try:
        meta = await update_skill(name, body.skill_md, config)
        return meta.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{name}", response_model=SkillDetailResponse)
async def get_skill_detail(name: str):
    """获取 Skill 详情（含 SKILL.md 内容）"""
    result = get_skill(name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' 未找到")
    content, meta = result
    data = meta.to_dict()
    data["content"] = content
    return data


@router.delete("/{name}")
async def delete_skill(name: str):
    """卸载一个 Skill"""
    ok = uninstall_skill(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' 未找到")
    return {"status": "ok", "message": f"Skill '{name}' 已卸载"}
