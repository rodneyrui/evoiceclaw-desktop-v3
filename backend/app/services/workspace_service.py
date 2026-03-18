"""工作区管理服务

管理注册的项目工作区。工作区元数据存储在 ~/.evoiceclaw/workspaces/ 目录中，
每个工作区对应一个以 slug 命名的子目录，元数据文件为 .meta.json。

示例：
    ~/.evoiceclaw/workspaces/evoiceclaw-app/.meta.json
    ~/.evoiceclaw/workspaces/默认工作区/.meta.json

功能：
- 注册/注销工作区（仅管理元数据，不触碰项目文件）
- 激活/切换工作区（同一时间只有一个工作区处于激活状态）
- 查看工作区文件树

全局单例模式：init_workspace_service() / get_workspace_service()
"""

import json
import logging
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("evoiceclaw.services.workspace")

# 工作区元数据存储根目录
_WORKSPACES_ROOT = Path.home() / ".evoiceclaw" / "workspaces"

# 元数据文件名
_META_FILENAME = ".meta.json"

# 生成文件树时排除的目录名
_TREE_EXCLUDE_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv", "dist",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "venv", "env", ".env", ".eggs", "*.egg-info",
}


@dataclass
class Workspace:
    """工作区数据模型"""
    id: str                    # slug（也是目录名）
    name: str                  # 显示名
    path: str                  # 项目根目录绝对路径
    description: str = ""
    created_at: str = ""       # ISO 8601 格式时间戳
    last_accessed: str = ""    # 最后访问时间
    active: bool = False       # 是否为当前激活工作区
    shell_enabled: bool = False        # 是否启用 Shell（宪法第11条）
    shell_level: str = "L1"            # Shell 安全级别
    network_whitelist: list[str] = field(default_factory=list)  # 域名白名单
    env_vars: dict[str, str] = field(default_factory=dict)      # 非敏感环境变量


