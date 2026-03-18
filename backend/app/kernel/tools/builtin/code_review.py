"""代码审核工具 — 调用 LLM 对代码文件或目录进行专业审核

让 LLM 能够审核代码文件，读取源码后调用 LLM 分析并输出审核意见。
支持单文件审核和目录批量审核，可指定审核关注点（安全性、性能、代码质量、架构等）。

安全策略：
- 复用 filesystem 的读取黑名单校验（_is_blocked_read_path）
- 排除系统敏感目录和凭据文件，其余均可审核
- 对代码内容长度做截断保护
"""

import logging
from pathlib import Path

from app.core.config import load_config
from app.domain.models import ChatMessage, MessageRole
from app.kernel.router.llm_router import collect_stream_text, get_router
from app.kernel.tools.builtin.filesystem import _is_blocked_read_path
from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.code_review")

# 支持审核的代码文件扩展名
_CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml",
}

# 递归扫描时跳过的目录名
_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".nuxt", "egg-info",
}

# 单文件最大读取字符数
_SINGLE_FILE_MAX_CHARS = 15000
# 目录模式下单文件最大字符数
_DIR_FILE_MAX_CHARS = 5000
# 目录模式下所有文件总字符数上限
_DIR_TOTAL_MAX_CHARS = 30000


class CodeReviewTool(SkillProtocol):
    """代码审核工具：读取源码并调用 LLM 进行专业审核"""

    @property
    def name(self) -> str:
        return "code_review"

    @property
    def description(self) -> str:
        return (
            "对代码文件或目录进行专业审核。输入文件或目录的绝对路径，"
            "可选指定审核关注点（如安全性、性能、代码质量、架构），"
            "将调用 LLM 分析代码并输出审核报告，包括代码质量、安全性、性能和改进建议。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件或目录的绝对路径",
                },
                "focus": {
                    "type": "string",
                    "description": (
                        "审核关注点（可选），如 '安全性'、'性能'、'代码质量'、'架构'。"
                        "不指定则进行全面审核"
                    ),
                },
                "language": {
                    "type": "string",
                    "description": (
                        "代码语言提示（可选），如 'python'、'typescript'。"
                        "不指定则自动检测"
                    ),
                },
            },
            "required": ["path"],
        }

    @property
    def capability_brief(self) -> str:
        return "审核代码文件，分析质量、安全性和性能"

    @property
    def required_permissions(self) -> list[str]:
        return ["read_file"]

    @property
    def tool_timeout(self) -> int:
        # LLM 审核需要较长时间
        return 60

    async def execute(self, arguments: dict) -> str:
        path_str = arguments.get("path", "")
        focus = arguments.get("focus", "")
        language = arguments.get("language", "")

        if not path_str:
            return "错误：请提供文件或目录路径"

        target = Path(path_str).expanduser()

        # 路径安全校验（黑名单模式）
        if _is_blocked_read_path(target):
            logger.warning("代码审核路径被拒绝（敏感路径）: %s", path_str)
            return (
                f"拒绝访问：{path_str} 属于系统敏感或凭据路径，无法审核。"
            )

        if not target.exists():
            return f"路径不存在：{path_str}"

        # 根据路径类型收集代码内容
        if target.is_file():
            code_content = _read_single_file(target, _SINGLE_FILE_MAX_CHARS)
        elif target.is_dir():
            code_content = _read_directory(target)
        else:
            return f"不支持的路径类型：{path_str}"

        if not code_content:
            return f"未找到可审核的代码内容：{path_str}"

        # 构建审核 prompt
        review_prompt = _build_review_prompt(code_content, focus, language)

        # 调用 LLM 进行审核
        try:
            config = load_config()
            model_id = config.get("llm", {}).get(
                "default_model", "deepseek/deepseek-chat"
            )

            messages = [
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "你是一个专业的代码审核员。"
                        "请仔细分析提供的代码，给出专业、具体、可操作的审核意见。"
                        "始终使用中文回复。"
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=review_prompt,
                ),
            ]

            router = get_router()
            review_text = await collect_stream_text(
                router, messages, model_id, config
            )

            if not review_text:
                return "LLM 审核未返回有效内容，请稍后重试。"

            logger.info(
                "代码审核完成: path=%s, model=%s, 结果长度=%d",
                path_str, model_id, len(review_text),
            )
            # 宪法第25条：AI 审核意见添加标记
            marked_result = f"## 代码审核报告\n\n**审核路径**: {path_str}\n**使用模型**: {model_id}\n\n{review_text}\n\n---\n🤖 AI Code Reviewer (eVoiceClaw Desktop)"

            # 审核结果记录审计日志
            try:
                from app.security.audit import log_event
                log_event(
                    component="code_review",
                    action="REVIEW_COMPLETED",
                    detail=f"path={path_str} model={model_id} result_len={len(review_text)}",
                )
            except Exception as e:
                logger.warning("[CodeReview] 审计日志记录失败: %s", e)

            return marked_result

        except RuntimeError as e:
            # LLMRouter 未初始化等运行时错误
            logger.error("代码审核失败（运行时错误）: %s", e)
            return f"代码审核失败：{e}"
        except Exception as e:
            logger.error("代码审核失败: %s", e, exc_info=True)
            return f"代码审核过程中出错：{e}"


