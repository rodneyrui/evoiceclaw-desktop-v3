"""Embedding 服务：文本向量化

支持两种模式:
  - "openai": 通过 LiteLLM 调用 OpenAI 兼容 API（text-embedding-3-small 等）
  - "local": 本地 sentence-transformers 模型（BAAI/bge-small-zh-v1.5 等）

配置来源: config.yaml 的 embedding 段 + secrets.yaml 的 api_key。
"""

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("evoiceclaw.embedding")

# ── 全局单例 ──

_service: "EmbeddingService | None" = None


@dataclass
class CacheStats:
    """缓存统计信息。"""
    hits: int = 0
    misses: int = 0
    size: int = 0
    maxsize: int = 0

    @property
    def hit_rate(self) -> float:
        """缓存命中率（0.0 ~ 1.0）。"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class EmbeddingService:
    """文本 Embedding 服务。"""

    def __init__(self, config: dict, secrets: dict | None = None):
        """初始化 Embedding 服务。

        Args:
            config: embedding 配置段
            secrets: 含 API Key 的 secrets 配置
        """
        self._provider = config.get("provider", "openai")
        self._model = config.get("model", "text-embedding-3-small")
        self._dim = config.get("dim", 1536)
        self._secrets = secrets or {}

        # 本地模型实例（延迟初始化）
        self._local_model: Any = None

        # ── LRU 缓存 ──
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_maxsize: int = config.get("cache_maxsize", 256)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

        logger.info(
            "[Embedding] 初始化: provider=%s model=%s dim=%d cache_maxsize=%d",
            self._provider, self._model, self._dim, self._cache_maxsize,
        )

    @property
    def dim(self) -> int:
        """向量维度。"""
        return self._dim

    @property
    def cache_stats(self) -> CacheStats:
        """返回缓存统计信息。"""
        return CacheStats(
            hits=self._cache_hits,
            misses=self._cache_misses,
            size=len(self._cache),
            maxsize=self._cache_maxsize,
        )

    def clear_cache(self) -> None:
        """清空 embedding 缓存。"""
        old_size = len(self._cache)
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        logger.info("[Embedding] 缓存已清空（原有 %d 条）", old_size)

    def _cache_get(self, text: str) -> list[float] | None:
        """从 LRU 缓存中查找向量。命中时自动移到队尾（最近使用）。"""
        if text in self._cache:
            # 移到队尾表示最近使用
            self._cache.move_to_end(text)
            self._cache_hits += 1
            return self._cache[text]
        self._cache_misses += 1
        return None

    def _cache_put(self, text: str, vector: list[float]) -> None:
        """将向量写入 LRU 缓存，超过容量时淘汰最早的条目。"""
        if text in self._cache:
            # 已存在则更新并移到队尾
            self._cache.move_to_end(text)
            self._cache[text] = vector
            return
        # 淘汰最旧的条目
        if len(self._cache) >= self._cache_maxsize:
            self._cache.popitem(last=False)
        self._cache[text] = vector

    async def embed(self, text: str) -> list[float]:
        """将单条文本转为向量。优先查缓存。

        Args:
            text: 输入文本

        Returns:
            浮点数列表（维度 = self._dim）
        """
        # 查缓存
        cached = self._cache_get(text)
        if cached is not None:
            return cached

        # 未命中，调用实际编码
        if self._provider == "local":
            vector = self._embed_local(text)
        else:
            vector = await self._embed_api(text)

        # 写入缓存
        self._cache_put(text, vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化。已缓存的文本不重复计算。

        Args:
            texts: 文本列表

        Returns:
            向量列表（顺序与 texts 对应）
        """
        if not texts:
            return []

        # 分离已缓存和未缓存的文本
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            cached = self._cache_get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # 仅对未缓存文本调用编码
        if uncached_texts:
            if self._provider == "local":
                new_vectors = self._embed_local_batch(uncached_texts)
            else:
                new_vectors = await self._embed_api_batch(uncached_texts)

            # 填回结果并写入缓存
            for idx, text, vector in zip(uncached_indices, uncached_texts, new_vectors):
                results[idx] = vector
                self._cache_put(text, vector)

        if uncached_texts:
            logger.debug(
                "[Embedding] 批量完成: 共 %d 条, 缓存命中 %d, 新编码 %d",
                len(texts), len(texts) - len(uncached_texts), len(uncached_texts),
            )

        # 此时 results 中不应有 None（类型断言）
        return results  # type: ignore[return-value]

    # ── API 模式（LiteLLM） ──

    async def _embed_api(self, text: str) -> list[float]:
        """通过 LiteLLM 调用 Embedding API。"""
        results = await self._embed_api_batch([text])
        return results[0]

    async def _embed_api_batch(self, texts: list[str]) -> list[list[float]]:
        """批量 API embedding。"""
        import litellm

        # 获取 API Key
        api_key = self._resolve_api_key()

        try:
            response = await litellm.aembedding(
                model=self._model,
                input=texts,
                api_key=api_key,
                dimensions=self._dim if "embedding-3" in self._model else None,
            )
            vectors = [item["embedding"] for item in response.data]
            logger.debug("[Embedding] API 批量完成: %d 条文本", len(texts))
            return vectors
        except Exception as e:
            logger.error("[Embedding] API 调用失败: %s", e)
            raise

    def _resolve_api_key(self) -> str | None:
        """从 secrets 中解析 API Key。"""
        # 尝试从 providers 段获取
        providers = self._secrets.get("providers", {})
        if self._provider == "openai" and providers.get("openai", {}).get("api_key"):
            return providers["openai"]["api_key"]
        # 尝试从 llm 段获取（兼容 DeepSeek 等使用 OpenAI 兼容 API 的 provider）
        llm_key = self._secrets.get("llm", {}).get("api_key")
        if llm_key:
            return llm_key
        return None

    # ── 本地模式（sentence-transformers） ──

    def _get_local_model(self) -> Any:
        """延迟加载本地 embedding 模型。"""
        if self._local_model is not None:
            return self._local_model

        try:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(self._model)
            logger.info("[Embedding] 本地模型已加载: %s", self._model)
            return self._local_model
        except ImportError:
            raise RuntimeError(
                "本地 embedding 需要安装 sentence-transformers: "
                "pip install sentence-transformers"
            )

    def _embed_local(self, text: str) -> list[float]:
        """使用本地模型生成 embedding。"""
        model = self._get_local_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def _embed_local_batch(self, texts: list[str]) -> list[list[float]]:
        """批量本地 embedding。"""
        model = self._get_local_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        if isinstance(vectors, np.ndarray):
            return vectors.tolist()
        return [v.tolist() for v in vectors]

    def zero_vector(self) -> list[float]:
        """返回零向量（用于占位）。"""
        return [0.0] * self._dim


def init_embedding_service(config: dict, secrets: dict | None = None) -> "EmbeddingService":
    """初始化全局 Embedding 服务单例。"""
    global _service
    _service = EmbeddingService(
        config=config.get("embedding", {}),
        secrets=secrets,
    )
    return _service


def get_embedding_service() -> "EmbeddingService":
    """获取全局 Embedding 服务。"""
    if _service is None:
        raise RuntimeError("EmbeddingService 未初始化，请先调用 init_embedding_service()")
    return _service
