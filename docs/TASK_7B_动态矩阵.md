# TASK 7B — 动态模型矩阵

> **Phase**: 7B
> **工作量**: 中
> **依赖**: Phase 7A 已完成
> **目标**: 改造 ModelMatrix 从 LanceDB 动态读取，支持热加载

---

## 一、任务目标

将静态的 `ModelMatrix` 改造为动态系统：
1. 从 LanceDB `model_evaluations` 表读取最新评测数据
2. 保留内存缓存，提升查询性能
3. 监听 `RulesUpdated` 事件，自动重载数据
4. 确保 SmartRouter 无感知变化

---

## 二、当前 ModelMatrix 结构

**文件**: `backend/app/kernel/router/model_matrix.py`

**当前实现**（静态硬编码）:
```python
MODEL_MATRIX = {
    "deepseek/deepseek-chat": {
        "coding": 5, "math_reasoning": 5, "logic": 5,
        # ... 13 维能力评分
        "cost_input_per_m": 2.0,
        "cost_output_per_m": 3.0,
        "context_window": 128000,
    },
    # ... 其余 18 个模型
}

def get_model_score(model_id: str, dimension: str) -> int:
    """获取模型在某维度的得分"""
    return MODEL_MATRIX.get(model_id, {}).get(dimension, 0)
```

---

## 三、改造方案

### 3.1 新增动态加载逻辑

**保留原有接口**，内部改为从 LanceDB 读取：

```python
"""动态模型矩阵 — 从 LanceDB 读取最新评测数据"""

import json
import logging
from datetime import datetime
from typing import Dict, Any

from app.infrastructure.vector_db import get_connection

logger = logging.getLogger(__name__)


class ModelMatrix:
    """动态模型矩阵

    从 LanceDB model_evaluations 表读取最新评测数据，
    保留内存缓存，支持热加载。
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_reload: datetime | None = None
        self._load_from_db()

    def _load_from_db(self):
        """从 LanceDB 加载最新评测数据"""
        try:
            db = get_connection()
            table = db.open_table("model_evaluations")

            # 查询所有模型的最新评测记录
            # 按 model_id 分组，取 timestamp 最新的记录
            results = table.to_pandas()

            if results.empty:
                logger.warning("[ModelMatrix] LanceDB 中无评测数据，使用空矩阵")
                return

            # 按 model_id 分组，取最新记录
            latest = results.sort_values("timestamp").groupby("model_id").last()

            # 转换为内存缓存格式
            self._cache.clear()
            for model_id, row in latest.iterrows():
                dimension_scores = json.loads(row["dimension_scores"])
                self._cache[model_id] = {
                    **dimension_scores,  # 13 维能力得分
                    "cost_input_per_m": float(row["cost_input_per_m"]),
                    "cost_output_per_m": float(row["cost_output_per_m"]),
                    "context_window": int(row["context_window"]),
                    "avg_latency_ms": int(row["avg_latency_ms"]),
                    "source": row["source"],
                    "eval_id": row["eval_id"],
                    "timestamp": row["timestamp"],
                }

            self._last_reload = datetime.now()
            logger.info(f"[ModelMatrix] ✅ 加载 {len(self._cache)} 个模型数据")

        except Exception as e:
            logger.error(f"[ModelMatrix] 加载失败: {e}", exc_info=True)

    def reload(self):
        """重新加载数据（热加载）"""
        logger.info("[ModelMatrix] 重新加载评测数据")
        self._load_from_db()

    def get_model_score(self, model_id: str, dimension: str) -> int:
        """获取模型在某维度的得分（0-100）

        兼容旧接口，返回 0-100 分数
        """
        model_data = self._cache.get(model_id, {})
        score = model_data.get(dimension, 0)

        # 如果是 0-5 等级，转换为 0-100 分数
        if 0 <= score <= 5:
            return int(score * 20)
        return int(score)

    def get_model_data(self, model_id: str) -> Dict[str, Any]:
        """获取模型完整数据"""
        return self._cache.get(model_id, {})

    def get_all_models(self) -> list[str]:
        """获取所有已评测模型列表"""
        return list(self._cache.keys())

    def get_models_by_dimension(self, dimension: str, min_score: int = 80) -> list[str]:
        """获取某维度得分 >= min_score 的模型列表"""
        return [
            model_id
            for model_id, data in self._cache.items()
            if self.get_model_score(model_id, dimension) >= min_score
        ]


# 全局单例
_matrix_instance: ModelMatrix | None = None


def get_model_matrix() -> ModelMatrix:
    """获取 ModelMatrix 单例"""
    global _matrix_instance
    if _matrix_instance is None:
        _matrix_instance = ModelMatrix()
    return _matrix_instance


# 兼容旧接口
def get_model_score(model_id: str, dimension: str) -> int:
    """获取模型在某维度的得分（兼容旧接口）"""
    return get_model_matrix().get_model_score(model_id, dimension)
```

### 3.2 事件监听与热加载

**文件**: `backend/app/domain/events.py`（已有，新增事件类型）

```python
class EventType(str, Enum):
    # ... 现有事件
    RULES_UPDATED = "rules_updated"  # 规则文件更新
```

**文件**: `backend/app/kernel/router/model_matrix.py`（续）

