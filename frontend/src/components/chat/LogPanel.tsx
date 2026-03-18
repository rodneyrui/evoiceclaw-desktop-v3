/**
 * 后端日志实时面板
 *
 * [P2修复] 用 react-virtuoso 替代原来的 lines.map()：
 * - 原来：每条新日志触发所有 500 行重渲染
 * - 现在：只渲染可见区域内的行（约 30 行），无论总行数多少
 */

import { useEffect, useRef, useState } from "react";
import { Terminal, X, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Virtuoso } from "react-virtuoso";
import type { VirtuosoHandle } from "react-virtuoso";

interface LogPanelProps {
  visible: boolean;
  onToggle: () => void;
}

export function LogPanel({ visible, onToggle }: LogPanelProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const virtuosoRef = useRef<VirtuosoHandle>(null);

  useEffect(() => {
    if (!visible) return;

    const ac = new AbortController();
    setConnected(false);

    (async () => {
      try {
        const res = await fetch("/api/v1/logs/stream", {
          signal: ac.signal,
        });
        if (!res.ok || !res.body) return;
        setConnected(true);

        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split("\n");
          buf = parts.pop() ?? "";

          const newLines: string[] = [];
          for (const part of parts) {
            if (part.startsWith("data: ")) {
              const text = part.slice(6);
              if (text) newLines.push(text);
            }
          }
          if (newLines.length > 0) {
            setLines((prev) => {
              const merged = [...prev, ...newLines];
              return merged.length > 500 ? merged.slice(-500) : merged;
            });
          }
        }
      } catch (err) {
        if ((err as { name?: string }).name !== "AbortError") {
          console.error("Log stream error:", err);
        }
      } finally {
        setConnected(false);
      }
    })();

    return () => {
      ac.abort();
    };
  }, [visible]);

  // 新日志到来时自动滚到底部
  useEffect(() => {
    if (lines.length > 0) {
      virtuosoRef.current?.scrollToIndex({
        index: lines.length - 1,
        align: "end",
        behavior: "auto",
      });
    }
  }, [lines.length]);

  if (!visible) return null;

  return (
    <div className="w-[640px] flex flex-col h-full bg-background border-l border-border">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Terminal className="w-3.5 h-3.5" />
          <span>后端日志</span>
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full",
              connected ? "bg-green-500" : "bg-red-500",
            )}
          />
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setLines([])}
            className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors"
            title="清空日志"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onToggle}
            className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors"
            title="关闭面板"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 日志内容（虚拟化列表） */}
      <div className="flex-1 overflow-hidden bg-muted/10">
        {lines.length === 0 ? (
          <div className="text-muted-foreground/50 text-center pt-8 text-xs font-mono p-3">
            等待日志输出...
          </div>
        ) : (
          <Virtuoso
            ref={virtuosoRef}
            data={lines}
            className="h-full"
            itemContent={(_index, line) => (
              <div
                className={cn(
                  "px-3 py-0.5 font-mono text-[13px] leading-[1.6] whitespace-pre-wrap break-all select-text",
                  line.includes("ERROR")
                    ? "text-red-600"
                    : line.includes("WARNING")
                      ? "text-amber-600"
                      : line.includes("INFO")
                        ? "text-blue-600"
                        : "text-muted-foreground",
                )}
              >
                {line}
              </div>
            )}
          />
        )}
      </div>
    </div>
  );
}
