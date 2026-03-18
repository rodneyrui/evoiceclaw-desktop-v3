/**
 * 对话页面：核心交互界面
 *
 * 模型选择 + 消息列表 + 输入框 + 权限对话框 + 历史面板
 */

import { useRef, useState, useEffect, useCallback } from "react";
import { Trash2, Terminal, History, X } from "lucide-react";
import { useDirectChat } from "./useDirectChat";
import { getSessions, deleteSession, type SessionInfo } from "./directChatApi";
import { ModelSelector } from "@/components/chat/ModelSelector";
import { MessageList } from "@/components/chat/MessageList";
import { InputArea } from "@/components/chat/InputArea";
import { LogPanel } from "@/components/chat/LogPanel";
import { PermissionDialog } from "@/components/chat/PermissionDialog";
import { useTranslation } from "react-i18next";

export default function ChatPage() {
  const { t } = useTranslation();
  const directChat = useDirectChat();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [showLogPanel, setShowLogPanel] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  const fetchSessions = useCallback(async () => {
    try {
      const list = await getSessions();
      setSessions(list);
    } catch (err) {
      console.error("获取会话列表失败:", err);
    }
  }, []);

  useEffect(() => {
    if (showHistory) {
      fetchSessions();
    }
  }, [showHistory, fetchSessions]);

  const handleDeleteSession = useCallback(
    async (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        await deleteSession(id);
        setSessions((prev) => prev.filter((s) => s.id !== id));
      } catch (err) {
        console.error("删除会话失败:", err);
      }
    },
    [],
  );

  const messages = directChat.messages.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    model: m.model,
    provider: m.provider,
    isUrlFetching: m.isUrlFetching,
    toolCalls: m.toolCalls,
    toolPhase: m.toolPhase,
    postToolContent: m.postToolContent,
  }));

  return (
    <div className="flex h-full w-full bg-background overflow-hidden">
      {/* 左侧：历史面板（可折叠） */}
      {showHistory && (
        <div className="w-64 flex-shrink-0 border-r border-border flex flex-col bg-muted/30">
          <div className="flex items-center justify-between px-3 py-3 border-b border-border">
            <span className="text-sm font-medium">{t("chat.history", "历史对话")}</span>
            <button
              type="button"
              onClick={() => setShowHistory(false)}
              className="p-1 rounded hover:bg-muted text-muted-foreground"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {sessions.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                {t("common.noData")}
              </div>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  onClick={() => {
                    directChat.loadSession(s.id);
                    setShowHistory(false);
                  }}
                  className={`group flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-muted transition-colors ${
                    s.id === directChat.conversationId
                      ? "bg-muted"
                      : ""
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate">
                      {s.title || t("chat.newChat")}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {s.message_count} {t("chat.messages", "条消息")}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <div className="flex flex-col flex-1 min-w-0">
        {/* 顶栏：模型选择 + 历史/日志/清空按钮 */}
        <div className="flex items-center gap-2 px-4 pt-4 pb-2">
          <div className="flex-1">
            <ModelSelector
              value={directChat.selectedModel}
              onChange={directChat.setSelectedModel}
            />
          </div>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              className={`p-2 rounded-lg transition-colors ${
                showHistory
                  ? "text-foreground bg-muted"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              }`}
              title={t("chat.history", "历史对话")}
            >
              <History className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setShowLogPanel((v) => !v)}
              className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title="后端日志"
            >
              <Terminal className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={directChat.clearChat}
              className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title={t("chat.newChat")}
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 消息列表 */}
        <MessageList
          messages={messages}
          isThinking={directChat.isStreaming}
          thinkingText={t("chat.thinking")}
          onScrollToBottom={() => inputRef.current?.focus()}
        />

        {/* 输入框 */}
        <InputArea
          onSend={directChat.sendMessage}
          onStop={directChat.stopStreaming}
          isStreaming={directChat.isStreaming}
          disabled={!directChat.selectedModel}
          placeholder={
            directChat.selectedModel
              ? t("chat.inputPlaceholder")
              : t("chat.selectModelFirst")
          }
          inputRef={inputRef}
        />
      </div>

      {/* 右侧：日志面板（可折叠） */}
      {showLogPanel && (
        <LogPanel
          visible={showLogPanel}
          onToggle={() => setShowLogPanel(false)}
        />
      )}

      {/* 权限请求对话框（全局浮层，替代 window.confirm） */}
      <PermissionDialog
        permissionRequest={directChat.permissionRequest}
        onRespond={directChat.respondToPermission}
      />
    </div>
  );
}
