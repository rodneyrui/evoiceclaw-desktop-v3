/**
 * 消息列表：虚拟滚动 + Markdown 渲染 + 代码块复制
 *
 * [P1修复] RenderContent 和 ToolAwareContent 用 React.memo 包裹：
 * - 历史消息的 content 不变时完全跳过重渲染
 * - 流式消息已由 useDirectChat 50ms 批量更新，渲染频率降低 ~5x
 */

import { memo, useMemo, useRef, useState, useEffect } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { Copy, Download, ArrowDown } from "lucide-react";
import { Virtuoso } from "react-virtuoso";
import type { VirtuosoHandle } from "react-virtuoso";
import { useTranslation } from "react-i18next";
import { ToolProgressBar } from "./ToolProgressBar";
import type { ToolCallInfo } from "@/features/chat/useDirectChat";

interface Message {
  id: string;
  role: "user" | "assistant" | "divider";
  content: string;
  model?: string;
  provider?: string;
  isUrlFetching?: boolean;
  toolCalls?: ToolCallInfo[];
  toolPhase?: "active" | "done" | null;
  postToolContent?: string;
}

interface MessageListProps {
  messages: Message[];
  isThinking?: boolean;
  thinkingText?: string;
  onScrollToBottom?: () => void;
}

export function MessageList({
  messages,
  isThinking,
  thinkingText,
  onScrollToBottom,
}: MessageListProps) {
  const { t } = useTranslation();
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const prevLenRef = useRef(messages.length);

  // 追踪不在底部时的新消息数
  useEffect(() => {
    const diff = messages.length - prevLenRef.current;
    if (!atBottom && diff > 0) {
      setUnreadCount((c) => c + diff);
    }
    if (atBottom) {
      setUnreadCount(0);
    }
    prevLenRef.current = messages.length;
  }, [messages.length, atBottom]);

  const scrollToEnd = () => {
    virtuosoRef.current?.scrollToIndex({
      index: messages.length - 1,
      align: "end",
      behavior: "smooth",
    });
    setUnreadCount(0);
    onScrollToBottom?.();
  };

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-4">
        <div className="relative w-24 h-24 flex items-center justify-center">
          <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center">
            <span className="text-3xl font-bold text-primary">AI</span>
          </div>
        </div>
        <div className="space-y-2 max-w-md">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            {t("chat.title")}
          </h2>
          <p className="text-muted-foreground text-sm">
            {t("chat.selectMode")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 h-full relative">
      <Virtuoso
        ref={virtuosoRef}
        data={messages}
        followOutput={(isAtBottom) => (isAtBottom ? "smooth" : false)}
        atBottomStateChange={setAtBottom}
        atBottomThreshold={80}
        initialTopMostItemIndex={Math.max(0, messages.length - 1)}
        className="h-full"
        itemContent={(_index, message) => (
          <div className="px-6 py-3">
            {message.role === "divider" ? (
              <div className="flex items-center gap-3 my-2">
                <div className="flex-1 h-px bg-border" />
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  {t("chat.freshDivider")}
                </span>
                <div className="flex-1 h-px bg-border" />
              </div>
            ) : (
            <div
              className={cn(
                "flex w-full",
                message.role === "user" ? "justify-end" : "justify-start",
              )}
            >
              <div
                className={cn(
                  "flex max-w-[80%] gap-3",
                  message.role === "user" ? "flex-row-reverse" : "flex-row",
                )}
              >
                <div
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold border border-border",
                    message.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {message.role === "user" ? "U" : "AI"}
                </div>

                <div className="space-y-1">
                  {message.role === "assistant" && message.model && (
                    <div className="flex items-center justify-between ml-1 mr-1">
                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground uppercase tracking-wider">
                        <span>{message.model}</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => downloadResult(message.content)}
                        className="p-1 rounded text-muted-foreground/50 hover:text-foreground hover:bg-muted transition-colors"
                        title={t("chat.downloadResult")}
                      >
                        <Download className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}

                  {message.role === "assistant" && !message.model && (
                    <div className="flex justify-end mr-1">
                      <button
                        type="button"
                        onClick={() => downloadResult(message.content)}
                        className="p-1 rounded text-muted-foreground/50 hover:text-foreground hover:bg-muted transition-colors"
                        title={t("chat.downloadResult")}
                      >
                        <Download className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}

                  <div
                    className={cn(
                      "p-4 rounded-2xl text-base leading-relaxed shadow-sm",
                      message.role === "user"
                        ? "bg-primary text-primary-foreground rounded-tr-sm"
                        : "bg-card border border-border text-card-foreground rounded-tl-sm",
                    )}
                  >
                    {message.toolPhase && message.toolCalls?.length ? (
                      <ToolAwareContent
                        content={message.content}
                        postToolContent={message.postToolContent}
                        toolCalls={message.toolCalls}
                        toolPhase={message.toolPhase}
                      />
                    ) : (
                      <RenderContent content={message.content} />
                    )}
                  </div>

                  {message.isUrlFetching && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground ml-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                      {t("chat.urlDetected")}
                    </div>
                  )}
                </div>
              </div>
            </div>
            )}
          </div>
        )}
        components={{
          Footer: () =>
            isThinking ? (
              <div className="px-6 py-3">
                <div className="flex justify-start w-full">
                  <div className="flex max-w-[80%] gap-3">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold border border-border bg-muted text-muted-foreground">
                      AI
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                        {thinkingText || t("chat.thinking")}
                      </div>
                      <div className="space-y-2 w-64">
                        <Skeleton className="h-4 w-full bg-muted" />
                        <Skeleton className="h-4 w-3/4 bg-muted" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : null,
        }}
      />

      {/* 回到底部浮动按钮 */}
      {!atBottom && (
        <button
          type="button"
          onClick={scrollToEnd}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 px-4 py-2 rounded-full bg-primary text-primary-foreground text-xs font-medium shadow-lg hover:bg-primary/90 transition-all animate-in fade-in slide-in-from-bottom-2 duration-200"
        >
          <ArrowDown className="w-3.5 h-3.5" />
          {unreadCount > 0 || isThinking
            ? t("chat.newMessages")
            : t("chat.scrollToBottom")}
        </button>
      )}
    </div>
  );
}

function downloadResult(content: string) {
  const timestamp = new Date()
    .toISOString()
    .replace(/[:.]/g, "-")
    .slice(0, 19);
  const filename = `result_${timestamp}.md`;
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** URL 消毒：仅允许 http/https 协议，防止 javascript:/data: XSS */
function sanitizeUrl(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return url;
    }
    return "#";
  } catch {
    return "#";
  }
}

