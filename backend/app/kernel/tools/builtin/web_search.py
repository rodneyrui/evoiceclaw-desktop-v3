"""WebSearchTool — 搜索引擎查询工具

优先使用博查 (Bocha) Web Search API（国内搜索质量最佳，需 API Key）。
API Key 未配置时降级到 DuckDuckGo（免费，无需 Key）。

博查 API 文档：https://open.bochaai.com/

迁移自 v2 services/skill/builtin/web_search.py
"""

import logging

import httpx

from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.web_search")

_BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"
_BOCHA_TIMEOUT = 15


class WebSearchTool(SkillProtocol):
    """搜索互联网"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "搜索互联网获取最新信息。"
            "用于回答需要实时数据的问题（新闻、天气、产品价格、技术文档等）。"
            "返回搜索结果的标题、链接和摘要。"
            "如需获取某条结果的完整网页内容，请接着使用 web_fetch 工具。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数（默认 5，最大 10）",
                },
                "freshness": {
                    "type": "string",
                    "enum": ["oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"],
                    "description": "时间范围过滤（默认 noLimit）",
                },
            },
            "required": ["query"],
        }

    @property
    def capability_brief(self) -> str:
        return "搜索互联网获取最新信息（新闻、文档、价格等）"

    @property
    def required_permissions(self) -> list[str]:
        return ["network"]

    async def execute(self, arguments: dict) -> str:
        query = arguments.get("query", "")
        if not query:
            return "错误：请提供搜索关键词"

        max_results = min(arguments.get("max_results", 5), 10)
        freshness = arguments.get("freshness", "noLimit")

        # 尝试获取博查 API Key
        bocha_key = self._get_bocha_api_key()
        if bocha_key:
            result = await self._search_bocha(query, max_results, freshness, bocha_key)
            if result:
                return result
            logger.warning("[WebSearch] 博查搜索失败，降级到 DuckDuckGo")

        return self._search_duckduckgo(query, max_results)

    # ── 博查 API 搜索 ──

    async def _search_bocha(
        self, query: str, count: int, freshness: str, api_key: str,
    ) -> str | None:
        """使用博查 Web Search API 搜索"""
        logger.info("[WebSearch] 博查搜索: %s (count=%d)", query, count)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_BOCHA_TIMEOUT)) as client:
                resp = await client.post(
                    _BOCHA_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "count": count,
                        "freshness": freshness,
                        "summary": True,
                    },
                )

            if resp.status_code != 200:
                logger.warning("[WebSearch] 博查 API 返回 %d: %s", resp.status_code, resp.text[:200])
                return None

            data = resp.json()
            web_pages = data.get("data", data).get("webPages", {})
            results = web_pages.get("value", [])

            if not results:
                return f"未找到关于「{query}」的搜索结果"

            lines = [f"搜索「{query}」的结果（共 {len(results)} 条，来源：博查）：\n"]
            for i, r in enumerate(results, 1):
                title = r.get("name", "无标题")
                url = r.get("url", "")
                summary = r.get("summary", "") or r.get("snippet", "")
                site = r.get("siteName", "")
                date = r.get("datePublished", "")

                lines.append(f"{i}. **{title}**")
                if site:
                    lines.append(f"   来源：{site}")
                lines.append(f"   链接：{url}")
                if summary:
                    lines.append(f"   摘要：{summary}")
                if date:
                    lines.append(f"   发布：{date}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            logger.warning("[WebSearch] 博查搜索异常: %s", e)
            return None

    # ── DuckDuckGo 降级搜索 ──

    def _search_duckduckgo(self, query: str, max_results: int) -> str:
        """降级方案：使用 DuckDuckGo 搜索（免费，无需 API Key）"""
        logger.info("[WebSearch] DuckDuckGo 搜索: %s (max=%d)", query, max_results)

        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "错误：搜索服务不可用（博查未配置 API Key，DuckDuckGo 未安装）"

        try:
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            logger.warning("[WebSearch] DuckDuckGo 搜索失败: %s", e)
            return f"搜索失败：{type(e).__name__}: {e}"

        if not results:
            return f"未找到关于「{query}」的搜索结果"

        lines = [f"搜索「{query}」的结果（共 {len(results)} 条）：\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            href = r.get("href", "")
            body = r.get("body", "")
            lines.append(f"{i}. **{title}**")
            lines.append(f"   链接：{href}")
            if body:
                lines.append(f"   摘要：{body}")
            lines.append("")

        return "\n".join(lines)

    # ── API Key 读取 ──

    @staticmethod
    def _get_bocha_api_key() -> str | None:
        """从 secrets.yaml 读取博查 API Key"""
        try:
            from app.core.config import load_secrets
            secrets = load_secrets()
            key = secrets.get("services", {}).get("bocha", {}).get("api_key", "")
            return key if key and key != "***" else None
        except Exception as e:
            logger.debug("[WebSearch] 读取博查 API Key 失败: %s", e)
            return None
