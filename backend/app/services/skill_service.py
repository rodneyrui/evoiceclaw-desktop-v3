"""Skill 生命周期服务：安装/更新/卸载/列表

管理 data/skills/{skill_name}/ 目录结构：
├── SKILL.md              # 改写后的安全版本
├── SKILL.md.original     # 原始版本（备份）
├── ACTIONS.yaml          # 提取的命令白名单
├── REVIEW.json           # 审查报告
└── VERSION.json          # 版本记录
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

from app.security.audit import log_event, new_trace_id, LEVEL_WARN
from app.security.gatekeeper.gatekeeper import review_skill
from app.security.gatekeeper.models import ActionDeclaration, ReviewResult, SkillMeta

logger = logging.getLogger("evoiceclaw.services.skill_service")

# Skills 安装目录（data/skills/）
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = _BACKEND_DIR / "data" / "skills"


def _ensure_skills_dir() -> None:
    """确保 skills 目录存在"""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def _content_hash(content: str) -> str:
    """计算内容 SHA-256 哈希"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _skill_dir(name: str) -> Path:
    """获取 Skill 目录路径"""
    # 安全：禁止路径穿越
    safe_name = name.replace("/", "_").replace("..", "_").strip(".")
    return SKILLS_DIR / safe_name


async def install_skill(name: str, skill_md: str, config: dict, authorization_mode: str = "once") -> SkillMeta:
    """安装一个 Skill

    1. 调用守门员审查
    2. 保存文件（原始+改写+审查报告+版本信息+ACTIONS）
    3. 写审计日志
    4. 返回安装结果

    Args:
        name: Skill 名称
        skill_md: 原始 SKILL.md 内容
        config: 全局配置

    Returns:
        SkillMeta 元数据

    Raises:
        ValueError: 审查被拒绝时
    """
    _ensure_skills_dir()
    trace_id = new_trace_id()

    log_event(
        component="skill_service",
        action="INSTALL_START",
        trace_id=trace_id,
        detail=f"name={name}, md_len={len(skill_md)}",
    )

    # 调用守门员审查
    result: ReviewResult = await review_skill(skill_md, config)

    if result.status == "rejected":
        log_event(
            component="skill_service",
            action="INSTALL_REJECTED",
            trace_id=trace_id,
            detail=f"name={name}, report={result.safety_report[:200]}",
            level=LEVEL_WARN,
        )
        raise ValueError(f"Skill '{name}' 审查被拒绝: {result.safety_report}")

    # 确定最终 SKILL.md 内容
    final_md = result.rewritten_content if result.rewritten_content else skill_md

    # 创建 Skill 目录并写入文件
    skill_path = _skill_dir(name)
    skill_path.mkdir(parents=True, exist_ok=True)

    # 保存原始版本
    (skill_path / "SKILL.md.original").write_text(skill_md, encoding="utf-8")

    # 保存改写/审查后版本
    (skill_path / "SKILL.md").write_text(final_md, encoding="utf-8")

    # 保存 ACTIONS.yaml
    actions_data = [a.to_dict() for a in result.actions]
    with open(skill_path / "ACTIONS.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"actions": actions_data}, f, allow_unicode=True, default_flow_style=False)

    # 保存审查报告
    review_data = result.to_dict()
    review_data["reviewed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with open(skill_path / "REVIEW.json", "w", encoding="utf-8") as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)

    # 保存版本信息
    version_data = {
        "name": name,
        "version": "1.0.0",
        "content_hash": _content_hash(skill_md),
        "installed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "gatekeeper_model": result.model_used,
        "status": result.status,
        "authorization_mode": authorization_mode,
    }
    with open(skill_path / "VERSION.json", "w", encoding="utf-8") as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)

    meta = SkillMeta(
        name=name,
        version="1.0.0",
        content_hash=_content_hash(skill_md),
        reviewed_at=version_data["installed_at"],
        gatekeeper_model=result.model_used,
        status=result.status,
        actions=result.actions,
        authorization_mode=authorization_mode,
    )

    log_event(
        component="skill_service",
        action="INSTALL_OK",
        trace_id=trace_id,
        detail=f"name={name}, status={result.status}, actions={len(result.actions)}",
        duration_ms=result.duration_ms,
    )

    return meta


async def update_skill(name: str, new_skill_md: str, config: dict) -> SkillMeta:
    """更新一个 Skill

    对比 content_hash，变化则重新审查。
    保存旧版为 .previous。

    Args:
        name: Skill 名称
        new_skill_md: 新的 SKILL.md 内容
        config: 全局配置

    Returns:
        SkillMeta 更新后的元数据
    """
    skill_path = _skill_dir(name)

    if not skill_path.is_dir():
        # 不存在则按新安装处理
        return await install_skill(name, new_skill_md, config)

    # 检查内容是否变化
    old_hash = ""
    version_file = skill_path / "VERSION.json"
    if version_file.is_file():
        try:
            old_data = json.loads(version_file.read_text(encoding="utf-8"))
            old_hash = old_data.get("content_hash", "")
        except Exception as e:
            logger.debug("[SkillService] 读取 VERSION.json 失败: %s", e)

    new_hash = _content_hash(new_skill_md)
    if old_hash == new_hash:
        logger.info("[SkillService] Skill '%s' 内容未变化，跳过更新", name)
        meta = get_skill_meta(name)
        if meta:
            return meta
        # meta 读取失败，按新安装处理
        return await install_skill(name, new_skill_md, config)

    # 内容变化，备份旧版
    for fname in ("SKILL.md", "SKILL.md.original", "ACTIONS.yaml", "REVIEW.json", "VERSION.json"):
        src = skill_path / fname
        if src.is_file():
            dst = skill_path / f"{fname}.previous"
            dst.write_bytes(src.read_bytes())

    # 重新安装（走完整审查流程）
    return await install_skill(name, new_skill_md, config)


def uninstall_skill(name: str) -> bool:
    """卸载一个 Skill（删除整个目录）

    Args:
        name: Skill 名称

    Returns:
        是否成功
    """
    import shutil

    skill_path = _skill_dir(name)
    if not skill_path.is_dir():
        return False

    trace_id = new_trace_id()
    log_event(
        component="skill_service",
        action="UNINSTALL",
        trace_id=trace_id,
        detail=f"name={name}",
    )

    try:
        shutil.rmtree(skill_path)
        return True
    except Exception as e:
        logger.error("[SkillService] 卸载失败: %s — %s", name, e)
        return False


def list_skills() -> list[SkillMeta]:
    """列出所有已安装的 Skill

    Returns:
        SkillMeta 列表
    """
    _ensure_skills_dir()
    result: list[SkillMeta] = []

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        meta = get_skill_meta(skill_dir.name)
        if meta:
            result.append(meta)

    return result


def get_skill(name: str) -> tuple[str, SkillMeta] | None:
    """获取 Skill 内容和元数据

    Returns:
        (SKILL.md 内容, SkillMeta) 或 None
    """
    skill_path = _skill_dir(name)
    skill_md = skill_path / "SKILL.md"

    if not skill_md.is_file():
        return None

    content = skill_md.read_text(encoding="utf-8")
    meta = get_skill_meta(name)
    if not meta:
        return None

    return content, meta


def get_skill_meta(name: str) -> SkillMeta | None:
    """获取 Skill 元数据"""
    skill_path = _skill_dir(name)
    version_file = skill_path / "VERSION.json"

    if not version_file.is_file():
        return None

    try:
        data = json.loads(version_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    # 加载 actions
    actions = get_skill_actions(name) or []

    return SkillMeta(
        name=data.get("name", name),
        version=data.get("version", "1.0.0"),
        content_hash=data.get("content_hash", ""),
        reviewed_at=data.get("installed_at", ""),
        gatekeeper_model=data.get("gatekeeper_model", ""),
        status=data.get("status", "unknown"),
        actions=actions,
        authorization_mode=data.get("authorization_mode", "once"),
    )


def get_skill_actions(name: str) -> list[ActionDeclaration] | None:
    """获取 Skill 的动作声明列表

    Returns:
        ActionDeclaration 列表或 None
    """
    skill_path = _skill_dir(name)
    actions_file = skill_path / "ACTIONS.yaml"

    if not actions_file.is_file():
        return None

    try:
        with open(actions_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    raw_actions = data.get("actions", [])
    return [
        ActionDeclaration(
            command=a.get("command", ""),
            pattern=a.get("pattern", ""),
            description=a.get("description", ""),
        )
        for a in raw_actions
        if isinstance(a, dict) and a.get("command")
    ]
