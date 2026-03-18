"""URL 处理器单元测试

覆盖：_extract_urls, _fetch_url_content, _enhance_message_with_urls
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from app.services.url_processor import (
    _extract_urls,
    _fetch_url_content,
    _enhance_message_with_urls,
    _MAX_URL_FETCH,
    _MAX_FETCH_CONTENT,
)


# ── _extract_urls ────────────────────────────────────────────

class TestExtractUrls:
    def test_无URL返回空列表(self):
        assert _extract_urls("这是一段没有链接的文字") == []

    def test_单个http链接(self):
        assert _extract_urls("访问 http://example.com 了解详情") == ["http://example.com"]

    def test_单个https链接(self):
        assert _extract_urls("参考 https://example.com/page") == ["https://example.com/page"]

    def test_多个链接(self):
        result = _extract_urls("见 https://a.com 和 https://b.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_去重_相同URL只保留一个(self):
        result = _extract_urls("https://a.com 和 https://a.com")
        assert result == ["https://a.com"]
        assert len(result) == 1

    def test_上限截断_超过MAX_URL_FETCH个只取前N个(self):
        urls = " ".join(f"https://site{i}.com" for i in range(_MAX_URL_FETCH + 2))
        result = _extract_urls(urls)
        assert len(result) == _MAX_URL_FETCH

    def test_尾部中文句号被去除(self):
        result = _extract_urls("链接是 https://example.com。")
        assert result == ["https://example.com"]

    def test_尾部英文句号被去除(self):
        result = _extract_urls("见 https://example.com.")
        assert result == ["https://example.com"]

    def test_尾部逗号被去除(self):
        # 逗号必须在末尾才会被 rstrip 处理
        result = _extract_urls("访问 https://example.com，")
        assert result == ["https://example.com"]

    def test_尾部问号被去除(self):
        result = _extract_urls("这对吗 https://example.com?")
        assert result == ["https://example.com"]

    def test_尾部中文括号被去除(self):
        result = _extract_urls("（https://example.com）")
        assert result == ["https://example.com"]

    def test_带路径和查询参数的链接(self):
        url = "https://example.com/path/to/page?key=value&foo=bar"
        result = _extract_urls(f"查看 {url}")
        assert result == [url]

    def test_带锚点的链接(self):
        url = "https://docs.example.com/guide#section-1"
        result = _extract_urls(f"见 {url}")
        assert result == [url]

    def test_非http协议不匹配(self):
        assert _extract_urls("ftp://example.com 不应被提取") == []

    def test_空字符串(self):
        assert _extract_urls("") == []

    def test_保留顺序_先出现的先返回(self):
        result = _extract_urls("https://first.com 然后 https://second.com")
        assert result[0] == "https://first.com"
        assert result[1] == "https://second.com"


# ── _fetch_url_content ───────────────────────────────────────

class TestFetchUrlContent:
    """WebFetchTool 在函数内部懒加载，patch 目标为源模块 app.kernel.tools.builtin.web_fetch"""

    @pytest.mark.asyncio
    async def test_成功抓取返回内容(self):
        with patch("app.kernel.tools.builtin.web_fetch.WebFetchTool") as mock_cls:
            mock_cls.return_value.execute = AsyncMock(return_value="网页内容")
            result = await _fetch_url_content("https://example.com")
        assert result == "网页内容"

    @pytest.mark.asyncio
    async def test_返回错误前缀时返回None(self):
        with patch("app.kernel.tools.builtin.web_fetch.WebFetchTool") as mock_cls:
            mock_cls.return_value.execute = AsyncMock(return_value="错误：连接失败")
            result = await _fetch_url_content("https://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_超时返回None(self):
        with patch("app.services.url_processor.asyncio.wait_for",
                   side_effect=asyncio.TimeoutError):
            result = await _fetch_url_content("https://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_抓取异常返回None(self):
        with patch("app.kernel.tools.builtin.web_fetch.WebFetchTool") as mock_cls:
            mock_cls.return_value.execute = AsyncMock(side_effect=ConnectionError("网络错误"))
            result = await _fetch_url_content("https://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_超长内容被截断(self):
        long_content = "a" * (_MAX_FETCH_CONTENT + 1000)
        with patch("app.kernel.tools.builtin.web_fetch.WebFetchTool") as mock_cls:
            mock_cls.return_value.execute = AsyncMock(return_value=long_content)
            result = await _fetch_url_content("https://example.com")
        assert result is not None
        assert len(result) <= _MAX_FETCH_CONTENT + len("\n...(内容已截断)")
        assert result.endswith("...(内容已截断)")

    @pytest.mark.asyncio
    async def test_正好等于上限内容不被截断(self):
        content = "x" * _MAX_FETCH_CONTENT
        with patch("app.kernel.tools.builtin.web_fetch.WebFetchTool") as mock_cls:
            mock_cls.return_value.execute = AsyncMock(return_value=content)
            result = await _fetch_url_content("https://example.com")
        assert result == content
        assert not result.endswith("...(内容已截断)")


# ── _enhance_message_with_urls ───────────────────────────────

class TestEnhanceMessageWithUrls:
    @pytest.mark.asyncio
    async def test_无URL消息原样返回(self):
        msg = "普通消息，没有链接"
        enhanced, urls = await _enhance_message_with_urls(msg)
        assert enhanced == msg
        assert urls == []

    @pytest.mark.asyncio
    async def test_有URL时返回检测到的URL列表(self):
        with patch("app.services.url_processor._fetch_url_content",
                   AsyncMock(return_value="页面内容")):
            _, urls = await _enhance_message_with_urls("看 https://example.com 这个")
        assert urls == ["https://example.com"]

    @pytest.mark.asyncio
    async def test_成功抓取时内容拼接到消息后(self):
        with patch("app.services.url_processor._fetch_url_content",
                   AsyncMock(return_value="这是网页正文")):
            enhanced, _ = await _enhance_message_with_urls("看 https://example.com")
        assert "这是网页正文" in enhanced
        assert "以下是链接内容" in enhanced

    @pytest.mark.asyncio
    async def test_抓取失败时显示失败提示(self):
        with patch("app.services.url_processor._fetch_url_content",
                   AsyncMock(return_value=None)):
            enhanced, _ = await _enhance_message_with_urls("看 https://example.com")
        assert "抓取失败或内容为空" in enhanced

    @pytest.mark.asyncio
    async def test_抓取异常时显示异常类型(self):
        async def raise_exc(url):
            raise RuntimeError("测试异常")

        with patch("app.services.url_processor._fetch_url_content", raise_exc):
            enhanced, _ = await _enhance_message_with_urls("看 https://example.com")
        assert "抓取失败" in enhanced

    @pytest.mark.asyncio
    async def test_多URL并发抓取都拼接(self):
        with patch("app.services.url_processor._fetch_url_content",
                   AsyncMock(return_value="内容")):
            enhanced, urls = await _enhance_message_with_urls(
                "看 https://a.com 和 https://b.com"
            )
        assert len(urls) == 2
        assert enhanced.count("---") >= 4  # 每个 URL 两条分隔线

    @pytest.mark.asyncio
    async def test_原始消息内容保留在增强消息开头(self):
        original = "请分析 https://example.com 的内容"
        with patch("app.services.url_processor._fetch_url_content",
                   AsyncMock(return_value="网页正文")):
            enhanced, _ = await _enhance_message_with_urls(original)
        assert enhanced.startswith(original)