class WorkspaceService:
    """工作区管理服务（全局单例）"""

    def __init__(self) -> None:
        # 确保元数据根目录存在
        _WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Slug 生成
    # ------------------------------------------------------------------

    @staticmethod
    def _name_to_slug(name: str) -> str:
        """从工作区名称生成 slug（用作目录名和 ID）

        规则：
        - ASCII 字母转小写
        - 空格和特殊字符替换为 -
        - 合并连续的 -
        - 去除首尾 -
        - 保留中文字符
        - 空结果回退为 'workspace'

        示例：
            "eVoiceClaw App"  → "evoiceclaw-app"
            "默认工作区"       → "默认工作区"
            "My Project v2.0" → "my-project-v2-0"
        """
        slug = name.strip()
        # ASCII 部分转小写
        slug = slug.lower()
        # 保留：字母、数字、中文、-
        # 替换其他字符为 -
        slug = re.sub(r'[^\w\u4e00-\u9fff-]', '-', slug)
        # _ 也替换为 -（\w 包含 _）
        slug = slug.replace('_', '-')
        # 合并连续 -
        slug = re.sub(r'-+', '-', slug)
        # 去除首尾 -
        slug = slug.strip('-')

        return slug or "workspace"

    def _unique_slug(self, slug: str) -> str:
        """确保 slug 不与已有目录冲突，必要时添加数字后缀"""
        if not (_WORKSPACES_ROOT / slug).exists():
            return slug
        for i in range(2, 100):
            candidate = f"{slug}-{i}"
            if not (_WORKSPACES_ROOT / candidate).exists():
                return candidate
        # 极端情况回退
        import uuid
        return f"{slug}-{uuid.uuid4().hex[:6]}"

    # ------------------------------------------------------------------
    # 默认工作区
    # ------------------------------------------------------------------

    # 默认工作区路径（macOS 用户可见位置）
    _DEFAULT_WS_PATH = Path.home() / "Desktop" / "eVoiceClaw"
    _DEFAULT_WS_NAME = "默认工作区"
    _DEFAULT_WS_DESC = "系统默认工作区，用于 Agent 存放工作成果"

    def _ensure_default_workspace(self) -> None:
        """确保至少存在一个工作区。

        首次启动时自动创建默认工作区并激活，避免用户需要手动注册。
        如果已有任何工作区（不论是否激活），不做任何操作。
        """
        existing = self.list_workspaces()
        if existing:
            logger.debug("已有 %d 个工作区，跳过默认创建", len(existing))
            return

        # 创建默认目录
        default_path = self._DEFAULT_WS_PATH
        default_path.mkdir(parents=True, exist_ok=True)
        logger.info("创建默认工作区目录: %s", default_path)

        # 注册
        ws = self.register_workspace(
            name=self._DEFAULT_WS_NAME,
            path=str(default_path),
            description=self._DEFAULT_WS_DESC,
        )

        # 激活
        self.activate_workspace(ws.id)

        # 启用 Shell L1
        self.update_workspace_field(ws.id, "shell_enabled", True)
        self.update_workspace_field(ws.id, "shell_level", "L1")

        logger.info(
            "默认工作区已创建并激活: %s (%s) -> %s",
            ws.name, ws.id, ws.path,
        )

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def register_workspace(
        self,
        name: str,
        path: str,
        description: str = "",
    ) -> Workspace:
        """注册新工作区

        从名称生成 slug 作为 ID 和目录名，验证项目路径存在后写入元数据文件。

        Args:
            name: 工作区显示名
            path: 项目根目录绝对路径
            description: 可选描述

        Returns:
            新创建的 Workspace 对象

        Raises:
            FileNotFoundError: 项目路径不存在
            NotADirectoryError: 路径不是目录
        """
        project_path = Path(path).expanduser().resolve()
        if not project_path.exists():
            raise FileNotFoundError(f"路径不存在: {path}")
        if not project_path.is_dir():
            raise NotADirectoryError(f"路径不是目录: {path}")

        # 生成 slug 并确保唯一
        slug = self._name_to_slug(name)
        slug = self._unique_slug(slug)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ws = Workspace(
            id=slug,
            name=name,
            path=str(project_path),
            description=description,
            created_at=now,
            last_accessed=now,
            active=False,
        )
        self._save_workspace(ws)
        logger.info("注册工作区: %s (%s) -> %s", ws.name, ws.id, ws.path)
        return ws

    def list_workspaces(self) -> list[Workspace]:
        """列出所有注册的工作区，按 last_accessed 降序排列"""
        workspaces: list[Workspace] = []
        if not _WORKSPACES_ROOT.is_dir():
            return workspaces

        for ws_dir in sorted(_WORKSPACES_ROOT.iterdir()):
            if not ws_dir.is_dir():
                continue
            ws = self._load_workspace(ws_dir.name)
            if ws:
                workspaces.append(ws)

        # 按最后访问时间降序
        workspaces.sort(key=lambda w: w.last_accessed, reverse=True)
        return workspaces

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        """获取单个工作区

        Args:
            workspace_id: 工作区 ID（slug）

        Returns:
            Workspace 对象，不存在则返回 None
        """
        return self._load_workspace(workspace_id)

    def activate_workspace(self, workspace_id: str) -> Workspace:
        """激活指定工作区（同时取消其他工作区的激活状态）

        Args:
            workspace_id: 要激活的工作区 ID

        Returns:
            激活后的 Workspace 对象

        Raises:
            ValueError: 工作区不存在
        """
        target = self._load_workspace(workspace_id)
        if not target:
            raise ValueError(f"工作区不存在: {workspace_id}")

        # 取消所有工作区的激活状态
        for ws in self.list_workspaces():
            if ws.active and ws.id != workspace_id:
                ws.active = False
                self._save_workspace(ws)

        # 激活目标工作区并更新访问时间
        target.active = True
        target.last_accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._save_workspace(target)

        logger.info("激活工作区: %s (%s)", target.name, target.id)
        return target

    def get_active_workspace(self) -> Workspace | None:
        """获取当前激活的工作区

        Returns:
            激活的 Workspace 对象，无激活工作区则返回 None
        """
        for ws in self.list_workspaces():
            if ws.active:
                return ws
        return None

    def unregister_workspace(self, workspace_id: str) -> bool:
        """注销工作区（只删除元数据，不删除项目文件）

        Args:
            workspace_id: 要注销的工作区 ID

        Returns:
            是否成功注销
        """
        ws_dir = _WORKSPACES_ROOT / self._safe_id(workspace_id)
        if not ws_dir.is_dir():
            return False

        try:
            shutil.rmtree(ws_dir)
            logger.info("注销工作区: %s", workspace_id)
            return True
        except Exception as e:
            logger.error("注销工作区失败: %s — %s", workspace_id, e)
            return False

    def get_file_tree(self, workspace_id: str, max_depth: int = 3) -> str:
        """获取工作区项目的文件树

        遍历项目目录，排除常见无用目录（__pycache__、node_modules 等），
        返回格式化的树形字符串。

        Args:
            workspace_id: 工作区 ID
            max_depth: 最大遍历深度（默认 3 层）

        Returns:
            格式化的文件树字符串

        Raises:
            ValueError: 工作区不存在或项目路径无效
        """
        ws = self._load_workspace(workspace_id)
        if not ws:
            raise ValueError(f"工作区不存在: {workspace_id}")

        root = Path(ws.path)
        if not root.is_dir():
            raise ValueError(f"项目目录不存在或不可访问: {ws.path}")

        lines: list[str] = [f"{root.name}/"]
        self._build_tree(root, lines, prefix="", depth=0, max_depth=max_depth)

        # 更新访问时间
        ws.last_accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._save_workspace(ws)

        return "\n".join(lines)

    def update_workspace_field(self, workspace_id: str, field_name: str, value) -> bool:
        """更新工作区的单个字段

        Args:
            workspace_id: 工作区 ID
            field_name: 字段名
            value: 新值

        Returns:
            是否更新成功
        """
        ws = self._load_workspace(workspace_id)
        if not ws:
            return False
        if not hasattr(ws, field_name):
            logger.warning("工作区不存在字段: %s", field_name)
            return False
        setattr(ws, field_name, value)
        self._save_workspace(ws)
        logger.info("更新工作区字段: %s.%s", workspace_id, field_name)
        return True

    # ------------------------------------------------------------------
    # 工作区敏感变量管理（secrets.json）
    # ------------------------------------------------------------------

    def _secrets_path(self, workspace_id: str) -> Path:
        """获取工作区 secrets 文件路径"""
        return _WORKSPACES_ROOT / self._safe_id(workspace_id) / "secrets.json"

    def save_workspace_secret(self, workspace_id: str, key: str, value: str) -> bool:
        """将敏感变量写入工作区 secrets.json，设置文件权限 0o600

        Args:
            workspace_id: 工作区 ID
            key: 密钥名
            value: 密钥值

        Returns:
            是否保存成功
        """
        try:
            secrets_path = self._secrets_path(workspace_id)
            secrets_path.parent.mkdir(parents=True, exist_ok=True)

            # 读取已有 secrets
            existing = self._load_secrets(workspace_id)
            existing[key] = value

            # 写入并设置权限
            secrets_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(secrets_path, 0o600)

            logger.info("保存工作区密钥: %s/%s", workspace_id, key)
            return True
        except Exception as e:
            logger.error("保存工作区密钥失败: %s — %s", workspace_id, e)
            return False

    def get_workspace_secret(self, workspace_id: str, key: str) -> str | None:
        """读取工作区敏感变量"""
        secrets = self._load_secrets(workspace_id)
        return secrets.get(key)

    def delete_workspace_secret(self, workspace_id: str, key: str) -> bool:
        """删除工作区敏感变量"""
        try:
            secrets = self._load_secrets(workspace_id)
            if key not in secrets:
                return False
            del secrets[key]

            secrets_path = self._secrets_path(workspace_id)
            secrets_path.write_text(
                json.dumps(secrets, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(secrets_path, 0o600)

            logger.info("删除工作区密钥: %s/%s", workspace_id, key)
            return True
        except Exception as e:
            logger.error("删除工作区密钥失败: %s — %s", workspace_id, e)
            return False

    def list_workspace_secret_keys(self, workspace_id: str) -> list[str]:
        """列出工作区密钥名称（不返回值）"""
        secrets = self._load_secrets(workspace_id)
        return list(secrets.keys())

    def get_workspace_env(self, workspace_id: str) -> dict[str, str]:
        """合并工作区的 env_vars + secrets，供 Shell 沙箱使用

        注意：secrets 优先级高于 env_vars（同名时 secrets 覆盖 env_vars）
        """
        ws = self._load_workspace(workspace_id)
        if not ws:
            return {}

        merged = dict(ws.env_vars)
        secrets = self._load_secrets(workspace_id)
        merged.update(secrets)
        return merged

    def _load_secrets(self, workspace_id: str) -> dict[str, str]:
        """加载工作区 secrets"""
        secrets_path = self._secrets_path(workspace_id)
        if not secrets_path.is_file():
            return {}
        try:
            return json.loads(secrets_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("[WorkspaceService] 读取 secrets 失败: %s", e)
            return {}

    # ------------------------------------------------------------------
    # 迁移：旧格式 → 新格式
    # ------------------------------------------------------------------

    def _migrate_legacy_workspaces(self) -> None:
        """启动时自动迁移旧格式工作区

        旧格式有两种：
        1. V2 slug 目录 + .meta.json（字段不同：slug/name/path）— 保留目录名，更新字段
        2. V3-old UUID 目录 + workspace.json — 转为 slug 目录 + .meta.json

        迁移后删除旧的 UUID 目录和非目录文件（如 .md、.jsonl 散落文件）。
        """
        if not _WORKSPACES_ROOT.is_dir():
            return

        migrated = 0

        for entry in sorted(_WORKSPACES_ROOT.iterdir()):
            # 跳过非目录文件（散落的 .md / .jsonl 等）
            if not entry.is_dir():
                continue

            meta_new = entry / _META_FILENAME       # 新格式
            meta_old_v3 = entry / "workspace.json"  # V3-old 格式
            meta_old_v2 = entry / ".meta.json"      # V2 格式（文件名相同但字段不同）

            # 已经是新格式 — 跳过
            if meta_new.is_file():
                try:
                    data = json.loads(meta_new.read_text(encoding="utf-8"))
                    # 检查是否有 "id" 字段（新格式标志），且 id == 目录名
                    if data.get("id") == entry.name:
                        continue
                except Exception:
                    pass

            # 情况 1：V3-old UUID 目录 + workspace.json
            if meta_old_v3.is_file():
                try:
                    data = json.loads(meta_old_v3.read_text(encoding="utf-8"))
                    name = data.get("name", entry.name)
                    slug = self._name_to_slug(name)

                    # 检查路径是否指向元数据目录（错误路径）
                    ws_path = data.get("path", "")
                    is_bad_path = ws_path.startswith(str(_WORKSPACES_ROOT))

                    # slug 冲突且路径错误 → 这是 V2 的重复品，直接删除
                    if (_WORKSPACES_ROOT / slug).exists() and is_bad_path:
                        shutil.rmtree(entry)
                        logger.info(
                            "[迁移] 删除 V3-old 重复项: %s (name=%s, 错误路径)",
                            entry.name, name,
                        )
                        migrated += 1
                        continue

                    # 无冲突：正常迁移
                    slug = self._unique_slug(slug)

                    # 构建新的元数据
                    new_data = {
                        "id": slug,
                        "name": name,
                        "path": "" if is_bad_path else ws_path,
                        "description": data.get("description", ""),
                        "created_at": data.get("created_at", ""),
                        "last_accessed": data.get("last_accessed", ""),
                        "active": data.get("active", False),
                        "shell_enabled": data.get("shell_enabled", False),
                        "shell_level": data.get("shell_level", "L1"),
                        "network_whitelist": data.get("network_whitelist", []),
                        "env_vars": data.get("env_vars", {}),
                    }

                    if is_bad_path:
                        logger.warning(
                            "[迁移] 工作区 %s 的 path 指向元数据目录，置空: %s",
                            name, ws_path,
                        )

                    # 创建新的 slug 目录并写入 .meta.json
                    new_dir = _WORKSPACES_ROOT / slug
                    new_dir.mkdir(parents=True, exist_ok=True)
                    (new_dir / _META_FILENAME).write_text(
                        json.dumps(new_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    # 迁移 secrets.json（如有）
                    old_secrets = entry / "secrets.json"
                    if old_secrets.is_file():
                        shutil.copy2(old_secrets, new_dir / "secrets.json")

                    # 删除旧的 UUID 目录
                    shutil.rmtree(entry)

                    logger.info(
                        "[迁移] V3-old: %s → %s (name=%s)",
                        entry.name, slug, name,
                    )
                    migrated += 1
                except Exception as e:
                    logger.warning("[迁移] 处理 %s 失败: %s", entry.name, e)
                continue

            # 情况 2：V2 slug 目录 + .meta.json（字段不同）
            if meta_old_v2.is_file():
                try:
                    data = json.loads(meta_old_v2.read_text(encoding="utf-8"))
                    # V2 使用 "slug" 字段而非 "id"
                    if "slug" in data and "id" not in data:
                        new_data = {
                            "id": entry.name,  # 目录名就是 slug
                            "name": data.get("name", entry.name),
                            "path": data.get("path", ""),
                            "description": data.get("description", ""),
                            "created_at": data.get("created_at", ""),
                            "last_accessed": data.get("last_accessed", ""),
                            "active": False,
                            "shell_enabled": False,
                            "shell_level": "L1",
                            "network_whitelist": [],
                            "env_vars": {},
                        }
                        # 原地更新 .meta.json
                        meta_old_v2.write_text(
                            json.dumps(new_data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        logger.info(
                            "[迁移] V2: %s 字段已更新 (name=%s)",
                            entry.name, new_data["name"],
                        )
                        migrated += 1
                except Exception as e:
                    logger.warning("[迁移] 处理 V2 %s 失败: %s", entry.name, e)

        # 清理散落的非目录文件
        for entry in _WORKSPACES_ROOT.iterdir():
            if entry.is_file():
                logger.info("[清理] 移除散落文件: %s", entry.name)
                entry.unlink()

        if migrated:
            logger.info("[迁移] 共迁移 %d 个工作区", migrated)

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_id(workspace_id: str) -> str:
        """防止路径穿越：清理 ID 中的危险字符"""
        return workspace_id.replace("/", "_").replace("..", "_").strip(".")

    def _workspace_meta_path(self, workspace_id: str) -> Path:
        """获取工作区元数据文件路径"""
        return _WORKSPACES_ROOT / self._safe_id(workspace_id) / _META_FILENAME

    def _save_workspace(self, ws: Workspace) -> None:
        """将工作区元数据写入 .meta.json"""
        meta_path = self._workspace_meta_path(ws.id)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(ws)
        meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_workspace(self, workspace_id: str) -> Workspace | None:
        """从 .meta.json 加载工作区元数据"""
        meta_path = self._workspace_meta_path(workspace_id)
        if not meta_path.is_file():
            return None
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return Workspace(
                id=data.get("id", workspace_id),
                name=data.get("name", ""),
                path=data.get("path", ""),
                description=data.get("description", ""),
                created_at=data.get("created_at", ""),
                last_accessed=data.get("last_accessed", ""),
                active=data.get("active", False),
                shell_enabled=data.get("shell_enabled", False),
                shell_level=data.get("shell_level", "L1"),
                network_whitelist=data.get("network_whitelist", []),
                env_vars=data.get("env_vars", {}),
            )
        except Exception as e:
            logger.warning("加载工作区元数据失败 (%s): %s", workspace_id, e)
            return None

    def _build_tree(
        self,
        directory: Path,
        lines: list[str],
        prefix: str,
        depth: int,
        max_depth: int,
    ) -> None:
        """递归构建文件树（缩进格式）

        Args:
            directory: 当前目录
            lines: 结果行列表（原地追加）
            prefix: 缩进前缀
            depth: 当前深度
            max_depth: 最大深度
        """
        if depth >= max_depth:
            return

        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except PermissionError:
            lines.append(f"{prefix}[权限不足]")
            return

        # 过滤排除目录
        entries = [
            e for e in entries
            if not (e.is_dir() and e.name in _TREE_EXCLUDE_DIRS)
        ]

        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(
                    entry, lines,
                    prefix=prefix + extension,
                    depth=depth + 1,
                    max_depth=max_depth,
                )


# ------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------

_instance: WorkspaceService | None = None


def init_workspace_service() -> WorkspaceService:
    """初始化全局 WorkspaceService 单例

    首次初始化时自动迁移旧格式工作区，然后确保存在默认工作区。
    """
    global _instance
    if _instance is None:
        _instance = WorkspaceService()
        _instance._migrate_legacy_workspaces()
        _instance._ensure_default_workspace()
        logger.info("WorkspaceService 已初始化")
    return _instance


def get_workspace_service() -> WorkspaceService:
    """获取全局 WorkspaceService 单例

    Raises:
        RuntimeError: 服务尚未初始化
    """
    if _instance is None:
        # 自动初始化，方便使用
        return init_workspace_service()
    return _instance
