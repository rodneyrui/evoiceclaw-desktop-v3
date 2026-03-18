#!/usr/bin/env python3
"""从 Benchmark SQLite 同步评测分数到 Desktop preset_evaluations.json

用法：python3 backend/scripts/sync_benchmark_scores.py
"""

import json
import os
import sqlite3
from pathlib import Path

BENCHMARK_DB = Path(
    os.environ.get("BENCHMARK_DB_PATH", str(Path(__file__).resolve().parent.parent.parent.parent / "eVoiceClawBenchmark" / "data" / "benchmark.db"))
)
PRESET_FILE = Path(__file__).parent.parent / "data" / "preset" / "preset_evaluations.json"

ALL_DIMS = [
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_business",
    "knowledge_legal", "knowledge_medical", "logic", "reasoning",
    "instruction_following",
]


def read_benchmark_scores() -> dict[str, dict[str, float]]:
    """从 benchmark.db 读取所有已完成 run 的评测分数，按 model_id 聚合。

    不同模型可能在不同 run 中测试，所以取所有 completed run 的数据，
    同一模型同一维度有多条时取最新 run 的值。
    """
    conn = sqlite3.connect(str(BENCHMARK_DB))
    rows = conn.execute("""
        SELECT s.model_id, s.dimension, s.raw_score
        FROM benchmark_scores s
        JOIN benchmark_runs r ON s.run_id = r.run_id
        WHERE r.status = 'completed'
        ORDER BY r.created_at DESC
    """).fetchall()
    conn.close()

    scores_by_model: dict[str, dict[str, float]] = {}
    for model_id, dim, score in rows:
        if model_id not in scores_by_model:
            scores_by_model[model_id] = {}
        # ORDER BY DESC 保证先遇到的是最新值，跳过重复
        if dim not in scores_by_model[model_id]:
            scores_by_model[model_id][dim] = score
    return scores_by_model


def sync():
    if not BENCHMARK_DB.exists():
        print(f"错误：Benchmark 数据库不存在: {BENCHMARK_DB}")
        return

    # 1. 读取 Benchmark 数据
    benchmark_scores = read_benchmark_scores()
    if not benchmark_scores:
        print("Benchmark 数据库中没有已完成的评测数据")
        return

    print(f"从 Benchmark 读取到 {len(benchmark_scores)} 个模型的评测数据：")
    for mid, scores in benchmark_scores.items():
        print(f"  {mid}: {len(scores)} 个维度")

    # 2. 读取现有 preset
    with open(PRESET_FILE, "r", encoding="utf-8") as f:
        preset = json.load(f)

    # 3. model_id → preset 条目索引
    preset_index = {m["model_id"]: i for i, m in enumerate(preset["models"])}

    # 4. 更新或新增
    for model_id, scores in benchmark_scores.items():
        # 派生 reasoning = (logic + instruction_following + math_reasoning) / 3
        if all(d in scores for d in ["logic", "instruction_following", "math_reasoning"]):
            scores["reasoning"] = round(
                (scores["logic"] + scores["instruction_following"] + scores["math_reasoning"]) / 3, 1
            )

        not_measured = [d for d in ALL_DIMS if d not in scores]

        if model_id in preset_index:
            entry = preset["models"][preset_index[model_id]]
            # 保留未测维度的旧值
            for dim in not_measured:
                if dim in entry["dimension_scores"]:
                    scores[dim] = entry["dimension_scores"][dim]
                    # 仍然标记为未实测
            entry["dimension_scores"] = scores
            entry["source"] = "benchmark_real"
            entry["not_measured_dims"] = [d for d in not_measured if d != "reasoning"]
            print(f"  更新: {model_id} (source → benchmark_real)")
        else:
            preset["models"].append({
                "model_id": model_id,
                "source": "benchmark_real",
                "dimension_scores": scores,
                "avg_latency_ms": 0,
                "cost_input_per_m": 0.0,
                "cost_output_per_m": 0.0,
                "context_window": 128000,
                "not_measured_dims": [d for d in not_measured if d != "reasoning"],
            })
            print(f"  新增: {model_id}")

    # 5. 写回
    with open(PRESET_FILE, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n同步完成：{len(benchmark_scores)} 个模型的评测数据已更新到 {PRESET_FILE.name}")


if __name__ == "__main__":
    sync()
