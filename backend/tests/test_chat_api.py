"""Chat API 测试"""

import asyncio
import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock

from app.main import app
from app.api.deps import get_config


class TestChatAPI:
    """Chat API 端点测试"""

    @pytest.fixture
    def mock_config(self):
        """模拟配置"""
        return {
            "llm": {
                "providers": {
                    "deepseek": {
                        "api_key": "test-key",
                        "base_url": "https://api.deepseek.com"
                    }
                }
            }
        }

    @pytest.fixture
    async def client(self, mock_config):
        """测试客户端（httpx AsyncClient + ASGI transport）

        starlette 0.27 + httpx 0.28 不兼容：TestClient 内部使用
        httpx.Client(app=...) 已在 httpx 0.20+ 移除，改用 ASGITransport。
        dependency_overrides 注入 mock_config，避免 app.state.config 未初始化。
        """
        async def override_get_config():
            return mock_config

        app.dependency_overrides[get_config] = override_get_config
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_chat_request_validation(self, client):
        """测试聊天请求格式验证（Pydantic 层校验，不触及服务层）"""
        # 消息长度超限
        response = await client.post("/api/v1/chat", json={
            "message": "a" * 100001,
            "model": "deepseek/deepseek-chat"
        })
        assert response.status_code == 422

        # conversation_id 含非法字符
        response = await client.post("/api/v1/chat", json={
            "message": "你好",
            "conversation_id": "invalid@id",
            "model": "deepseek/deepseek-chat"
        })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_stream_response(self, client):
        """测试流式聊天响应"""
        with patch('app.services.chat_service.start_stream_session') as mock_start:
            mock_session = MagicMock()
            mock_session.queue = asyncio.Queue()
            mock_session.conversation_id = "test-conv-123"

            test_chunks = [
                {"type": "text", "content": "你好", "model": "deepseek-chat", "provider": "deepseek"},
                {"type": "text", "content": "世界", "model": "deepseek-chat", "provider": "deepseek"},
                {"type": "end", "content": "", "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
            ]
            for chunk in test_chunks:
                mock_session.queue.put_nowait(chunk)
            mock_session.queue.put_nowait(None)
            mock_start.return_value = mock_session

            response = await client.post("/api/v1/chat", json={
                "message": "你好",
                "model": "deepseek/deepseek-chat"
            })

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

            lines = response.text.split('\n')
            data_lines = [line for line in lines if line.startswith('data: ')]
            assert len(data_lines) >= 2

            first_data = json.loads(data_lines[0][6:])
            assert first_data["type"] == "text"
            assert first_data["content"] == "你好"

    @pytest.mark.asyncio
    async def test_chat_stream_error_handling(self, client):
        """测试流式聊天错误处理"""
        with patch('app.services.chat_service.start_stream_session') as mock_start:
            mock_session = MagicMock()
            mock_session.queue = asyncio.Queue()
            mock_session.conversation_id = "test-conv-123"

            error_chunk = {"type": "error", "content": "连接超时", "error": "timeout"}
            mock_session.queue.put_nowait(error_chunk)
            mock_session.queue.put_nowait(None)
            mock_start.return_value = mock_session

            response = await client.post("/api/v1/chat", json={
                "message": "你好",
                "model": "deepseek/deepseek-chat"
            })

            assert response.status_code == 200

            lines = response.text.split('\n')
            data_lines = [line for line in lines if line.startswith('data: ')]
            error_lines = [line for line in data_lines if '"type": "error"' in line]
            assert len(error_lines) > 0
            error_data = json.loads(error_lines[0][6:])
            assert error_data["type"] == "error"
            assert "连接超时" in error_data["content"]

    @pytest.mark.asyncio
    async def test_recover_stream_endpoint(self, client):
        """测试恢复流式会话端点"""
        # 非法 conversation_id
        response = await client.get("/api/v1/chat/invalid@id/recover")
        assert response.status_code == 400

        # 不存在的会话，返回 active=False
        response = await client.get("/api/v1/chat/nonexistent-conv/recover")
        assert response.status_code == 200
        data = response.json()
        assert data["active"] is False
        assert data["full_text"] == ""

    @pytest.mark.asyncio
    async def test_list_models_endpoint(self, client):
        """测试获取模型列表端点"""
        mock_models = [
            {
                "id": "deepseek/deepseek-chat",
                "name": "DeepSeek Chat",
                "provider": "deepseek",
                "type": "api",
                "mode": "fast"
            },
            {
                "id": "claude/claude-3",
                "name": "Claude 3",
                "provider": "anthropic",
                "type": "cli",
                "mode": "analysis"
            }
        ]

        with patch('app.services.chat_service.get_available_models',
                   return_value=mock_models):
            response = await client.get("/api/v1/chat/models")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["id"] == "deepseek/deepseek-chat"
            assert data[0]["type"] == "api"
            assert data[1]["type"] == "cli"

    @pytest.mark.asyncio
    async def test_chat_system_prompt(self, client):
        """测试系统提示词功能"""
        with patch('app.services.chat_service.start_stream_session') as mock_start:
            mock_session = MagicMock()
            mock_session.queue = asyncio.Queue()
            mock_session.conversation_id = "new-session"

            mock_session.queue.put_nowait({"type": "text", "content": "好的", "model": "test"})
            mock_session.queue.put_nowait(None)
            mock_start.return_value = mock_session

            response = await client.post("/api/v1/chat", json={
                "message": "你好",
                "model": "deepseek/deepseek-chat",
                "system_prompt": "你是一个助手",
                "conversation_id": None
            })

            assert response.status_code == 200
            mock_start.assert_called_once()
            call_args = mock_start.call_args
            assert call_args.kwargs["system_prompt"] == "你是一个助手"

    @pytest.mark.asyncio
    async def test_chat_existing_conversation(self, client):
        """测试现有会话功能"""
        with patch('app.services.chat_service.start_stream_session') as mock_start:
            mock_session = MagicMock()
            mock_session.queue = asyncio.Queue()
            mock_session.conversation_id = "existing-conv-123"

            mock_session.queue.put_nowait({"type": "text", "content": "继续", "model": "test"})
            mock_session.queue.put_nowait(None)
            mock_start.return_value = mock_session

            response = await client.post("/api/v1/chat", json={
                "message": "下一个问题",
                "model": "deepseek/deepseek-chat",
                "conversation_id": "existing-conv-123"
            })

            assert response.status_code == 200
            mock_start.assert_called_once()
            call_args = mock_start.call_args
            assert call_args.kwargs["conversation_id"] == "existing-conv-123"
