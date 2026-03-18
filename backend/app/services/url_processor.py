"""URL 检测与自动抓取：从用户消息中提取 URL 并抓取内容，增强 LLM 上下文"""

import asyncio
import logging
import re

logger = logging.getLogger("evoiceclaw.chat")

_URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')
_MAX_URL_FETCH = 3        # 最多处理 3 个 URL
_MAX_FETCH_CONTENT = 30 * 1024  # 单个 URL 抓取内容上限 30KB


def _extract_urls(message: str) -> list[str]:
    """从消息中提取 URL 列表（去重，最多 _MAX_URL_FETCH 个）"""
    urls = _URL_REGEX.findall(message)
    # 去除尾部标点
    cleaned = []
    seen = set()
    for url in urls:
        url = url.rstrip(".,;:!?。，；：！？）)」】》")
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned[:_MAX_URL_FETCH]


async def _fetch_url_content(url: str) -> str | None:
    """使用 WebFetchTool 抓取 URL 内容，失败返回 None"""
    try:
        from app.kernel.tools.builtin.web_fetch import WebFetchTool
        tool = WebFetchTool()
        result = await asyncio.wait_for(
            tool.execute({"url": url, "include_links": False}),
            timeout=15,
        )
        if result.startswith("错误："):
            logger.warning("[URL预处理] 抓取失败: %s → %s", url, result[:100])
            return None
        # 截取内容上限
        if len(result) > _MAX_FETCH_CONTENT:
            result = result[:_MAX_FETCH_CONTENT] + "\n...(内容已截断)"
        return result
    except asyncio.TimeoutError:
        logger.warning("[URL预处理] 抓取超时: %s", url)
        return None
    except Exception as e:
        logger.warning("[URL预处理] 抓取异常: %s → %s", url, e)
        return None


async def _enhance_message_with_urls(message: str) -> tuple[str, list[str]]:
    """检测消息中的 URL 并抓取内容，返回 (增强后的消息, 检测到的URL列表)

    如果消息中包含 URL，自动抓取内容并拼接到消息后面，
    让 LLM 能直接分析网页内容而非只看到裸 URL。
    """
    urls = _extract_urls(message)
    if not urls:
        return message, []

    logger.info("[URL预处理] 检测到 %d 个 URL: %s", len(urls), urls)

    # 并发抓取所有 URL
    tasks = [_fetch_url_content(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 拼接抓取结果
    fetched_parts: list[str] = []
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            fetched_parts.append(f"\n--- {url} ---\n（抓取失败：{type(result).__name__}）")
        elif result:
            fetched_parts.append(f"\n--- {url} ---\n{result}")
        else:
            fetched_parts.append(f"\n--- {url} ---\n（抓取失败或内容为空）")

    enhanced = message + "\n\n--- 以下是链接内容（由系统自动抓取） ---" + "".join(fetched_parts)
    logger.info("[URL预处理] 消息已增强，新增 %d 字符", len(enhanced) - len(message))
    return enhanced, urls
