"""隐私恢复器（Privacy Restorer）

职责: 将 LLM 回复中的 UUID 占位符恢复为原始数据。

输入: LLM 回复文本 + redaction_map
输出: 恢复后的完整文本
"""

import logging
import re

from app.domain.models import RedactionEntry

logger = logging.getLogger("evoiceclaw.pipeline.restorer")

# 占位符匹配模式
_PLACEHOLDER_PATTERN = re.compile(r"__REDACTED_[a-f0-9]{12}__")


class PrivacyRestorer:
    """将 UUID 占位符恢复为原始敏感数据。"""

    def restore(
        self,
        text: str,
        redaction_map: dict[str, RedactionEntry],
    ) -> str:
        """恢复文本中的所有 UUID 占位符。

        Args:
            text: 含占位符的 LLM 回复
            redaction_map: 占位符 → 原始数据的映射

        Returns:
            恢复后的文本
        """
        if not redaction_map or not text:
            return text

        restored = text
        restore_count = 0

        for placeholder, entry in redaction_map.items():
            if placeholder in restored:
                restored = restored.replace(placeholder, entry.original)
                restore_count += 1

        if restore_count > 0:
            logger.info("[恢复器] 恢复了 %d 个占位符", restore_count)

        # 检查是否还有未恢复的占位符（不在 map 中的）
        remaining = _PLACEHOLDER_PATTERN.findall(restored)
        if remaining:
            logger.warning(
                "[恢复器] 有 %d 个占位符未能恢复: %s",
                len(remaining), remaining[:3],
            )

        return restored

    def check_consistency(
        self,
        text: str,
        redaction_map: dict[str, RedactionEntry],
    ) -> list[str]:
        """检查恢复后文本的上下文一致性（基础版本）。

        Returns:
            不一致问题列表（空列表表示一致）
        """
        issues: list[str] = []

        # 检查是否有残留占位符
        remaining = _PLACEHOLDER_PATTERN.findall(text)
        if remaining:
            issues.append(f"残留 {len(remaining)} 个未恢复的占位符")

        return issues
