"""HttpRequestTool — 让 LLM 发起 HTTP 请求

安全措施：
- 请求超时 30s
- 响应体截断 50KB
- 禁止访问内网地址（127.x / 10.x / 192.168.x / 172.16-31.x / localhost）
- 过滤危险 Header（cookie / authorization）

迁移自 v2 services/skill/builtin/http_request.py
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.network")

_TIMEOUT = 30  # 秒
_MAX_RESPONSE_SIZE = 50 * 1024  # 50KB
_BLOCKED_HEADERS = {"cookie", "authorization"}  # 不自动转发的危险 header


def _is_private_host(hostname: str) -> bool:
    """检查是否为内网地址（SSRF 防护）

    被 web_fetch 等工具复用，因此作为模块级函数暴露。
    """
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
        for _, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        pass
    return False


class HttpRequestTool(SkillProtocol):
    """发起 HTTP 请求（GET/POST/PUT/DELETE）"""

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "发起 HTTP 请求到外部 API。"
            "支持 GET/POST/PUT/DELETE 方法，可设置请求头和 JSON Body。"
            "用于调用已安装 Skill 所需的外部服务 API（如 Gamma、Notion 等）。"
            "禁止访问内网地址。响应体最大 50KB。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP 方法",
                },
                "url": {
                    "type": "string",
                    "description": "完整的 URL（必须是 https:// 或 http://）",
                },
                "headers": {
                    "type": "object",
                    "description": "请求头（键值对），如 {\"X-API-KEY\": \"xxx\"}",
                    "additionalProperties": {"type": "string"},
                },
                "json_body": {
                    "type": "object",
                    "description": "JSON 请求体（仅 POST/PUT 时使用）",
                },
            },
            "required": ["method", "url"],
        }

    @property
    def capability_brief(self) -> str:
        return "发起 HTTP 请求到外部 API（支持 GET/POST/PUT/DELETE）"

    @property
    def required_permissions(self) -> list[str]:
        return ["network"]

    async def execute(self, arguments: dict) -> str:
        method = arguments.get("method", "GET").upper()
        url = arguments.get("url", "")
        headers = arguments.get("headers") or {}
        json_body = arguments.get("json_body")

        if not url:
            return "错误：缺少 url 参数"
        if method not in ("GET", "POST", "PUT", "DELETE"):
            return f"错误：不支持的 HTTP 方法 {method}"

        # URL 解析与安全检查
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"错误：仅支持 http/https 协议，收到 {parsed.scheme}"

        hostname = parsed.hostname
        if not hostname:
            return "错误：无法从 URL 解析主机名"

        # NetworkGuard 域名白名单检查（宪法第8条）
        from app.security.network_guard import check_url
        ws_id = (arguments.get("_context") or {}).get("workspace_id", "global")
        ng_allowed, ng_reason = check_url(url, workspace_id=ws_id)
        if not ng_allowed:
            logger.warning("[HttpRequest] NetworkGuard 拦截: %s — %s", url, ng_reason)
            return f"请求被拒绝: {ng_reason}"

        if _is_private_host(hostname):
            return f"错误：禁止访问内网地址 ({hostname})"

        # 过滤危险 header
        safe_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in _BLOCKED_HEADERS
        }

        logger.info("[HttpRequest] %s %s", method, url)

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(_TIMEOUT),
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                kwargs: dict = {"headers": safe_headers}
                if method in ("POST", "PUT") and json_body is not None:
                    kwargs["json"] = json_body

                response = await client.request(method, url, **kwargs)

            # 截断响应体
            body = response.text
            truncated = False
            if len(body) > _MAX_RESPONSE_SIZE:
                body = body[:_MAX_RESPONSE_SIZE]
                truncated = True

            # 构造结果
            parts = [f"HTTP {response.status_code}"]

            content_type = response.headers.get("content-type", "")
            if content_type:
                parts.append(f"Content-Type: {content_type}")

            parts.append("")  # 空行分隔
            parts.append(body)

            if truncated:
                parts.append(f"\n[响应已截断，原始大小超过 {_MAX_RESPONSE_SIZE // 1024}KB]")

            return "\n".join(parts)

        except httpx.TimeoutException:
            return f"错误：请求超时（{_TIMEOUT}s）"
        except httpx.TooManyRedirects:
            return "错误：重定向次数过多（超过 5 次）"
        except httpx.ConnectError as e:
            return f"错误：连接失败 — {e}"
        except Exception as e:
            logger.exception("[HttpRequest] 请求异常")
            return f"错误：请求失败 — {type(e).__name__}: {e}"
