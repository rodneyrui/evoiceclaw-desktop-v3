"""规则生成子系统 — 基于评测数据自动生成路由规则

子模块：
- reasoning_model_detector: 自动检测深度思维模型（用户不可见）
- rule_generator: 调用深度思维模型生成 4 个 YAML 规则文件
- hot_reload: 轮询监听规则文件变更，通知 SmartRouter 重载
- usage_trigger: 基于对话轮次触发规则生成
- prompt: 构造规则生成 Prompt
"""

from app.evaluation.rules.rule_generator import RuleGenerator, generate_rules, init_rule_generator, get_rule_generator
from app.evaluation.rules.hot_reload import RulesHotReloader, init_hot_reloader, get_hot_reloader
from app.evaluation.rules.usage_trigger import UsageTrigger, init_usage_trigger, get_usage_trigger
from app.evaluation.rules.reasoning_model_detector import detect_reasoning_model

__all__ = [
    "RuleGenerator",
    "generate_rules",
    "init_rule_generator",
    "get_rule_generator",
    "RulesHotReloader",
    "init_hot_reloader",
    "get_hot_reloader",
    "UsageTrigger",
    "init_usage_trigger",
    "get_usage_trigger",
    "detect_reasoning_model",
]
