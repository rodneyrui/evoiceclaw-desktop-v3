"""文件系统工具 — read_file / list_directory / write_file / edit_file

安全策略（读宽写严）：
- 读取：允许任意路径，但排除系统敏感目录和用户凭据目录（黑名单模式）
- 写入：仅限 EVOICECLAW_HOME/workspaces/ + 激活工作区的项目目录（白名单模式）
- 路径必须通过 resolve() 验证，防止路径逃逸
- 禁止创建/编辑可执行文件（.sh、.bash、.exe 等）

迁移自 v2 services/skill/builtin/filesystem.py
"""

import logging
from pathlib import Path

from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.filesystem")

# ~/.evoiceclaw/ 主目录
EVOICECLAW_HOME = Path.home() / ".evoiceclaw"
_WORKSPACES_DIR = EVOICECLAW_HOME / "workspaces"
_HOME = Path.home()

# ── 读取黑名单（系统敏感目录 + 用户凭据目录）──

# 系统目录（绝对路径前缀）
_BLOCKED_SYSTEM_PREFIXES = (
    "/etc", "/private/etc",
    "/System", "/Library",
    "/usr/bin", "/usr/sbin", "/sbin", "/bin",
    "/dev", "/proc", "/sys", "/run",
    "/var/log", "/var/run",
    "/boot", "/root",
    # Windows 兼容
    "C:\\Windows", "C:\\Program Files",
)

# 用户凭据/隐私目录（相对 HOME）
_BLOCKED_HOME_DIRS = (
    ".ssh",              # SSH 密钥
    ".gnupg", ".gpg",    # GPG 密钥
    ".aws",              # AWS 凭据
    ".azure",            # Azure 凭据
    ".gcp",              # GCP 凭据
    ".config/gcloud",    # Google Cloud
    ".docker",           # Docker 凭据
    ".kube",             # Kubernetes
    ".npmrc",            # npm token
    ".pypirc",           # PyPI token
    ".netrc",            # 通用凭据
    ".password-store",   # pass 密码管理
    "Library/Keychains", # macOS 钥匙串
    ".local/share/keyrings",  # Linux 密钥环
)

# 敏感文件名（任意位置匹配）
_BLOCKED_FILENAMES = {
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",  # SSH 私钥
    ".env", ".env.local", ".env.production",          # 环境变量
    "credentials.json", "service-account.json",       # 云服务凭据
    "secrets.yaml", "secrets.yml",                    # 敏感配置
}


def _is_blocked_read_path(target: Path) -> bool:
    """检查路径是否在读取黑名单中（系统敏感或用户凭据）"""
    try:
        resolved = target.resolve()
        resolved_str = str(resolved)

        # 系统目录
        for prefix in _BLOCKED_SYSTEM_PREFIXES:
            if resolved_str.startswith(prefix):
                return True

        # 用户凭据目录
        for rel_dir in _BLOCKED_HOME_DIRS:
            blocked_path = _HOME / rel_dir
            try:
                resolved.relative_to(blocked_path.resolve())
                return True
            except ValueError:
                continue

        # 敏感文件名
        if resolved.name in _BLOCKED_FILENAMES:
            return True

        return False
    except Exception as e:
        logger.debug("[FileSystem] 读取路径黑名单检查异常: %s", e)
        return True  # 异常时保守拒绝


def _get_write_roots() -> list[Path]:
    """获取当前允许写入的根目录列表

    包含工作区元数据目录 + 激活工作区的项目路径。
    """
    roots = [_WORKSPACES_DIR]
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        active_ws = ws_svc.get_active_workspace()
        if active_ws and active_ws.path:
            roots.append(Path(active_ws.path))
    except Exception as e:
        logger.debug("[FileSystem] 获取写入根目录失败: %s", e)
    return roots


def _is_safe_write_path(target: Path, allowed_roots: list[Path]) -> bool:
    """检查目标路径是否在允许写入的根目录内（白名单模式）"""
    if not allowed_roots:
        return False
    try:
        resolved = target.resolve()
        for root in allowed_roots:
            try:
                resolved.relative_to(root.resolve())
                return True
            except ValueError:
                continue
    except Exception as e:
        logger.debug("[FileSystem] 写入路径安全检查异常: %s", e)
    return False


def _is_safe_path(target: Path, allowed_roots: list[Path]) -> bool:
    """统一路径安全检查（白名单 + 系统目录阻止）

    同时检查：
    1. 目标路径是否在允许的根目录内（白名单）
    2. 目标路径是否命中系统敏感/凭据黑名单（BLOCKED_PREFIXES）
    两者都通过才返回 True。
    """
    if _is_blocked_read_path(target):
        return False
    return _is_safe_write_path(target, allowed_roots)


