"""领域模型单元测试（修复版本）"""

import json
from datetime import datetime
from app.domain.models import (
    ChatMessage, MessageRole, ToolCall, StreamChunk, StreamChunkType,
    SensitivityLevel, RedactionEntry
)


def test_message_role_enum():
    """测试消息角色枚举"""
    assert MessageRole.SYSTEM == "system"
    assert MessageRole.USER == "user"
    assert MessageRole.ASSISTANT == "assistant"
    assert MessageRole.TOOL == "tool"
    
    # 测试枚举值
    assert MessageRole("system") == MessageRole.SYSTEM
    assert MessageRole("user") == MessageRole.USER


def test_stream_chunk_type_enum():
    """测试流式块类型枚举"""
    assert StreamChunkType.TEXT == "text"
    assert StreamChunkType.THINKING == "thinking"
    assert StreamChunkType.TOOL_CALL == "tool_call"
    assert StreamChunkType.TOOL_RESULT == "tool_result"
    assert StreamChunkType.URL_DETECTED == "url_detected"
    assert StreamChunkType.PERMISSION_REQUEST == "permission_request"
    assert StreamChunkType.ERROR == "error"
    assert StreamChunkType.STATUS == "status"
    assert StreamChunkType.END == "end"


def test_sensitivity_level_enum():
    """测试敏感度等级枚举"""
    assert SensitivityLevel.CRITICAL == "critical"
    assert SensitivityLevel.HIGH == "high"
    assert SensitivityLevel.MEDIUM == "medium"
    assert SensitivityLevel.LOW == "low"
    
    # 测试顺序（从高到低）
    levels = list(SensitivityLevel)
    assert levels == [
        SensitivityLevel.CRITICAL,
        SensitivityLevel.HIGH,
        SensitivityLevel.MEDIUM,
        SensitivityLevel.LOW
    ]


def test_chat_message_creation():
    """测试聊天消息创建"""
    # 基本消息
    message = ChatMessage(
        role=MessageRole.USER,
        content="Hello, world!"
    )
    
    assert message.role == MessageRole.USER
    assert message.content == "Hello, world!"
    assert message.id is not None
    assert len(message.id) > 0
    assert message.model is None
    assert message.tool_calls is None
    assert message.tool_call_id is None
    assert message.name is None
    assert message.reasoning_content is None
    assert message.user_id == "default"
    
    # 验证时间戳格式
    try:
        datetime.fromisoformat(message.created_at)
    except ValueError:
        pytest.fail(f"Invalid ISO format: {message.created_at}")
    
    # 带工具调用的消息
    tool_call = ToolCall(id="call_123", name="search", arguments={"query": "test"})
    message_with_tools = ChatMessage(
        role=MessageRole.ASSISTANT,
        content="I'll search for that.",
        model="deepseek-chat",
        tool_calls=[tool_call],
        reasoning_content="User wants me to search for information."
    )
    
    assert message_with_tools.role == MessageRole.ASSISTANT
    assert message_with_tools.model == "deepseek-chat"
    assert len(message_with_tools.tool_calls) == 1
    assert message_with_tools.tool_calls[0].name == "search"
    assert message_with_tools.reasoning_content == "User wants me to search for information."


def test_tool_call_creation():
    """测试工具调用创建"""
    tool_call = ToolCall(
        id="call_abc123",
        name="web_search",
        arguments={"query": "Python testing", "max_results": 5}
    )
    
    assert tool_call.id == "call_abc123"
    assert tool_call.name == "web_search"
    assert tool_call.arguments == {"query": "Python testing", "max_results": 5}
    
    # 测试JSON序列化
    json_str = json.dumps({
        "id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments
    })
    data = json.loads(json_str)
    assert data["id"] == "call_abc123"
    assert data["name"] == "web_search"


def test_stream_chunk_creation():
    """测试流式块创建"""
    # 文本块
    text_chunk = StreamChunk(
        type=StreamChunkType.TEXT,
        content="Hello",
        model="deepseek-chat",
        provider="deepseek"
    )
    
    assert text_chunk.type == StreamChunkType.TEXT
    assert text_chunk.content == "Hello"
    assert text_chunk.model == "deepseek-chat"
    assert text_chunk.provider == "deepseek"
    assert text_chunk.tool_call is None
    assert text_chunk.trace_id is None
    assert text_chunk.usage is None
    assert text_chunk.reasoning_content == ""
    
    # 工具调用块
    tool_call = ToolCall(id="call_123", name="search", arguments={"query": "test"})
    tool_chunk = StreamChunk(
        type=StreamChunkType.TOOL_CALL,
        tool_call=tool_call,
        trace_id="trace_123"
    )
    
    assert tool_chunk.type == StreamChunkType.TOOL_CALL
    assert tool_chunk.tool_call == tool_call
    assert tool_chunk.trace_id == "trace_123"
    assert tool_chunk.content == ""
    
    # 推理内容块
    thinking_chunk = StreamChunk(
        type=StreamChunkType.THINKING,
        content="",
        reasoning_content="I need to think about this carefully..."
    )
    
    assert thinking_chunk.type == StreamChunkType.THINKING
    assert thinking_chunk.reasoning_content == "I need to think about this carefully..."