function renderInline(text: string): React.ReactNode {
  const linkPattern =
    /(\[[^\]]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>"{}|\\^`[\]]+)/g;
  const segments = text.split(linkPattern);

  return segments.map((seg, i) => {
    const mdMatch = seg.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (mdMatch) {
      return (
        <a
          key={i}
          href={sanitizeUrl(mdMatch[2])}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline hover:opacity-80"
        >
          {mdMatch[1]}
        </a>
      );
    }
    if (/^https?:\/\//.test(seg)) {
      const cleanUrl = seg.replace(/[.,;:!?，。；：！？、)]+$/, "");
      const trailing = seg.slice(cleanUrl.length);
      return (
        <span key={i}>
          <a
            href={sanitizeUrl(cleanUrl)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline hover:opacity-80 break-all"
          >
            {cleanUrl}
          </a>
          {trailing}
        </span>
      );
    }
    return renderBoldAndCode(seg, i);
  });
}

function renderBoldAndCode(text: string, keyPrefix: number): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>;
    }
    const codeParts = part.split(/(`[^`]+`)/g);
    return codeParts.map((cp, j) => {
      if (cp.startsWith("`") && cp.endsWith("`")) {
        return (
          <code
            key={`${keyPrefix}-${i}-${j}`}
            className="px-1 py-0.5 bg-muted rounded text-xs font-mono"
          >
            {cp.slice(1, -1)}
          </code>
        );
      }
      return <span key={`${keyPrefix}-${i}-${j}`}>{cp}</span>;
    });
  });
}

/**
 * [P1修复] memo 包裹：历史消息内容不变时跳过重渲染
 * useMemo 缓存解析结果，仅在 content 变化时重新构建元素树
 */
const RenderContent = memo(function RenderContent({ content }: { content: string }) {
  const elements = useMemo(() => {
    const lines = content.split("\n");
    const result: React.ReactNode[] = [];
    let inCodeBlock = false;
    let codeLines: string[] = [];
    let codeLang = "";

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      if (line.startsWith("```")) {
        if (!inCodeBlock) {
          inCodeBlock = true;
          codeLang = line.slice(3).trim();
          codeLines = [];
        } else {
          inCodeBlock = false;
          const code = codeLines.join("\n");
          result.push(
            <div
              key={i}
              className="my-3 p-3 bg-muted rounded-lg border border-border font-mono text-xs overflow-x-auto relative group"
            >
              <button
                onClick={() => navigator.clipboard.writeText(code)}
                className="absolute right-2 top-2 p-1 rounded opacity-0 group-hover:opacity-100 bg-muted hover:bg-muted-foreground/20 transition-all"
              >
                <Copy className="w-3 h-3 text-muted-foreground" />
              </button>
              {codeLang && (
                <div className="text-[10px] text-muted-foreground mb-2">
                  {codeLang}
                </div>
              )}
              <pre className="whitespace-pre-wrap">{code}</pre>
            </div>,
          );
        }
        continue;
      }

      if (inCodeBlock) {
        codeLines.push(line);
        continue;
      }

      if (line.startsWith("# ")) {
        result.push(
          <h1 key={i} className="text-lg font-bold mb-2">
            {line.slice(2)}
          </h1>,
        );
      } else if (line.startsWith("## ")) {
        result.push(
          <h2 key={i} className="text-base font-bold mb-2 mt-4">
            {line.slice(3)}
          </h2>,
        );
      } else if (line.startsWith("### ")) {
        result.push(
          <h3 key={i} className="text-sm font-bold mb-1 mt-3">
            {line.slice(4)}
          </h3>,
        );
      } else if (line.startsWith("- ")) {
        result.push(
          <li key={i} className="ml-4 list-disc">
            {renderInline(line.slice(2))}
          </li>,
        );
      } else if (line.trim() === "") {
        result.push(<div key={i} className="h-2" />);
      } else {
        result.push(
          <p key={i} className="mb-1">
            {renderInline(line)}
          </p>,
        );
      }
    }

    return result;
  }, [content]);

  return <>{elements}</>;
});

/** [P1修复] memo 包裹：工具感知渲染，避免工具结果不变时重渲染 */
const ToolAwareContent = memo(function ToolAwareContent({
  content,
  postToolContent,
  toolCalls,
  toolPhase,
}: {
  content: string;
  postToolContent?: string;
  toolCalls: ToolCallInfo[];
  toolPhase: "active" | "done";
}) {
  const preToolContent = postToolContent
    ? content.slice(0, content.length - postToolContent.length)
    : content;

  return (
    <>
      {preToolContent.trim() && <RenderContent content={preToolContent} />}
      <ToolProgressBar toolCalls={toolCalls} phase={toolPhase} />
      {postToolContent?.trim() && <RenderContent content={postToolContent} />}
    </>
  );
});