class ReadFileTool(SkillProtocol):
    """读取文件内容（排除系统敏感和凭据文件）"""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "读取指定路径的文件内容。输入文件的绝对路径，返回文件内容（最多 32000 字符）。"
            "可以读取系统中的大部分文件，但无法访问系统目录（/etc、/System 等）"
            "和用户凭据目录（.ssh、.aws 等）。"
            "PDF 文件支持指定页码范围（start_page / end_page，从 1 开始计数）。"
            "使用前建议先用 list_directory 查看目录结构。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件的绝对路径",
                },
                "start_page": {
                    "type": "integer",
                    "description": "（仅 PDF）起始页码，从 1 开始。不指定则从第 1 页开始。",
                },
                "end_page": {
                    "type": "integer",
                    "description": "（仅 PDF）结束页码（含），从 1 开始。不指定则读到最后一页。",
                },
            },
            "required": ["path"],
        }

    @property
    def capability_brief(self) -> str:
        return "读取文件内容（排除系统敏感路径）"

    @property
    def required_permissions(self) -> list[str]:
        return ["read_file"]

    async def execute(self, arguments: dict) -> str:
        path = arguments.get("path", "")
        if not path:
            return "错误：请提供文件路径"

        target = Path(path).expanduser()

        if not _is_safe_path(target, [Path("/")]):
            logger.warning("文件读取被拒绝（敏感路径）: %s", path)
            return (
                f"拒绝访问：{path} 属于系统敏感或凭据路径，无法读取。\n"
                "被保护的路径包括：系统目录（/etc、/System 等）、"
                "凭据目录（.ssh、.aws 等）、敏感文件（.env、私钥等）。"
            )

        if not target.exists():
            return f"文件不存在：{path}"

        if target.is_dir():
            return f"这是一个目录，请使用 list_directory 工具查看内容：{path}"

        try:
            # PDF 文件用 pdfplumber 提取文本
            if target.suffix.lower() == ".pdf":
                try:
                    import pdfplumber
                    # 解析页码范围参数（1-indexed，容错处理）
                    raw_start = arguments.get("start_page")
                    raw_end = arguments.get("end_page")
                    try:
                        start_page = max(1, int(raw_start)) if raw_start is not None else 1
                    except (TypeError, ValueError):
                        start_page = 1
                    try:
                        end_page = max(1, int(raw_end)) if raw_end is not None else None
                    except (TypeError, ValueError):
                        end_page = None

                    with pdfplumber.open(str(target)) as pdf:
                        total_pages = len(pdf.pages)
                        # end_page 超出范围时修正
                        actual_end = min(end_page, total_pages) if end_page else total_pages
                        # 逐页累积，超出 32000 字符时停止，记录最后完整读入的页码
                        _LIMIT = 32000
                        parts: list[str] = []
                        char_count = 0
                        last_complete_page = start_page - 1  # 尚未读任何页
                        truncated = False
                        for i in range(start_page - 1, actual_end):
                            page_num = i + 1
                            text = pdf.pages[i].extract_text()
                            if not text or not text.strip():
                                last_complete_page = page_num  # 空页也算读过
                                continue
                            page_text = f"--- 第 {page_num} 页 ---\n{text.strip()}"
                            if char_count + len(page_text) > _LIMIT:
                                truncated = True
                                break
                            parts.append(page_text)
                            char_count += len(page_text)
                            last_complete_page = page_num
                        content = "\n\n".join(parts)

                    read_pages = f"第 {start_page}–{last_complete_page} 页" if last_complete_page >= start_page else "（无可提取文本）"
                    range_info = f"{read_pages}，共 {total_pages} 页"
                    if not content.strip():
                        content = (
                            f"[PDF（共 {total_pages} 页）: 所选页面无法提取文本，"
                            "可能是扫描版图片 PDF，建议使用 OCR 工具处理]"
                        )
                    elif truncated:
                        next_start = last_complete_page + 1
                        content += (
                            f"\n\n[已读取 {range_info}，内容接近上限。"
                            f"如需继续，请使用 start_page={next_start}, end_page={min(next_start + 9, total_pages)} 读取后续页面]"
                        )
                    logger.info(
                        "读取 PDF: %s (%d 字符, %s%s)",
                        path, len(content), range_info, " [已截断]" if truncated else "",
                    )
                except ImportError:
                    content = "[PDF: 未安装 pdfplumber，请执行 pip install pdfplumber]"
                except Exception as e:
                    content = f"[PDF: 读取失败: {e}]"
                return content

            content = target.read_text(encoding="utf-8", errors="replace")
            if len(content) > 32000:
                content = content[:32000] + "\n\n[... 文件过长，已截断至 32000 字符 ...]"
            logger.info("读取文件: %s (%d 字符)", path, len(content))
            return content
        except PermissionError:
            return f"权限不足，无法读取：{path}"
        except Exception as e:
            return f"读取失败：{e}"