def _read_single_file(file_path: Path, max_chars: int) -> str:
    """读取单个文件内容，超长时截断"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = True

        result = f"### 文件: {file_path.name}\n```\n{content}\n```"
        if truncated:
            result += f"\n\n[... 文件内容过长，已截断至 {max_chars} 字符 ...]"
        return result
    except PermissionError:
        return f"### 文件: {file_path.name}\n[权限不足，无法读取]"
    except Exception as e:
        return f"### 文件: {file_path.name}\n[读取失败: {e}]"


def _read_directory(dir_path: Path) -> str:
    """递归读取目录中的代码文件，拼接为审核内容

    每个文件最多 _DIR_FILE_MAX_CHARS 字符，
    所有文件合计最多 _DIR_TOTAL_MAX_CHARS 字符。
    """
    collected_parts: list[str] = []
    total_chars = 0
    file_count = 0
    skipped_count = 0

    for file_path in sorted(dir_path.rglob("*")):
        # 跳过敏感路径（黑名单模式二次防护）
        if _is_blocked_read_path(file_path):
            continue

        # 跳过需要忽略的目录下的文件
        if any(skip_dir in file_path.parts for skip_dir in _SKIP_DIRS):
            continue

        # 只处理代码文件
        if not file_path.is_file():
            continue
        if file_path.suffix not in _CODE_EXTENSIONS:
            continue

        # 总字符数上限检查
        if total_chars >= _DIR_TOTAL_MAX_CHARS:
            skipped_count += 1
            continue

        # 计算本文件的可用字符配额
        remaining = _DIR_TOTAL_MAX_CHARS - total_chars
        file_max = min(_DIR_FILE_MAX_CHARS, remaining)

        part = _read_single_file(file_path, file_max)
        part_len = len(part)
        collected_parts.append(part)
        total_chars += part_len
        file_count += 1

    if not collected_parts:
        return ""

    header = f"目录: {dir_path}（共扫描 {file_count} 个代码文件"
    if skipped_count > 0:
        header += f"，另有 {skipped_count} 个文件因总长度限制被跳过"
    header += "）\n\n"

    return header + "\n\n".join(collected_parts)


def _build_review_prompt(code_content: str, focus: str, language: str) -> str:
    """构建发送给 LLM 的审核 prompt"""
    parts: list[str] = ["请对以下代码进行审核。\n"]

    if focus:
        parts.append(f"重点关注: {focus}\n")

    if language:
        parts.append(f"代码语言: {language}\n")

    parts.append(
        "请从以下维度分析:\n"
        "1. 代码质量: 可读性、命名、结构\n"
        "2. 安全性: 注入风险、路径逃逸、敏感数据处理\n"
        "3. 性能: 明显的性能问题\n"
        "4. 建议: 具体的改进建议\n"
    )

    parts.append(f"\n代码内容:\n---\n{code_content}\n---\n")
    parts.append("请用中文输出审核报告。")

    return "\n".join(parts)