def test_redaction_entry_creation():
    """测试脱敏条目创建"""
    entry = RedactionEntry(
        original="张三",
        type="PERSON_NAME",
        sensitivity=SensitivityLevel.HIGH,
        placeholder="__REDACTED_uuid123__"
    )
    
    assert entry.original == "张三"
    assert entry.type == "PERSON_NAME"
    assert entry.sensitivity == SensitivityLevel.HIGH
    assert entry.placeholder == "__REDACTED_uuid123__"
    
    # 测试不同敏感度等级
    critical_entry = RedactionEntry(
        original="123456789012345678",
        type="ID_CARD",
        sensitivity=SensitivityLevel.CRITICAL,
        placeholder="__REDACTED_uuid456__"
    )
    
    assert critical_entry.sensitivity == SensitivityLevel.CRITICAL
    assert critical_entry.type == "ID_CARD"


def test_chat_message_with_custom_id():
    """测试使用自定义ID创建聊天消息"""
    custom_id = "msg_123456"
    message = ChatMessage(
        role=MessageRole.SYSTEM,
        content="You are a helpful assistant.",
        id=custom_id
    )
    
    assert message.id == custom_id
    assert message.role == MessageRole.SYSTEM
    assert message.content == "You are a helpful assistant."


def test_chat_message_with_tool_call_id():
    """测试带工具调用ID的消息"""
    message = ChatMessage(
        role=MessageRole.TOOL,
        content="Search result: Found 5 items.",
        name="web_search",
        tool_call_id="call_123"
    )
    
    assert message.role == MessageRole.TOOL
    assert message.name == "web_search"
    assert message.tool_call_id == "call_123"
    assert message.content == "Search result: Found 5 items."


def test_stream_chunk_with_usage():
    """测试带使用量信息的流式块"""
    chunk = StreamChunk(
        type=StreamChunkType.END,
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    )
    
    assert chunk.type == StreamChunkType.END
    assert chunk.usage["prompt_tokens"] == 100
    assert chunk.usage["completion_tokens"] == 50
    assert chunk.usage["total_tokens"] == 150


def test_message_user_id():
    """测试消息的用户ID字段"""
    # 默认用户ID
    message1 = ChatMessage(role=MessageRole.USER, content="Hello")
    assert message1.user_id == "default"
    
    # 自定义用户ID
    message2 = ChatMessage(
        role=MessageRole.USER,
        content="Hello",
        user_id="user_123"
    )
    assert message2.user_id == "user_123"


def test_dataclass_equality():
    """测试数据类相等性"""
    # 相同内容的ChatMessage应该不相等（因为ID不同）
    msg1 = ChatMessage(role=MessageRole.USER, content="Hello")
    msg2 = ChatMessage(role=MessageRole.USER, content="Hello")
    assert msg1.id != msg2.id  # ID应该不同
    assert msg1 != msg2  # 整体不相等
    
    # 相同ID和时间的消息应该相等
    same_id = "test_id"
    same_time = "2024-01-01T00:00:00"
    msg3 = ChatMessage(
        role=MessageRole.USER, 
        content="Hello", 
        id=same_id, 
        created_at=same_time
    )
    msg4 = ChatMessage(
        role=MessageRole.USER, 
        content="Hello", 
        id=same_id, 
        created_at=same_time
    )
    assert msg3 == msg4
    
    # ToolCall相等性
    tool1 = ToolCall(id="id1", name="search", arguments={"q": "test"})
    tool2 = ToolCall(id="id1", name="search", arguments={"q": "test"})
    tool3 = ToolCall(id="id2", name="search", arguments={"q": "test"})
    assert tool1 == tool2
    assert tool1 != tool3
    
    # RedactionEntry相等性
    entry1 = RedactionEntry(
        original="test",
        type="TEST",
        sensitivity=SensitivityLevel.LOW,
        placeholder="__TEST__"
    )
    entry2 = RedactionEntry(
        original="test",
        type="TEST",
        sensitivity=SensitivityLevel.LOW,
        placeholder="__TEST__"
    )
    assert entry1 == entry2