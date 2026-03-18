"""配置模块单元测试"""

import tempfile
import os
from pathlib import Path
import pytest
from app.core.config import load_config, load_secrets, save_secrets, strip_secrets_from_config


def test_load_secrets(tmp_path):
    """测试加载 secrets.yaml"""
    # 创建临时的 secrets.yaml
    secrets_content = """
llm:
  api_key: sk-test-llm-key
providers:
  deepseek:
    api_key: sk-test-deepseek-key
  qwen:
    api_key: sk-test-qwen-key
services:
  bocha:
    api_key: sk-test-bocha-key
"""
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text(secrets_content, encoding="utf-8")
    
    # 临时替换 SECRETS_PATH
    import app.core.config as config_module
    original_path = config_module.SECRETS_PATH
    config_module.SECRETS_PATH = secrets_file
    
    try:
        secrets = load_secrets()
        assert secrets["llm"]["api_key"] == "sk-test-llm-key"
        assert secrets["providers"]["deepseek"]["api_key"] == "sk-test-deepseek-key"
        assert secrets["providers"]["qwen"]["api_key"] == "sk-test-qwen-key"
        assert secrets["services"]["bocha"]["api_key"] == "sk-test-bocha-key"
    finally:
        config_module.SECRETS_PATH = original_path


def test_load_config_with_secrets(tmp_path):
    """测试加载配置并合并 secrets"""
    # 创建临时的 config.yaml
    config_content = """
llm:
  model: deepseek-chat
  base_url: https://api.deepseek.com
providers:
  deepseek:
    enabled: true
    base_url: https://api.deepseek.com
  qwen:
    enabled: false
    base_url: https://dashscope.aliyuncs.com
services:
  bocha:
    enabled: true
    base_url: https://api.bocha.ai
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    
    # 创建临时的 secrets.yaml
    secrets_content = """
llm:
  api_key: sk-test-llm-key
providers:
  deepseek:
    api_key: sk-test-deepseek-key
  qwen:
    api_key: sk-test-qwen-key
services:
  bocha:
    api_key: sk-test-bocha-key
"""
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text(secrets_content, encoding="utf-8")
    
    # 临时替换 SECRETS_PATH
    import app.core.config as config_module
    original_path = config_module.SECRETS_PATH
    config_module.SECRETS_PATH = secrets_file
    
    try:
        config = load_config(str(config_file))
        
        # 检查配置合并
        assert config["llm"]["model"] == "deepseek-chat"
        assert config["llm"]["api_key"] == "sk-test-llm-key"
        
        assert config["providers"]["deepseek"]["enabled"] is True
        assert config["providers"]["deepseek"]["api_key"] == "sk-test-deepseek-key"
        
        assert config["providers"]["qwen"]["enabled"] is False
        assert config["providers"]["qwen"]["api_key"] == "sk-test-qwen-key"
        
        assert config["services"]["bocha"]["enabled"] is True
        assert config["services"]["bocha"]["api_key"] == "sk-test-bocha-key"
    finally:
        config_module.SECRETS_PATH = original_path


def test_load_config_with_env_vars(tmp_path):
    """测试环境变量替换"""
    # 创建临时的 config.yaml 包含环境变量
    config_content = """
llm:
  model: ${LLM_MODEL}
  base_url: ${LLM_BASE_URL}
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    
    # 设置环境变量
    os.environ["LLM_MODEL"] = "deepseek-chat"
    os.environ["LLM_BASE_URL"] = "https://api.deepseek.com"
    
    try:
        config = load_config(str(config_file))
        assert config["llm"]["model"] == "deepseek-chat"
        assert config["llm"]["base_url"] == "https://api.deepseek.com"
    finally:
        # 清理环境变量
        os.environ.pop("LLM_MODEL", None)
        os.environ.pop("LLM_BASE_URL", None)


def test_strip_secrets_from_config():
    """测试从配置中移除敏感信息"""
    config = {
        "llm": {
            "model": "deepseek-chat",
            "api_key": "sk-secret-key",
            "base_url": "https://api.deepseek.com"
        },
        "providers": {
            "deepseek": {
                "enabled": True,
                "api_key": "sk-deepseek-secret",
                "base_url": "https://api.deepseek.com"
            },
            "qwen": {
                "enabled": False,
                "api_key": "sk-qwen-secret"
            }
        },
        "services": {
            "bocha": {
                "enabled": True,
                "api_key": "sk-bocha-secret"
            }
        }
    }
    
    stripped = strip_secrets_from_config(config)
    
    # 检查敏感信息已被移除
    assert "api_key" not in stripped["llm"]
    assert stripped["llm"]["model"] == "deepseek-chat"
    assert stripped["llm"]["base_url"] == "https://api.deepseek.com"
    
    assert "api_key" not in stripped["providers"]["deepseek"]
    assert stripped["providers"]["deepseek"]["enabled"] is True
    assert stripped["providers"]["deepseek"]["base_url"] == "https://api.deepseek.com"
    
    assert "api_key" not in stripped["providers"]["qwen"]
    assert stripped["providers"]["qwen"]["enabled"] is False
    
    assert "api_key" not in stripped["services"]["bocha"]
    assert stripped["services"]["bocha"]["enabled"] is True


def test_save_secrets(tmp_path):
    """测试保存 secrets"""
    # 临时替换 SECRETS_PATH
    import app.core.config as config_module
    original_path = config_module.SECRETS_PATH
    temp_secrets_file = tmp_path / "secrets.yaml"
    config_module.SECRETS_PATH = temp_secrets_file
    
    try:
        secrets = {
            "llm": {"api_key": "sk-new-key"},
            "providers": {
                "deepseek": {"api_key": "sk-deepseek-new"},
                "qwen": {"api_key": "sk-qwen-new"}
            }
        }
        
        save_secrets(secrets)
        
        # 验证文件已创建
        assert temp_secrets_file.exists()
        
        # 重新加载验证内容
        loaded = load_secrets()
        assert loaded["llm"]["api_key"] == "sk-new-key"
        assert loaded["providers"]["deepseek"]["api_key"] == "sk-deepseek-new"
        assert loaded["providers"]["qwen"]["api_key"] == "sk-qwen-new"
    finally:
        config_module.SECRETS_PATH = original_path


def test_load_config_missing_files(tmp_path):
    """测试加载缺失的配置文件"""
    # 临时替换 SECRETS_PATH 到一个不存在的文件
    import app.core.config as config_module
    original_path = config_module.SECRETS_PATH
    temp_secrets_file = tmp_path / "nonexistent_secrets.yaml"
    config_module.SECRETS_PATH = temp_secrets_file
    
    try:
        # 创建一个临时的 config.yaml
        config_content = """
llm:
  model: deepseek-chat
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content, encoding="utf-8")
        
        # secrets.yaml 不存在，应该返回空字典
        secrets = load_secrets()
        assert secrets == {}
        
        # 加载配置应该成功（secrets 为空）
        config = load_config(str(config_file))
        assert config["llm"]["model"] == "deepseek-chat"
        assert "api_key" not in config.get("llm", {})
    finally:
        config_module.SECRETS_PATH = original_path