class ListDirectoryTool(SkillProtocol):
    """列出目录内容（排除系统敏感和凭据目录）"""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return (
            "列出指定目录的文件和子目录。输入目录的绝对路径，"
            "返回该目录下的所有条目（含文件大小和类型标识）。"
            "可以访问系统中的大部分目录，但无法访问系统目录和凭据目录。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录的绝对路径",
                },
            },
            "required": ["path"],
        }

    @property
    def capability_brief(self) -> str:
        return "列出目录内容（排除系统敏感路径）"

    @property
    def required_permissions(self) -> list[str]:
        return ["read_file"]

    async def execute(self, arguments: dict) -> str:
        path = arguments.get("path", "")
        if not path:
            return "错误：请提供目录路径"

        target = Path(path).expanduser()

        if not _is_safe_path(target, [Path("/")]):
            logger.warning("目录访问被拒绝（敏感路径）: %s", path)
            return (
                f"拒绝访问：{path} 属于系统敏感或凭据路径，无法列出。\n"
                "被保护的路径包括：系统目录（/etc、/System 等）、"
                "凭据目录（.ssh、.aws 等）。"
            )

        if not target.exists():
            return f"目录不存在：{path}"

        if not target.is_dir():
            return f"这是一个文件，请使用 read_file 工具读取内容：{path}"

        try:
            items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines: list[str] = []
            for item in items:
                suffix = "/" if item.is_dir() else ""
                size_info = ""
                if item.is_file():
                    try:
                        size_info = f"  [{item.stat().st_size:,} bytes]"
                    except Exception as e:
                        logger.debug("[FileSystem] 获取文件大小失败: %s — %s", item, e)
                lines.append(f"{item.name}{suffix}{size_info}")

            header = f"目录 {path}（共 {len(lines)} 项）："
            logger.info("列目录: %s (%d 项)", path, len(lines))
            return header + "\n" + "\n".join(lines)
        except PermissionError:
            return f"权限不足，无法列出目录：{path}"
        except Exception as e:
            return f"列目录失败：{e}"


class WriteFileTool(SkillProtocol):
    """写入文件（仅限工作区目录）"""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "在当前激活工作区内创建或覆盖文件。"
            "可以写入工作区的项目目录（如 ~/Desktop/eVoiceClaw/）"
            "和工作区数据目录（~/.evoiceclaw/workspaces/）。"
            "请优先使用项目目录，用户更容易找到文件。"
            "适合记录想法、创建计划、保存分析结果。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件的绝对路径（必须在当前激活工作区的项目目录或工作区数据目录内）",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文件内容",
                },
            },
            "required": ["path", "content"],
        }

    @property
    def capability_brief(self) -> str:
        return "在工作区目录内写入文件"

    @property
    def required_permissions(self) -> list[str]:
        return ["write_file"]

    async def execute(self, arguments: dict) -> str:
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        if not path:
            return "错误：请提供文件路径"

        target = Path(path).expanduser()
        roots = _get_write_roots()

        if not _is_safe_path(target, roots):
            logger.warning("文件写入被拒绝: %s", path)
            # 动态提示当前可写目录
            writable_dirs = ", ".join(str(r) for r in roots)
            return (
                f"拒绝写入：{path} 不在工作区目录内。\n"
                f"当前可写入的目录：{writable_dirs}"
            )

        if target.suffix.lower() in (
            ".sh", ".bash", ".exe", ".bat", ".cmd", ".ps1",
            # ".py", ".js", ".ts",  # 自举实验临时放开 — 实验结束后恢复
            ".rb", ".php", ".lua",
        ):
            return f"安全限制：不允许创建脚本/可执行文件（{target.suffix}）"

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            logger.info("写入文件: %s (%d 字符)", path, len(content))
            return f"文件已写入：{path}（{len(content)} 字符）"
        except PermissionError:
            return f"权限不足，无法写入：{path}"
        except Exception as e:
            return f"写入失败：{e}"


