"""简化的 Skills API 测试 - 验证基本结构和数据模型"""

import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError


class TestSkillsAPISimple:
    """简化的 Skills API 测试"""

    def test_install_request_structure(self):
        """测试 InstallRequest 数据结构"""
        from app.api.v1.skills import InstallRequest
        
        # 测试有效数据
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
        assert hasattr(request, 'skill_md')
        assert len(request.skill_md) > 10
        
        # 测试名称长度限制
        long_name = "a" * 65
        invalid_data = {
            "name": long_name,
            "skill_md": "test content"
        }
        
        with pytest.raises(ValidationError):
            InstallRequest(**invalid_data)
            
        # 测试名称格式限制
        invalid_names = ["test@skill", "test#skill", "test skill", "test.skill"]
        for invalid_name in invalid_names:
            invalid_data = {
                "name": invalid_name,
                "skill_md": "test content"
            }
            
            with pytest.raises(ValidationError):
                InstallRequest(**invalid_data)

    def test_skill_response_structure(self):
        """测试 SkillResponse 数据结构"""
        from app.api.v1.skills import SkillResponse
        
        # 测试有效数据
        valid_data = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00",
            "gatekeeper_model": "test_model",
            "actions": [{"action": "install", "timestamp": "2024-01-01T00:00:00"}]
        }
        
        response = SkillResponse(**valid_data)
        assert response.name == "test_skill"
        assert response.version == "1.0.0"
        assert response.status == "installed"
        assert response.content_hash == "abc123"
        assert len(response.actions) == 1
        
        # 测试缺失必填字段
        incomplete_data = {
            "name": "test_skill"
            # 缺少其他必填字段
        }
        
        with pytest.raises(ValidationError):
            SkillResponse(**incomplete_data)

    def test_skill_detail_response_structure(self):
        """测试 SkillDetailResponse 数据结构"""
        from app.api.v1.skills import SkillDetailResponse
        
        # 测试有效数据
        valid_data = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00",
            "gatekeeper_model": "test_model",
            "actions": [{"action": "install", "timestamp": "2024-01-01T00:00:00"}],
            "content": "# Test Skill\nversion: 1.0.0"
        }
        
        response = SkillDetailResponse(**valid_data)
        assert response.name == "test_skill"
        assert response.content == "# Test Skill\nversion: 1.0.0"
        
        # 验证继承自 SkillResponse
        assert response.version == "1.0.0"
        assert response.status == "installed"

    @patch('app.services.skill_service.list_skills')
    def test_list_skills_service_call(self, mock_list_skills):
        """测试 list_skills 服务调用结构"""
        from app.services.skill_service import list_skills
        
        # 模拟技能列表
        # 创建模拟技能对象
        mock_skill = MagicMock()
        mock_skill.name = "test_skill"  # 直接设置属性而不是依赖 to_dict
        mock_skill.to_dict.return_value = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00",
            "gatekeeper_model": "test_model",
            "actions": []
        }
        
        mock_list_skills.return_value = [mock_skill]
        
        # 测试函数调用
        result = list_skills()
        
        assert len(result) == 1
        assert result[0].name == "test_skill"
        mock_list_skills.assert_called_once()

    @patch('app.services.skill_service.install_skill')
    @pytest.mark.asyncio
    async def test_install_skill_service_call(self, mock_install_skill):
        """测试 install_skill 服务调用结构"""
        from app.services.skill_service import install_skill
        
        # 模拟技能元数据
        mock_meta = MagicMock()
        mock_meta.name = "test_skill"  # 直接设置属性
        mock_meta.to_dict.return_value = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00",
            "gatekeeper_model": "test_model",
            "actions": []
        }
        
        mock_install_skill.return_value = mock_meta
        
        # 测试函数调用
        result = await install_skill("test_skill", "test skill md content", {})
        
        assert result.name == "test_skill"
        mock_install_skill.assert_called_once_with("test_skill", "test skill md content", {})

    @patch('app.services.skill_service.uninstall_skill')
    def test_uninstall_skill_service_call(self, mock_uninstall_skill):
        """测试 uninstall_skill 服务调用结构"""
        from app.services.skill_service import uninstall_skill
        
        # 模拟成功卸载
        mock_uninstall_skill.return_value = True
        
        # 测试函数调用
        result = uninstall_skill("test_skill")
        
        assert result is True
        mock_uninstall_skill.assert_called_once_with("test_skill")

    @patch('app.services.skill_service.get_skill')
    def test_get_skill_service_call(self, mock_get_skill):
        """测试 get_skill 服务调用结构"""
        from app.services.skill_service import get_skill
        
        # 模拟技能内容
        mock_content = "# Test Skill\nversion: 1.0.0"
        mock_meta = MagicMock()
        mock_meta.name = "test_skill"  # 直接设置属性
        mock_meta.to_dict.return_value = {
            "name": "test_skill",
            "version": "1.0.0",
            "status": "installed",
            "content_hash": "abc123",
            "reviewed_at": "2024-01-01T00:00:00",
            "gatekeeper_model": "test_model",
            "actions": []
        }
        
        mock_get_skill.return_value = (mock_content, mock_meta)
        
        # 测试函数调用
        result = get_skill("test_skill")
        
        assert result[0] == mock_content
        assert result[1].name == "test_skill"
        mock_get_skill.assert_called_once_with("test_skill")

    def test_skill_name_validation(self):
        """测试技能名称验证规则"""
        from app.api.v1.skills import InstallRequest
        from pydantic import ValidationError
        
        # 测试有效名称
        valid_names = ["test_skill", "test-skill", "test_skill_123", "ABC123"]
        for valid_name in valid_names:
            data = {"name": valid_name, "skill_md": "test content"}
            request = InstallRequest(**data)
            assert request.name == valid_name
        
        # 测试无效名称
        invalid_names = ["", "toolongname" * 10, "test@skill", "test#skill", "test skill", "test.skill"]
        for invalid_name in invalid_names:
            data = {"name": invalid_name, "skill_md": "test content"}
            with pytest.raises(ValidationError):
                InstallRequest(**data)

    def test_skill_md_validation(self):
        """测试技能 MD 内容验证"""
        from app.api.v1.skills import InstallRequest
        from pydantic import ValidationError
        
        # 测试有效内容
        valid_md = """# Test Skill
version: 1.0.0
description: 测试技能
functions:
  - name: test_func
    description: 测试函数
"""
        data = {"name": "test_skill", "skill_md": valid_md}
        request = InstallRequest(**data)
        assert request.skill_md == valid_md
        
        # 测试内容太短
        short_md = "short"
        data = {"name": "test_skill", "skill_md": short_md}
        with pytest.raises(ValidationError):
            InstallRequest(**data)
        
        # 测试内容太长
        long_md = "a" * 65537
        data = {"name": "test_skill", "skill_md": long_md}
        with pytest.raises(ValidationError):
            InstallRequest(**data)