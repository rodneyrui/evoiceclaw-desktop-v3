/**
 * 模型选择器：展示所有可用 LLM 模型，按 Provider 分组
 */

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { getAvailableModels } from "@/features/chat/directChatApi";
import type { ChatModel } from "@/features/chat/directChatApi";

interface ModelSelectorProps {
  value: string;
  onChange: (modelId: string) => void;
}

// Provider 显示名称映射
const PROVIDER_LABELS: Record<string, string> = {
  deepseek: "DeepSeek",
  qwen: "Qwen (通义)",
  kimi: "Kimi (月之暗面)",
  zhipu: "Zhipu (智谱)",
  minimax: "MiniMax",
  ollama: "Ollama (本地)",
  openai: "OpenAI",
  anthropic: "Anthropic",
  cli: "CLI 代理",
};

export function ModelSelector({ value, onChange }: ModelSelectorProps) {
  const [models, setModels] = useState<ChatModel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAvailableModels()
      .then((list) => {
        setModels(list);
        if (!value) {
          onChange("auto");
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 按 provider 分组
  const grouped = models.reduce<Record<string, ChatModel[]>>((acc, m) => {
    const key = m.provider;
    if (!acc[key]) acc[key] = [];
    acc[key].push(m);
    return acc;
  }, {});

  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading}
        className="appearance-none w-full bg-card/50 border border-white/10 rounded-xl px-4 py-3 pr-10 text-sm text-foreground focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none transition-all cursor-pointer disabled:opacity-50"
      >
        {loading ? (
          <option value="">加载模型列表...</option>
        ) : models.length === 0 ? (
          <option value="">无可用模型</option>
        ) : (
          <>
            <option value="auto">
              自动选择（根据意图匹配最优模型）
            </option>
            {Object.entries(grouped).map(([provider, providerModels]) => (
              <optgroup
                key={provider}
                label={PROVIDER_LABELS[provider] || provider.toUpperCase()}
              >
                {providerModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.type === "cli" ? " (CLI)" : ""}
                    {m.mode === "fast" ? " ⚡" : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </>
        )}
      </select>
      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
    </div>
  );
}
