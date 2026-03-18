/**
 * 工具执行进度条：紧凑的状态指示器
 *
 * active 状态：旋转图标 + 当前工具名
 * done 状态：可折叠的工具列表摘要
 */

import { useState } from "react";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Wrench,
  ChevronDown,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ToolCallInfo } from "@/features/chat/useDirectChat";

interface ToolProgressBarProps {
  toolCalls: ToolCallInfo[];
  phase: "active" | "done";
}

export function ToolProgressBar({ toolCalls, phase }: ToolProgressBarProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const count = toolCalls.length;
  const failedCount = toolCalls.filter((tc) => tc.status === "error").length;

  if (phase === "active") {
    const lastTool = toolCalls[toolCalls.length - 1];
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 my-2 rounded-lg bg-muted/50 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
        <span>{t("chat.toolWorking")}</span>
        <span className="text-muted-foreground/70">
          {t("chat.toolExecuted", { count })}
        </span>
        {lastTool && (
          <>
            <span className="text-muted-foreground/50">&middot;</span>
            <span className="font-mono text-muted-foreground/70">
              {lastTool.name}
            </span>
          </>
        )}
      </div>
    );
  }

  // done 状态：可折叠列表
  return (
    <div className="my-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 text-xs text-muted-foreground hover:bg-muted transition-colors w-full"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        <Wrench className="w-3.5 h-3.5" />
        <span>{t("chat.toolCompleted", { count })}</span>
        {failedCount > 0 && (
          <span className="text-destructive">
            {t("chat.toolFailed", { count: failedCount })}
          </span>
        )}
      </button>

      {expanded && (
        <div className="mt-1 ml-3 border-l-2 border-border pl-3 space-y-1">
          {toolCalls.map((tc, i) => (
            <ToolCallItem key={tc.id || i} toolCall={tc} />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolCallItem({ toolCall }: { toolCall: ToolCallInfo }) {
  const { t } = useTranslation();
  const [showResult, setShowResult] = useState(false);

  return (
    <div className="text-xs">
      <div className="flex items-center gap-2 py-0.5">
        <button
          type="button"
          onClick={() => toolCall.result && setShowResult(!showResult)}
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
        >
          {toolCall.status === "error" ? (
            <XCircle className="w-3 h-3 text-destructive" />
          ) : toolCall.status === "success" ? (
            <CheckCircle2 className="w-3 h-3 text-green-500" />
          ) : (
            <Loader2 className="w-3 h-3 animate-spin" />
          )}
          <span className="font-mono">{toolCall.name}</span>
          {toolCall.result && (
            <span className="text-muted-foreground/50 text-[10px]">
              {showResult ? t("common.collapse") : t("common.detail")}
            </span>
          )}
        </button>
        {toolCall.browseUrl && (
          <a
            href={toolCall.browseUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors text-[10px]"
            onClick={(e) => e.stopPropagation()}
          >
            {t("chat.viewPage", "查看网页")}
            <ExternalLink className="w-2.5 h-2.5" />
          </a>
        )}
      </div>

      {showResult && toolCall.result && (
        <pre className="mt-1 p-2 rounded bg-muted text-[10px] font-mono whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
          {toolCall.result}
        </pre>
      )}
    </div>
  );
}
