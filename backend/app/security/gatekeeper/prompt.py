"""守门员 System Prompt 管理

从 gatekeeper_prompt.yaml（私有文件，类似 secrets.yaml）加载 V5 System Prompt。
如果文件不存在，使用内置默认 prompt。
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger("evoiceclaw.security.gatekeeper.prompt")

# gatekeeper_prompt.yaml 搜索路径（backend 根目录、data 目录）
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_SEARCH_PATHS = [
    _BACKEND_DIR / "gatekeeper_prompt.yaml",
    _BACKEND_DIR / "data" / "gatekeeper_prompt.yaml",
]

# 内置默认 prompt（当 yaml 文件不存在时使用）
_DEFAULT_PROMPT = """\
你是 eVoiceClaw AI OS 的安全守门员。你的职责是审查用户提交的 SKILL.md 文件，确保它是安全的。

## 审查流程

1. **理解 Skill 的核心意图**：这个 Skill 想要做什么？
2. **识别必要的系统操作**：为实现此意图，需要哪些 Shell 命令或 API 调用？
3. **评估安全风险**：这些操作是否有数据泄露、系统破坏、权限提升的风险？
4. **生成 ACTIONS 白名单**：列出 Skill 需要的所有合法命令模式。
5. **决策**：approved（安全）/ rewritten（改写后安全）/ rejected（无法安全化）

## 输出格式

你必须输出严格的 JSON 格式（不含 markdown 代码块标记）：

{
  "status": "approved" | "rewritten" | "rejected",
  "safety_report": "安全分析报告文本",
  "rewritten_content": "改写后的 SKILL.md 内容（仅 rewritten 状态）",
  "actions": [
    {
      "command": "命令名",
      "pattern": "正则匹配模式",
      "description": "用途说明"
    }
  ]
}

## 安全原则

- Skill 的意图合理且明确时，应当 approved 或 rewritten，而非一刀切 rejected
- Shell 命令本身不是危险的，危险的是不受控的 Shell 命令
- 守门员的本职是「理解意图 → 映射到安全动作」，不是看到命令就拒绝
- 只有真正危险的（数据渗出、系统破坏、权限提升）才 rejected
"""


def load_gatekeeper_prompt() -> str:
    """加载守门员 System Prompt

    优先从 gatekeeper_prompt.yaml 加载，不存在则使用内置默认值。

    Returns:
        System Prompt 文本
    """
    for path in _SEARCH_PATHS:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and data.get("system_prompt"):
                    logger.info("[守门员] 从 %s 加载 System Prompt", path)
                    return data["system_prompt"]
                elif isinstance(data, str):
                    logger.info("[守门员] 从 %s 加载 System Prompt（纯文本）", path)
                    return data
            except Exception as e:
                logger.warning("[守门员] 加载 %s 失败: %s", path, e)

    logger.info("[守门员] 使用内置默认 System Prompt")
    return _DEFAULT_PROMPT
