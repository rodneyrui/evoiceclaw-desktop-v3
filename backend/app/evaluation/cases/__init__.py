"""评测题目汇总 — 11 维度 × 15 题 = 165 题"""

from app.evaluation.cases.coding import CODING_TESTS
from app.evaluation.cases.math_reasoning import MATH_TESTS
from app.evaluation.cases.logic import LOGIC_TESTS
from app.evaluation.cases.long_context import LONG_CONTEXT_TESTS
from app.evaluation.cases.agent_tool_use import TOOL_USE_TESTS
from app.evaluation.cases.chinese_writing import WRITING_TESTS
from app.evaluation.cases.instruction_following import INSTRUCTION_FOLLOWING_TESTS
from app.evaluation.cases.knowledge_tech import KNOWLEDGE_TECH_TESTS
from app.evaluation.cases.knowledge_business import KNOWLEDGE_BUSINESS_TESTS
from app.evaluation.cases.knowledge_legal import KNOWLEDGE_LEGAL_TESTS
from app.evaluation.cases.knowledge_medical import KNOWLEDGE_MEDICAL_TESTS

DIMENSIONS = [
    "coding", "math_reasoning", "logic", "long_context",
    "agent_tool_use", "chinese_writing", "instruction_following",
    "knowledge_tech", "knowledge_business", "knowledge_legal",
    "knowledge_medical"
]

ALL_TESTS = (
    CODING_TESTS + MATH_TESTS + LOGIC_TESTS + LONG_CONTEXT_TESTS +
    TOOL_USE_TESTS + WRITING_TESTS + INSTRUCTION_FOLLOWING_TESTS +
    KNOWLEDGE_TECH_TESTS + KNOWLEDGE_BUSINESS_TESTS + KNOWLEDGE_LEGAL_TESTS + KNOWLEDGE_MEDICAL_TESTS
)
