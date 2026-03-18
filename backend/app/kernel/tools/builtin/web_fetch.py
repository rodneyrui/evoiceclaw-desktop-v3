"""WebFetchTool — 网页内容提取工具

获取网页 URL 的内容，自动提取正文并转为易读文本。
使用 trafilatura 进行智能内容提取（类似浏览器阅读模式）。
提取失败时降级为基础 HTML 标签剥离。

迁移自 v2 services/skill/builtin/web_fetch.py
"""

import logging
import re
from urllib.parse import urlparse

import httpx

from app.kernel.tools.protocol import SkillProtocol
from app.kernel.tools.builtin.network import _is_private_host

logger = logging.getLogger("evoiceclaw.tool.web_fetch")

_TIMEOUT = 30
_MAX_CONTENT_LENGTH = 50 * 1024  # 50KB
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class WebFetchTool(SkillProtocol):
    """获取并提取网页内容"""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "获取指定 URL 的网页内容，自动提取正文（去除导航栏、广告、页脚等干扰）。"
            "适用于阅读文章、查看文档、获取产品详情等场景。"
            "返回提取后的纯文本。如需原始 HTML，请用 http_request。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要获取的网页 URL（http:// 或 https://）",
                },
                "include_links": {
                    "type": "boolean",
                    "description": "是否保留链接（默认 true）",
                },
            },
            "required": ["url"],
        }

    @property
    def capability_brief(self) -> str:
        return "获取网页内容并提取正文（自动去除广告和导航）"

    @property
    def required_permissions(self) -> list[str]:
        return ["network"]

    async def execute(self, arguments: dict) -> str:
        url = arguments.get("url", "")
        if not url:
            return "错误：请提供 URL"

        include_links = arguments.get("include_links", True)

        # URL 校验
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"错误：仅支持 http/https，收到 {parsed.scheme}"
        hostname = parsed.hostname
        if not hostname:
            return "错误：无法解析主机名"
        # NetworkGuard 域名白名单检查（宪法第8条）
        from app.security.network_guard import check_url
        ws_id = (arguments.get("_context") or {}).get("workspace_id", "global")
        ng_allowed, ng_reason = check_url(url, workspace_id=ws_id)
        if not ng_allowed:
            logger.warning("[WebFetch] NetworkGuard 拦截: %s — %s", url, ng_reason)
            return f"请求被拒绝: {ng_reason}"

        if _is_private_host(hostname):
            return f"错误：禁止访问内网地址 ({hostname})"

        logger.info("[WebFetch] 获取: %s", url)

        # 获取 HTML
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(_TIMEOUT),
                follow_redirects=True,
                max_redirects=5,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/markdown, text/html;q=0.9, */*;q=0.8",
                },
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException:
            return f"错误：请求超时（{_TIMEOUT}s）"
        except httpx.TooManyRedirects:
            return "错误：重定向次数过多"
        except httpx.ConnectError as e:
            return f"错误：连接失败 — {e}"
        except Exception as e:
            return f"错误：{type(e).__name__}: {e}"

        if response.status_code >= 400:
            return f"错误：HTTP {response.status_code}"

        content_type = response.headers.get("content-type", "")
        html = response.text

        # R9: Cloudflare Markdown for Agents — CF 站点直接返回 Markdown，跳过 trafilatura
        if "text/markdown" in content_type:
            logger.info("[WebFetch] CF Markdown 直通: %s", url)
            text = html[:_MAX_CONTENT_LENGTH]
            if len(html) > _MAX_CONTENT_LENGTH:
                text += "\n...(内容已截断)"
            return f"URL: {url}\n\n{text}"

        # 非 HTML 内容直接返回
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            text = html[:_MAX_CONTENT_LENGTH]
            if len(html) > _MAX_CONTENT_LENGTH:
                text += "\n...(内容已截断)"
            return f"URL: {url}\nContent-Type: {content_type}\n\n{text}"

        # trafilatura 智能提取
        extracted = self._extract_with_trafilatura(html, url, include_links)
        if extracted:
            if len(extracted) > _MAX_CONTENT_LENGTH:
                extracted = extracted[:_MAX_CONTENT_LENGTH] + "\n...(内容已截断)"
            return f"URL: {url}\n\n{extracted}"

        # 降级：基础 HTML 标签剥离
        fallback = self._fallback_extract(html)
        if len(fallback) > _MAX_CONTENT_LENGTH:
            fallback = fallback[:_MAX_CONTENT_LENGTH] + "\n...(内容已截断)"
        return f"URL: {url}\n（智能提取失败，以下为基础提取）\n\n{fallback}"

    def _extract_with_trafilatura(
        self, html: str, url: str, include_links: bool
    ) -> str | None:
        try:
            import trafilatura
            return trafilatura.extract(
                html,
                url=url,
                include_links=include_links,
                include_tables=True,
                favor_recall=True,
                output_format="txt",
            )
        except ImportError:
            logger.warning("[WebFetch] trafilatura 未安装，降级提取")
            return None
        except Exception as e:
            logger.warning("[WebFetch] trafilatura 失败: %s", e)
            return None

    def _fallback_extract(self, html: str) -> str:
        text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
        text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
