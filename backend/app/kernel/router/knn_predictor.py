"""kNN 需求向量预测器：用 bge-small 向量 + kNN 回归替代 LLM 意图分类

基于 Cerebellum R1 标注的锚点数据（2000+ 条），将用户消息编码为向量后，
在锚点向量矩阵中找 top-K 近邻，加权平均其 15 维需求标签作为预测结果。

性能：~30ms（本地 embedding + numpy dot），远优于 LLM 分类器的 ~500ms。
精度：Cosine=0.9223，优于 LLM 分类器的 ~0.85。
"""

import hashlib
import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("evoiceclaw.kernel.knn_predictor")

# 锚点数据和缓存路径
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_ANCHORS_PATH = _DATA_DIR / "preset" / "intent_anchors.jsonl"
_CACHE_DIR = _DATA_DIR / "cache"
_VECTORS_CACHE = _CACHE_DIR / "intent_anchor_vectors.npy"
_HASH_CACHE = _CACHE_DIR / "intent_anchor_vectors.hash"

# 15 维需求维度（与 smart_router.ALL_DIMS 一致）
ALL_DIMS = [
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_business",
    "knowledge_legal", "knowledge_medical", "logic", "reasoning",
    "instruction_following",
    "cost_sensitivity", "speed_priority", "context_need",
]

# 置信度阈值（基于 top-K 邻居标签标准差）
_HIGH_CONFIDENCE_THRESHOLD = 0.87   # std < 此值 → 高置信度
_LOW_CONFIDENCE_THRESHOLD = 1.42    # std > 此值 → 低置信度，建议降级 LLM

# kNN 参数
_TOP_K = 5