class EditFileTool(SkillProtocol):
    """精确编辑文件（局部替换，类似 Claude Code 的 Edit 工具）

    在工作区目录内对已有文件执行 old_string → new_string 精确替换。
    支持单次替换和全量替换两种模式。
    """

    # 禁止编辑的脚本/可执行文件扩展名
    _EXECUTABLE_SUFFIXES = (
        ".sh", ".bash", ".exe", ".bat", ".cmd", ".ps1",
        # ".py", ".js", ".ts",  # 自举实验临时放开 — 实验结束后恢复
        ".rb", ".php", ".lua",
    )

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "精确编辑工作区内的文件。指定 old_string（要替换的原文）和 new_string（替换后的新文）"
            "进行局部替换。默认要求 old_string 在文件中唯一出现；如需替换所有匹配项，"
            "设置 replace_all=true。只能编辑当前激活工作区的项目目录或工作区数据目录内的文件。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件的绝对路径（必须在当前激活工作区的项目目录或工作区数据目录内）",
                },
                "old_string": {
                    "type": "string",
                    "description": "要替换的原始文本（必须与文件内容精确匹配）",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有匹配项（默认 false，仅替换唯一匹配）",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    @property
    def capability_brief(self) -> str:
        return "精确编辑工作区内的文件（局部替换）"

    @property
    def required_permissions(self) -> list[str]:
        return ["write_file"]

    async def execute(self, arguments: dict) -> str:
        path = arguments.get("path", "")
        old_string = arguments.get("old_string", "")
        new_string = arguments.get("new_string", "")
        replace_all = arguments.get("replace_all", False)

        # 参数校验
        if not path:
            return "错误：请提供文件路径"
        if not old_string:
            return "错误：请提供要替换的原始文本（old_string）"
        if old_string == new_string:
            return "错误：old_string 和 new_string 相同，无需替换"

        target = Path(path).expanduser()
        roots = _get_write_roots()

        # 安全校验：只能编辑工作区内的文件
        if not _is_safe_path(target, roots):
            logger.warning("文件编辑被拒绝: %s", path)
            writable_dirs = ", ".join(str(r) for r in roots)
            return (
                f"拒绝编辑：{path} 不在工作区目录内。\n"
                f"当前可编辑的目录：{writable_dirs}"
            )

        # 禁止编辑可执行文件
        if target.suffix in self._EXECUTABLE_SUFFIXES:
            return f"安全限制：不允许编辑可执行文件（{target.suffix}）"

        # 文件必须已存在
        if not target.exists():
            return f"文件不存在：{path}（edit_file 只能编辑已有文件，创建新文件请使用 write_file）"

        if target.is_dir():
            return f"这是一个目录，无法编辑：{path}"

        try:
            # 读取文件内容
            content = target.read_text(encoding="utf-8")
        except PermissionError:
            return f"权限不足，无法读取：{path}"
        except UnicodeDecodeError:
            return f"编码错误：文件不是有效的 UTF-8 文本文件：{path}"
        except Exception as e:
            return f"读取失败：{e}"

        # 检查 old_string 是否存在
        match_count = content.count(old_string)
        if match_count == 0:
            return (
                f"未找到匹配：old_string 在文件中不存在。\n"
                f"请确认要替换的文本与文件内容完全一致（包括空格、换行等）。\n"
                f"文件路径：{path}"
            )

        # 非全量替换模式下，要求 old_string 唯一出现
        if not replace_all and match_count > 1:
            return (
                f"找到 {match_count} 处匹配，请提供更多上下文使 old_string 唯一，"
                f"或使用 replace_all=true 替换所有匹配项。"
            )

        # 执行替换
        if replace_all:
            new_content = content.replace(old_string, new_string)
            actual_replacements = match_count
        else:
            # 单次替换（仅替换第一次出现，此时 match_count == 1）
            new_content = content.replace(old_string, new_string, 1)
            actual_replacements = 1

        # 写回文件
        try:
            target.write_text(new_content, encoding="utf-8")
            logger.info(
                "编辑文件: %s（替换 %d 处，文件 %d→%d 字符）",
                path, actual_replacements, len(content), len(new_content),
            )
            return (
                f"编辑成功：{path}\n"
                f"替换了 {actual_replacements} 处匹配"
                f"（文件大小：{len(content)} → {len(new_content)} 字符）"
            )
        except PermissionError:
            return f"权限不足，无法写入：{path}"
        except Exception as e:
            return f"写入失败：{e}"
