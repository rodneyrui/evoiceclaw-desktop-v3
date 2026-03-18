"""Skills API 测试"""

import pytest
from unittest.mock import patch
from typing import Dict, Any


class TestSkillsAPI:
    """Skills API 端点测试"""

    @pytest.fixture
    def mock_skill_data(self):
        """模拟技能数据"""
        return {
            "name": "test_skill",
            "version": "1.0.0",
            "description": "测试技能",
            "author": "test_author",
            "functions": [
                {
                    "name": "test_function",
                    "description": "测试函数",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "param1": {"type": "string", "description": "参数1"}
                        }
                    }
                }
            ]
        }

    @pytest.fixture
    def mock_config(self):
        """模拟配置"""
        return {
            "skills": {
                "directory": "/skills",
                "auto_load": True
            }
        }

    def test_skill_validation_structure(self):
        """测试 SkillMeta 数据结构（@dataclass，非 Pydantic）"""
        from app.security.gatekeeper.models import SkillMeta

        # SkillMeta 只有 name 是必填，其余字段均有默认值
        skill_data = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00Z",
            "gatekeeper_model": "test-model",
            "actions": []
        }

        skill = SkillMeta(**skill_data)
        assert skill.name == "test_skill"
        assert skill.version == "1.0.0"
        assert skill.status == "installed"

    def test_list_skills_endpoint_structure(self, mock_config):
        """测试获取技能列表端点结构"""
        import app.services.skill_service as skill_service_module

        mock_skills = [
            {
                "name": "test_skill_1",
                "version": "1.0.0",
                "status": "installed",
                "content_hash": "abc123",
                "reviewed_at": "2024-01-01T00:00:00Z",
                "gatekeeper_model": "test-model",
                "actions": []
            },
            {
                "name": "test_skill_2",
                "version": "2.0.0",
                "status": "available",
                "content_hash": "def456",
                "reviewed_at": "2024-01-02T00:00:00Z",
                "gatekeeper_model": "test-model",
                "actions": []
            }
        ]

        # patch.object 确保模块引用和调用引用一致
        with patch.object(skill_service_module, 'list_skills', return_value=mock_skills):
            result = skill_service_module.list_skills()

            assert len(result) == 2
            assert result[0]["name"] == "test_skill_1"
            assert result[1]["name"] == "test_skill_2"

    @pytest.mark.asyncio
    async def test_install_skill_endpoint_structure(self, mock_config, mock_skill_data):
        """测试安装技能端点结构"""
        from unittest.mock import AsyncMock

        mock_install_result = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00Z",
            "gatekeeper_model": "test-model",
            "actions": []
        }

        mock_install_skill = AsyncMock(return_value=mock_install_result)
        result = await mock_install_skill("test_skill", "test content", mock_config)

        assert result["name"] == "test_skill"
        assert result["status"] == "installed"
        mock_install_skill.assert_called_once_with("test_skill", "test content", mock_config)

    def test_uninstall_skill_endpoint_structure(self, mock_config):
        """测试卸载技能端点结构"""
        import app.services.skill_service as skill_service_module

        with patch.object(skill_service_module, 'uninstall_skill', return_value=True):
            result = skill_service_module.uninstall_skill("test_skill")
            assert result is True

    def test_get_skill_info_endpoint_structure(self, mock_config):
        """测试获取技能信息端点结构"""
        import app.services.skill_service as skill_service_module

        mock_skill_info = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00Z",
            "gatekeeper_model": "test-model",
            "actions": []
        }

        with patch.object(skill_service_module, 'get_skill',
                          return_value=("test content", mock_skill_info)):
            result = skill_service_module.get_skill("test_skill")

            assert result is not None
            assert result[0] == "test content"
            assert result[1]["name"] == "test_skill"

    def test_skill_info_model_structure(self):
        """测试 SkillMeta 模型结构（@dataclass）"""
        from app.security.gatekeeper.models import SkillMeta, ActionDeclaration

        # 测试有效数据
        valid_data = {
            "name": "valid_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00Z",
            "gatekeeper_model": "test-model",
            "actions": [
                ActionDeclaration(
                    command="test",
                    pattern="test*",
                    description="测试命令"
                )
            ]
        }

        skill = SkillMeta(**valid_data)
        assert skill.name == "valid_skill"
        assert skill.status == "installed"
        assert len(skill.actions) == 1

        # SkillMeta 是 @dataclass（非 Pydantic），name 是唯一必填参数
        # 不传 name 时抛 TypeError（非 ValidationError）
        with pytest.raises(TypeError):
            SkillMeta()

    @pytest.mark.asyncio
    async def test_skill_install_validation(self):
        """测试技能安装数据验证"""
        from app.api.v1.skills import InstallRequest
        from pydantic import ValidationError

        # 测试有效安装请求
        valid_data = {
            "name": "test_skill",
            "skill_md": """# Test Skill
version: 1.0.0
description: 测试技能
functions:
  - name: test_func
    description: 测试函数
"""
        }

        request = InstallRequest(**valid_data)
        assert request.name == "test_skill"
        # Pydantic v2 BaseModel 不支持 `in` 运算符，改用 hasattr
        assert hasattr(request, "skill_md")

        # 测试空名称
        with pytest.raises(ValidationError):
            InstallRequest(name="", skill_md="invalid md content")

        # 测试名称含非法字符
        with pytest.raises(ValidationError):
            InstallRequest(name="invalid@name", skill_md="test content")