class KNNPredictor:
    """基于语义向量 kNN 回归的需求向量预测器。"""

    def __init__(self) -> None:
        self._anchor_texts: list[str] = []
        self._anchor_labels: np.ndarray | None = None   # shape: (N, 15)
        self._anchor_matrix: np.ndarray | None = None    # shape: (N, dim), L2 归一化
        self._ready = False

    def is_available(self) -> bool:
        """检查预测器是否就绪（锚点已加载且 embedding 服务可用）。"""
        return self._ready and self._anchor_matrix is not None

    def _load_anchors(self) -> tuple[list[str], np.ndarray]:
        """从 jsonl 文件加载锚点文本和标签。"""
        if not _ANCHORS_PATH.exists():
            raise FileNotFoundError(f"锚点数据文件不存在: {_ANCHORS_PATH}")

        texts: list[str] = []
        labels: list[list[int]] = []

        with open(_ANCHORS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                texts.append(item["message"])
                req = item["requirements"]
                labels.append([req.get(dim, 0) for dim in ALL_DIMS])

        logger.info("[kNN] 加载锚点数据: %d 条", len(texts))
        return texts, np.array(labels, dtype=np.float32)

    def _file_hash(self) -> str:
        """计算锚点文件的 MD5 哈希（用于缓存失效判断）。"""
        h = hashlib.md5()
        with open(_ANCHORS_PATH, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _try_load_cache(self, expected_count: int) -> np.ndarray | None:
        """尝试从 .npy 缓存加载锚点向量矩阵。"""
        if not _VECTORS_CACHE.exists() or not _HASH_CACHE.exists():
            return None

        # 检查文件哈希是否匹配
        cached_hash = _HASH_CACHE.read_text(encoding="utf-8").strip()
        current_hash = self._file_hash()
        if cached_hash != current_hash:
            logger.info("[kNN] 锚点数据已变更（hash 不匹配），需重新编码")
            return None

        matrix = np.load(str(_VECTORS_CACHE))
        if matrix.shape[0] != expected_count:
            logger.info("[kNN] 缓存向量数量不匹配（%d vs %d），需重新编码",
                        matrix.shape[0], expected_count)
            return None

        logger.info("[kNN] 从缓存加载锚点向量: shape=%s", matrix.shape)
        return matrix

    def _save_cache(self, matrix: np.ndarray) -> None:
        """保存锚点向量矩阵到 .npy 缓存。"""
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(str(_VECTORS_CACHE), matrix)
        _HASH_CACHE.write_text(self._file_hash(), encoding="utf-8")
        logger.info("[kNN] 锚点向量已缓存: %s", _VECTORS_CACHE)

    async def warmup(self) -> None:
        """预热：加载锚点数据并编码为向量矩阵。

        需要 EmbeddingService 已初始化。编码结果缓存到 .npy 文件，
        后续启动直接加载（<1ms）。
        """
        from app.infrastructure.embedding import get_embedding_service

        try:
            embed_svc = get_embedding_service()
        except RuntimeError:
            logger.warning("[kNN] EmbeddingService 未初始化，跳过预热")
            return

        # 加载锚点文本和标签
        try:
            self._anchor_texts, self._anchor_labels = self._load_anchors()
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("[kNN] 加载锚点数据失败: %s", e)
            return

        n = len(self._anchor_texts)

        # 尝试从缓存加载
        cached = self._try_load_cache(n)
        if cached is not None:
            self._anchor_matrix = cached
            self._ready = True
            logger.info("[kNN] 预热完成（缓存命中），%d 条锚点就绪", n)
            return

        # 缓存未命中，批量编码
        logger.info("[kNN] 开始编码 %d 条锚点文本...", n)
        batch_size = 256
        all_vectors: list[list[float]] = []

        for i in range(0, n, batch_size):
            batch = self._anchor_texts[i:i + batch_size]
            vectors = await embed_svc.embed_batch(batch)
            all_vectors.extend(vectors)
            if i + batch_size < n:
                logger.info("[kNN] 编码进度: %d/%d", min(i + batch_size, n), n)

        matrix = np.array(all_vectors, dtype=np.float32)

        # L2 归一化（使 dot product = cosine similarity）
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)  # 避免除零
        matrix = matrix / norms

        self._anchor_matrix = matrix
        self._save_cache(matrix)
        self._ready = True
        logger.info("[kNN] 预热完成（新编码），%d 条锚点，向量维度 %d", n, matrix.shape[1])

    async def predict(self, message: str) -> tuple[dict[str, int], float]:
        """预测用户消息的 15 维需求向量。

        Args:
            message: 用户消息文本

        Returns:
            (requirements_dict, confidence)
            - requirements_dict: {dim_name: 0-10 int}
            - confidence: 置信度指标（top-K 邻居标签的平均标准差，越低越确信）
        """
        from app.infrastructure.embedding import get_embedding_service

        embed_svc = get_embedding_service()

        # 编码用户消息
        query_vec = np.array(await embed_svc.embed(message), dtype=np.float32)

        # L2 归一化
        norm = np.linalg.norm(query_vec)
        if norm > 1e-10:
            query_vec = query_vec / norm

        # 计算 cosine 相似度（锚点矩阵已归一化，dot product = cosine）
        sims = self._anchor_matrix @ query_vec  # (N,)

        # 取 top-K 邻居
        top_k_idx = np.argsort(sims)[-_TOP_K:][::-1]
        top_k_sims = sims[top_k_idx]

        # 相似度加权（clamp 负值）
        weights = np.maximum(top_k_sims, 0.0)
        weight_sum = weights.sum()
        if weight_sum < 1e-10:
            # 极端情况：所有相似度为负，均匀加权
            weights = np.ones(_TOP_K, dtype=np.float32) / _TOP_K
        else:
            weights = weights / weight_sum

        # 加权平均标签
        top_k_labels = self._anchor_labels[top_k_idx]  # (K, 15)
        predicted = (weights[:, np.newaxis] * top_k_labels).sum(axis=0)  # (15,)

        # 置信度：top-K 邻居标签的平均标准差（越低越一致 → 越确信）
        label_std = top_k_labels.std(axis=0).mean()

        # 转为字典，round 到整数，clamp 0-10
        req: dict[str, int] = {}
        for i, dim in enumerate(ALL_DIMS):
            val = int(round(float(predicted[i])))
            req[dim] = max(0, min(10, val))

        logger.info(
            "[kNN] 预测完成: confidence=%.3f top_sim=%.3f | %s | 输入=%s",
            label_std, float(top_k_sims[0]),
            {k: v for k, v in req.items() if v > 0},
            message[:60],
        )

        return req, float(label_std)


# ── 模块级单例 ──

_predictor: KNNPredictor | None = None


def get_knn_predictor() -> KNNPredictor | None:
    """获取 kNN 预测器实例（可能为 None，表示未初始化）。"""
    return _predictor


async def init_knn_predictor() -> KNNPredictor:
    """初始化并预热 kNN 预测器。"""
    global _predictor
    _predictor = KNNPredictor()
    await _predictor.warmup()
    return _predictor