```python
from app.domain.events import EventType, SystemEvent

def on_rules_updated(event: SystemEvent):
    """监听规则更新事件，重载矩阵数据"""
    if event.event_type == EventType.RULES_UPDATED:
        logger.info("[ModelMatrix] 收到规则更新事件，重新加载")
        get_model_matrix().reload()


# 在 main.py lifespan 中注册事件监听
# event_bus.subscribe(EventType.RULES_UPDATED, on_rules_updated)
```

### 3.3 SmartRouter 适配

**文件**: `backend/app/kernel/router/smart_router.py`（无需修改）

SmartRouter 当前通过 `get_model_score()` 函数获取模型得分，由于我们保留了该接口，SmartRouter 无需任何修改。

**验证点**：
```python
# SmartRouter 中的调用
from app.kernel.router.model_matrix import get_model_score

score = get_model_score("deepseek/deepseek-chat", "coding")
# 预期：返回 100（从 LanceDB 读取）
```

---

## 四、实施步骤

### 4.1 备份现有 model_matrix.py

```bash
cp backend/app/kernel/router/model_matrix.py \
   backend/app/kernel/router/model_matrix.py.backup
```

### 4.2 替换为动态实现

将上述 `ModelMatrix` 类代码写入 `model_matrix.py`，完全替换原有静态字典。

### 4.3 在 main.py 中初始化

**文件**: `backend/app/main.py`（修改 lifespan）

```python
from app.kernel.router.model_matrix import get_model_matrix

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=== eVoiceClaw Desktop v3 启动 ===")

    # 初始化数据库
    init_db()
    init_vector_db()

    # 加载预置评测数据
    await load_preset_evaluations()

    # 初始化 ModelMatrix（从 LanceDB 加载）
    matrix = get_model_matrix()
    logger.info(f"[Startup] ModelMatrix 已加载 {len(matrix.get_all_models())} 个模型")

    # ... 其他初始化

    yield

    logger.info("=== eVoiceClaw Desktop v3 关闭 ===")
```

### 4.4 添加事件监听（可选，Phase 7D 实现）

在 Phase 7D 规则生成器完成后，添加事件总线监听：

```python
# 在 main.py lifespan 中
from app.kernel.router.model_matrix import on_rules_updated
from app.domain.events import EventType

# 假设有全局 event_bus
event_bus.subscribe(EventType.RULES_UPDATED, on_rules_updated)
```

---

## 五、验证步骤

### 5.1 验证数据加载

```bash
# 启动服务
cd backend
uvicorn app.main:app --reload

# 查看日志
# 预期输出: [ModelMatrix] ✅ 加载 17 个模型数据
```

### 5.2 验证接口兼容性

```python
# 在 Python REPL 中测试
from app.kernel.router.model_matrix import get_model_score, get_model_matrix

# 测试旧接口
score = get_model_score("deepseek/deepseek-chat", "coding")
print(f"DeepSeek-V3 代码得分: {score}")
# 预期输出: DeepSeek-V3 代码得分: 100

# 测试新接口
matrix = get_model_matrix()
models = matrix.get_all_models()
print(f"已加载模型数: {len(models)}")
# 预期输出: 已加载模型数: 17

# 测试维度筛选
coding_models = matrix.get_models_by_dimension("coding", min_score=90)
print(f"代码能力 >= 90 的模型: {coding_models}")
```

### 5.3 验证 SmartRouter 路由

```bash
# 发送测试请求
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "写一个 Python 快速排序", "model": "auto"}'

# 查看日志，确认 SmartRouter 正确选择了代码能力高的模型
# 预期: [SmartRouter] 选择模型: deepseek/deepseek-chat (代码任务)
```

### 5.4 验证热加载

```python
# 在 Python REPL 中
from app.kernel.router.model_matrix import get_model_matrix

matrix = get_model_matrix()

# 手动触发重载
matrix.reload()

# 查看日志
# 预期输出: [ModelMatrix] 重新加载评测数据
#          [ModelMatrix] ✅ 加载 17 个模型数据
```

---

## 六、性能优化

### 6.1 缓存策略

当前实现已包含内存缓存，查询性能与静态字典相当。

**缓存失效时机**：
- 收到 `RulesUpdated` 事件
- 手动调用 `reload()`

### 6.2 查询优化

如果模型数量增长到 100+ 个，可考虑：
- 为常用维度建立索引（如 `_cache_by_dimension`）
- 使用 LRU 缓存热点查询

---

## 七、回滚方案

如果动态加载出现问题，可快速回滚：

```bash
# 恢复备份
cp backend/app/kernel/router/model_matrix.py.backup \
   backend/app/kernel/router/model_matrix.py

# 重启服务
```

---

## 八、交付清单

- [x] `backend/app/kernel/router/model_matrix.py`（动态实现）
- [x] `ModelMatrix` 类（从 LanceDB 读取）
- [x] 兼容旧接口（`get_model_score()`）
- [x] 热加载机制（`reload()`）
- [x] 事件监听（`on_rules_updated()`）
- [x] `main.py` 集成初始化

---

## 九、注意事项

1. **接口兼容性**：保留 `get_model_score()` 函数，确保 SmartRouter 无需修改
2. **性能**：内存缓存确保查询性能不下降
3. **容错**：LanceDB 加载失败时，使用空矩阵，记录错误日志
4. **热加载**：仅在收到事件时重载，避免频繁查询数据库

---

## 十、下一步

完成 Phase 7B 后，进入 **Phase 7C: 调度+执行**，实现评测任务状态机和执行器。
