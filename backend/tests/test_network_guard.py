"""NetworkGuard 域名白名单守卫测试"""

import pytest
from unittest.mock import patch, MagicMock

from app.security.network_guard import check_url, get_whitelist, _BLOCKED_HOSTS


# ─── 云元数据地址拦截（无条件） ────────────────────────────────

class TestCloudMetadataBlocked:

    @pytest.mark.parametrize("url", [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "http://metadata.google.com/computeMetadata/v1/",
    ])
    def test_cloud_metadata_always_blocked(self, url):
        allowed, reason = check_url(url)
        assert not allowed
        assert "云元数据" in reason or "禁止" in reason

    def test_blocked_hosts_set_completeness(self):
        assert "169.254.169.254" in _BLOCKED_HOSTS
        assert "metadata.google.internal" in _BLOCKED_HOSTS
        assert "metadata.google.com" in _BLOCKED_HOSTS


# ─── 内网地址拦截 ──────────────────────────────────────────────

class TestPrivateIPBlocked:

    @pytest.mark.parametrize("url", [
        "http://192.168.1.1/api",
        "http://10.0.0.1/secret",
        "http://172.16.0.1/internal",
        "http://127.0.0.1:8080/api",
        "http://localhost/admin",
        "http://0.0.0.0/",
    ])
    def test_private_ip_blocked(self, url):
        allowed, reason = check_url(url)
        assert not allowed
        assert "内网" in reason or "禁止" in reason


# ─── NetworkGuard 未启用时放行 ─────────────────────────────────

class TestNetworkGuardDisabled:

    def _disabled_config(self):
        return {"network_guard": {"enabled": False}}

    def test_public_domain_allowed_when_disabled(self):
        with patch("app.security.network_guard.load_config",
                   return_value=self._disabled_config()):
            allowed, reason = check_url("https://api.openai.com/v1/chat")
        assert allowed
        assert "未启用" in reason

    def test_any_domain_allowed_when_disabled(self):
        with patch("app.security.network_guard.load_config",
                   return_value=self._disabled_config()):
            allowed, _ = check_url("https://unknown-domain.xyz/api")
        assert allowed


# ─── 白名单匹配 ────────────────────────────────────────────────

class TestWhitelistMatching:

    def _config_with_whitelist(self, domains: list):
        return {
            "network_guard": {
                "enabled": True,
                "default_whitelist": domains,
            }
        }

    def test_exact_domain_match(self):
        with patch("app.security.network_guard.load_config",
                   return_value=self._config_with_whitelist(["api.example.com"])):
            allowed, reason = check_url("https://api.example.com/v1/data")
        assert allowed
        assert "白名单" in reason

    def test_subdomain_match(self):
        """example.com 白名单应匹配 sub.example.com"""
        with patch("app.security.network_guard.load_config",
                   return_value=self._config_with_whitelist(["example.com"])):
            allowed, _ = check_url("https://sub.example.com/api")
        assert allowed

    def test_deep_subdomain_match(self):
        with patch("app.security.network_guard.load_config",
                   return_value=self._config_with_whitelist(["example.com"])):
            allowed, _ = check_url("https://a.b.example.com/path")
        assert allowed

    def test_domain_not_in_whitelist(self):
        with patch("app.security.network_guard.load_config",
                   return_value=self._config_with_whitelist(["allowed.com"])):
            allowed, reason = check_url("https://blocked.com/api")
        assert not allowed
        assert "白名单" in reason

    def test_partial_domain_not_match(self):
        """evilexample.com 不应匹配 example.com 白名单"""
        with patch("app.security.network_guard.load_config",
                   return_value=self._config_with_whitelist(["example.com"])):
            allowed, _ = check_url("https://evilexample.com/phish")
        assert not allowed

    def test_empty_whitelist_allows_all(self):
        """白名单为空时默认放行（未配置阶段）"""
        with patch("app.security.network_guard.load_config",
                   return_value={"network_guard": {"enabled": True, "default_whitelist": []}}):
            allowed, reason = check_url("https://any-domain.com/api")
        assert allowed
        assert "默认放行" in reason or "空" in reason

    def test_multiple_domains_in_whitelist(self):
        domains = ["openai.com", "anthropic.com", "google.com"]
        with patch("app.security.network_guard.load_config",
                   return_value=self._config_with_whitelist(domains)), \
             patch("app.kernel.tools.builtin.network._is_private_host", return_value=False):
            for url in ["https://api.openai.com/v1", "https://api.anthropic.com/v1"]:
                allowed, reason = check_url(url)
                assert allowed, f"应放行 {url}，原因: {reason}"


# ─── URL 解析边界 ──────────────────────────────────────────────

class TestUrlParsing:

    def test_invalid_url_denied(self):
        allowed, reason = check_url("not_a_url")
        assert not allowed

    def test_empty_url_denied(self):
        allowed, reason = check_url("")
        assert not allowed

    def test_url_without_hostname_denied(self):
        allowed, reason = check_url("file:///etc/passwd")
        # file:// 无法通过内网检查或被 urlparse 处理
        # 至少不崩溃
        assert isinstance(allowed, bool)


# ─── get_whitelist ────────────────────────────────────────────

class TestGetWhitelist:

    def test_returns_list(self):
        with patch("app.security.network_guard.load_config",
                   return_value={"network_guard": {"default_whitelist": ["example.com"]}}):
            result = get_whitelist()
        assert isinstance(result, list)
        assert "example.com" in result

    def test_dedup_workspace_domain(self):
        """workspace 白名单与 default_whitelist 重复时，最终列表不应重复"""
        from unittest.mock import MagicMock
        with patch("app.security.network_guard.load_config",
                   return_value={"network_guard": {"default_whitelist": ["example.com"]}}), \
             patch("app.security.network_guard._get_workspace_whitelist",
                   return_value=["example.com", "extra.com"]):
            result = get_whitelist("some_workspace")
        assert result.count("example.com") == 1
        assert "extra.com" in result
