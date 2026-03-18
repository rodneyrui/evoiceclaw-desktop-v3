/**
 * 直聊模式状态管理 Hook
 *
 * 管理：消息列表、流式状态、模型选择、会话 ID、消息排队
 * 持久化：消息列表、conversationId、selectedModel 存入 localStorage，刷新后自动恢复
 * 断线恢复：页面加载后自动检查后端是否有未完成的流，轮询获取缓冲内容
 * 排队：streaming 期间允许发送新消息，用户消息立即显示，流结束后自动处理队列
 *
 * V3 适配：
 * - tool_call.name（非 function_name）
 * - 新增 url_detected 通知
 * - 移除 verification/correction/approval_request
 *
 * 稳定性修复：
 * - [P0] localStorage 写入改为 300ms 防抖（通过 useEffect），避免每个 chunk 同步写
 * - [P0] permission_request 改用 React 对话框替代阻塞式 window.confirm
 * - [P1] 文本流批量渲染：50ms 聚合一次 setAndSave，减少 DOM 更新频率
 * - [P1] 移除 web_fetch 自动 window.open — 改为后端 BrowserService 托管打开
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { streamChat, recoverStream, getSessionMessages } from "./directChatApi";

export interface ToolCallInfo {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status?: "running" | "success" | "error";
  result?: string;
  /** web_fetch/http_request 的目标 URL（window.open 被拦截时用于降级按钮） */
  browseUrl?: string;
}

export interface DirectChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  provider?: string;
  toolCalls?: ToolCallInfo[];
  isUrlFetching?: boolean;
  toolPhase?: "active" | "done" | null;
  postToolContent?: string;
}

/** 权限请求信息（供 PermissionDialog 使用） */
export interface PermissionRequestInfo {
  cmdName: string;
  command: string;
  currentLevel: string;
  requiredLevel: string;
  requestId: string;
}

const LS_MESSAGES_KEY = "evoiceclaw_v3_messages";
const LS_CONV_ID_KEY = "evoiceclaw_v3_conv_id";
const LS_MODEL_KEY = "evoiceclaw_v3_selected_model";
const MAX_PERSISTED_MESSAGES = 200;
/** localStorage 写入防抖间隔（ms） */
const SAVE_DEBOUNCE_MS = 300;
/** 流式文本批量渲染间隔（ms），降低 DOM 更新频率 */
const TEXT_FLUSH_MS = 50;

function loadMessages(): DirectChatMessage[] {
  try {
    const raw = localStorage.getItem(LS_MESSAGES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as DirectChatMessage[];
    if (!Array.isArray(parsed)) return [];
    // 恢复时修正中断的工具阶段和 URL 抓取标记
    return parsed.map((m) => ({
      ...m,
      ...(m.toolPhase === "active" ? { toolPhase: "done" as const } : {}),
      isUrlFetching: false,
    }));
  } catch {
    return [];
  }
}

function saveMessages(messages: DirectChatMessage[]) {
  try {
    const toSave = messages.slice(-MAX_PERSISTED_MESSAGES);
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify(toSave));
  } catch {
    // localStorage 满时静默忽略
  }
}

function generateId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function loadConvId(): string {
  return localStorage.getItem(LS_CONV_ID_KEY) || generateId();
}

function saveConvId(id: string) {
  localStorage.setItem(LS_CONV_ID_KEY, id);
}

function loadSelectedModel(): string {
  return localStorage.getItem(LS_MODEL_KEY) || "auto";
}

function saveSelectedModel(model: string) {
  localStorage.setItem(LS_MODEL_KEY, model);
}

export function useDirectChat() {
  const [messages, setMessages] = useState<DirectChatMessage[]>(loadMessages);
  const [isStreaming, setIsStreaming] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>(loadSelectedModel);
  const [permissionRequest, setPermissionRequest] = useState<PermissionRequestInfo | null>(null);

  const conversationId = useRef<string>(loadConvId());

  // messagesRef 始终追踪最新消息（用于 beforeunload 和异步闭包）
  const messagesRef = useRef<DirectChatMessage[]>(messages);

  // 排队机制：streaming 期间发送的消息进入队列
  const queueRef = useRef<string[]>([]);
  const streamingRef = useRef(false);
  const selectedModelRef = useRef(selectedModel);

  // AbortController：用于中断当前 streaming
  const abortControllerRef = useRef<AbortController | null>(null);

  // 恢复轮询定时器
  const recoveryPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 权限对话框 Promise resolve 函数
  const permissionResolveRef = useRef<((approved: boolean) => void) | null>(null);

  useEffect(() => {
    selectedModelRef.current = selectedModel;
    saveSelectedModel(selectedModel);
  }, [selectedModel]);

  // ── [P0修复] localStorage 防抖写入 ──
  // 每次 messages 状态变化时启动 300ms 防抖，代替原来每个 chunk 同步写一次
  useEffect(() => {
    if (messages.length === 0) return; // clearChat 后不保存空数组
    const timer = setTimeout(() => {
      saveMessages(messages);
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [messages]);

  // beforeunload 保底：页面刷新/关闭前强制保存最新状态
  useEffect(() => {
    const handleBeforeUnload = () => {
      saveMessages(messagesRef.current);
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

  // 统一的消息更新辅助函数（不再内联 localStorage 写入）
  const setAndSave = useCallback(
    (updater: (prev: DirectChatMessage[]) => DirectChatMessage[]) => {
      setMessages((prev) => {
        const next = updater(prev);
        messagesRef.current = next;
        return next;
      });
    },
    [],
  );

  // 停止恢复轮询
  const stopRecoveryPoll = useCallback(() => {
    if (recoveryPollRef.current) {
      clearInterval(recoveryPollRef.current);
      recoveryPollRef.current = null;
    }
  }, []);

  // ── [P0修复] 权限请求响应（替代 window.confirm） ──
  // 由 PermissionDialog 组件调用
  const respondToPermission = useCallback((approved: boolean) => {
    permissionResolveRef.current?.(approved);
    permissionResolveRef.current = null;
    setPermissionRequest(null);
  }, []);

  // 处理队列中的下一条消息
  const processNext = useCallback(() => {
    if (queueRef.current.length === 0 || streamingRef.current) return;

    stopRecoveryPoll();

    const text = queueRef.current.shift()!;
    const model = selectedModelRef.current;

    const assistantId = `assistant-${Date.now()}`;
    setAndSave((prev) => [
      ...prev,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        model: model === "auto" ? "" : model,
      },
    ]);
    setIsStreaming(true);
    streamingRef.current = true;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    (async () => {
      let toolStarted = false;

      // 追踪后端是否已为当前工具打开浏览器（用于远程部署降级判断）
      let browserOpenedForTool = false;

      // ── [噪音修复] <think> 标签流式过滤 ──
      // DeepSeek 等模型有时把链式思考内容直接写入 delta.content，
      // 这里逐 chunk 过滤，用户永远不会看到 <think>...</think> 内容
      let inThinkBlock = false;

      const filterThink = (raw: string): string => {
        if (!raw) return raw;
        let result = "";
        let remaining = raw;
        while (remaining.length > 0) {
          if (!inThinkBlock) {
            const openIdx = remaining.indexOf("<think>");
            if (openIdx === -1) {
              result += remaining;
              break;
            }
            result += remaining.slice(0, openIdx);
            remaining = remaining.slice(openIdx + 7);
            inThinkBlock = true;
          } else {
            const closeIdx = remaining.indexOf("</think>");
            if (closeIdx === -1) {
              // 仍在 think 块内，整段丢弃
              break;
            }
            remaining = remaining.slice(closeIdx + 8);
            inThinkBlock = false;
          }
        }
        return result;
      };

      // ── [P1修复] 文本批量渲染缓冲 ──
      // 将多个 text chunk 聚合后每 TEXT_FLUSH_MS 统一渲染一次，降低 DOM 更新频率
      let textAccumulator = "";
      let pendingModel: string | undefined;
      let pendingProvider: string | undefined;
      let flushTimer: ReturnType<typeof setTimeout> | null = null;

      const flushText = () => {
        flushTimer = null;
        if (!textAccumulator) return;
        const toFlush = textAccumulator;
        const fModel = pendingModel;
        const fProvider = pendingProvider;
        textAccumulator = "";
        pendingModel = undefined;
        pendingProvider = undefined;

        if (!toolStarted) {
          setAndSave((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: m.content + toFlush,
                    ...(fModel ? { model: fModel } : {}),
                    ...(fProvider ? { provider: fProvider } : {}),
                  }
                : m,
            ),
          );
        } else {
          setAndSave((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: m.content + toFlush,
                    ...(fModel ? { model: fModel } : {}),
                    ...(fProvider ? { provider: fProvider } : {}),
                    toolPhase: "done" as const,
                    postToolContent: (m.postToolContent || "") + toFlush,
                  }
                : m,
            ),
          );
        }
      };

      const scheduleFlush = () => {
        if (!flushTimer) {
          flushTimer = setTimeout(flushText, TEXT_FLUSH_MS);
        }
      };

      // 立即冲刷文本缓冲的辅助函数
      const immediateFlush = () => {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        flushText();
      };

      try {
        for await (const chunk of streamChat({
          message: text,
          model: model,
          conversation_id: conversationId.current,
          signal: controller.signal,
        })) {
          if (chunk.type === "text") {
            // 过滤 <think>...</think> 后累积，50ms 后统一渲染
            const visible = filterThink(chunk.content ?? "");
            if (visible) {
              textAccumulator += visible;
            }
            if (chunk.model) pendingModel = chunk.model;
            if (chunk.provider) pendingProvider = chunk.provider;
            scheduleFlush();
          } else if (chunk.type === "tool_call") {
            // 工具调用前先冲刷缓冲文本
            immediateFlush();

            const toolCall = chunk.tool_call;
            if (toolCall) {
              toolStarted = true;

              setAndSave((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? {
                        ...m,
                        toolCalls: [...(m.toolCalls || []), { ...toolCall, status: "running" as const }],
                        toolPhase: "active" as const,
                        postToolContent: "",
                      }
                    : m,
                ),
              );
            }
          } else if (chunk.type === "tool_result") {
            immediateFlush();

            const isError =
              chunk.content.startsWith("[错误]") ||
              chunk.content.startsWith("错误：") ||
              chunk.content.includes("失败");
            setAndSave((prev) =>
              prev.map((m) => {
                if (m.id !== assistantId) return m;
                const updatedToolCalls = m.toolCalls ? [...m.toolCalls] : [];
                if (updatedToolCalls.length > 0) {
                  const last = { ...updatedToolCalls[updatedToolCalls.length - 1] };
                  last.status = isError ? "error" : "success";
                  last.result = chunk.content.slice(0, 200);
                  // 远程部署降级：后端未打开浏览器时，为 web_fetch/http_request 设置手动查看按钮
                  if (
                    !browserOpenedForTool &&
                    !isError &&
                    (last.name === "web_fetch" || last.name === "http_request") &&
                    typeof last.arguments?.url === "string"
                  ) {
                    last.browseUrl = last.arguments.url as string;
                  }
                  updatedToolCalls[updatedToolCalls.length - 1] = last;
                }
                // 重置标记，为下一个工具调用做准备
                browserOpenedForTool = false;
                return {
                  ...m,
                  toolCalls: updatedToolCalls,
                  // [噪音修复] 工具错误通过 ToolProgressBar 展示，不再注入原始文本到 content
                };
              }),
            );
          } else if (chunk.type === "browser_opened") {
            // 后端已成功打开浏览器，标记当前工具无需前端降级
            browserOpenedForTool = true;
          } else if (chunk.type === "url_detected") {
            setAndSave((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, isUrlFetching: true }
                  : m,
              ),
            );
          } else if (chunk.type === "permission_request") {
            // [P0修复] 用 React 对话框替代阻塞式 window.confirm
            // window.confirm 会挂起主线程，导致 SSE 流超时中断
            immediateFlush();

            try {
              const reqData = JSON.parse(chunk.content);
              const cmdName = reqData.cmd_name || "unknown";
              const requiredLevel = reqData.required_level || "L2";
              const command = reqData.command || "";
              const requestId = reqData.request_id;
              const currentLevel = reqData.current_level || "L1";

              // [噪音修复] 不再往消息 content 里注入权限状态文字，由 PermissionDialog 显示

              // 显示对话框，等待用户决策（不阻塞主线程）
              // Promise.race：用户点击按钮 OR 用户点击"停止"（AbortError）
              const approved = await Promise.race([
                new Promise<boolean>((resolve) => {
                  permissionResolveRef.current = resolve;
                  setPermissionRequest({ cmdName, command, currentLevel, requiredLevel, requestId });
                }),
                new Promise<never>((_, reject) => {
                  controller.signal.addEventListener("abort", () =>
                    reject(new DOMException("已取消", "AbortError")),
                  );
                }),
              ]);

              fetch(`/api/v1/permissions/${requestId}/respond`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approved }),
              }).catch((err) => console.error("权限响应失败:", err));

              // [噪音修复] 不注入批准/拒绝文字，PermissionDialog 关闭即为反馈
            } catch (err) {
              if ((err as DOMException).name !== "AbortError") {
                console.error("解析权限请求失败:", err);
              }
              throw err; // 将 AbortError 传播，退出 for-await 循环
            }
          } else if (chunk.type === "error") {
            setAndSave((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: m.content || `[错误] ${chunk.content}`,
                    }
                  : m,
              ),
            );
          }
          // thinking、end 等暂不处理
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // 用户主动停止，保留已接收的内容
        } else {
          setAndSave((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: m.content || `[错误] ${String(err)}` }
                : m,
            ),
          );
        }
      } finally {
        // 冲刷剩余文本缓冲
        immediateFlush();

        // 清理权限对话框（异常退出时对话框可能还在显示）
        setPermissionRequest(null);
        permissionResolveRef.current = null;

        // 修正中断的工具阶段 + 清除 URL 抓取标记
        setAndSave((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  isUrlFetching: false,
                  ...(m.toolPhase === "active" ? { toolPhase: "done" as const } : {}),
                }
              : m,
          ),
        );

        // 流结束后立即保存（不等 300ms 防抖）
        saveMessages(messagesRef.current);

        abortControllerRef.current = null;
        setIsStreaming(false);
        streamingRef.current = false;
        setTimeout(processNext, 50);
      }
    })();
  }, [setAndSave, stopRecoveryPoll]);

  // ── 页面加载后断线恢复 ──
  useEffect(() => {
    const msgs = messagesRef.current;
    if (msgs.length === 0) return;

    const lastMsg = msgs[msgs.length - 1];
    if (lastMsg.role !== "assistant") return;

    const convId = conversationId.current;
    let cancelled = false;

    const updateLastAssistant = (fullText: string, model: string, provider: string) => {
      setAndSave((prev) => {
        const last = prev[prev.length - 1];
        if (!last || last.role !== "assistant") return prev;
        if (fullText.length <= last.content.length) return prev;
        return prev.map((m, i) =>
          i === prev.length - 1
            ? {
                ...m,
                content: fullText,
                model: model || m.model,
                provider: provider || m.provider,
              }
            : m,
        );
      });
    };

    const doRecover = async () => {
      try {
        const data = await recoverStream(convId);
        if (cancelled) return;
        if (!data.full_text && !data.active) return;

        if (data.full_text) {
          updateLastAssistant(data.full_text, data.model, data.provider);
        }

        if (data.active) {
          setIsStreaming(true);
          streamingRef.current = true;

          recoveryPollRef.current = setInterval(async () => {
            if (cancelled) return;
            try {
              const poll = await recoverStream(convId);
              if (cancelled) return;

              if (poll.full_text) {
                updateLastAssistant(poll.full_text, poll.model, poll.provider);
              }

              if (!poll.active) {
                if (recoveryPollRef.current) {
                  clearInterval(recoveryPollRef.current);
                  recoveryPollRef.current = null;
                }
                setIsStreaming(false);
                streamingRef.current = false;
              }
            } catch {
              if (recoveryPollRef.current) {
                clearInterval(recoveryPollRef.current);
                recoveryPollRef.current = null;
              }
              setIsStreaming(false);
              streamingRef.current = false;
            }
          }, 1000);
        }
      } catch {
        // 恢复失败，静默忽略
      }
    };

    doRecover();

    return () => {
      cancelled = true;
      if (recoveryPollRef.current) {
        clearInterval(recoveryPollRef.current);
        recoveryPollRef.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = useCallback(
    (text: string) => {
      if (!selectedModelRef.current) return;

      const userMsg: DirectChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: text,
      };
      setAndSave((prev) => [...prev, userMsg]);

      queueRef.current.push(text);

      if (!streamingRef.current) {
        processNext();
      }
    },
    [processNext, setAndSave],
  );

  const clearChat = useCallback(() => {
    stopRecoveryPoll();
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    queueRef.current = [];
    const emptyMessages: DirectChatMessage[] = [];
    setMessages(emptyMessages);
    messagesRef.current = emptyMessages;
    setPermissionRequest(null);
    permissionResolveRef.current = null;
    const newId = generateId();
    conversationId.current = newId;
    saveConvId(newId);
    localStorage.removeItem(LS_MESSAGES_KEY);
  }, [stopRecoveryPoll]);

  const stopStreaming = useCallback(() => {
    stopRecoveryPoll();
    abortControllerRef.current?.abort();
  }, [stopRecoveryPoll]);

  /** 加载历史会话：停止当前流 → 从 API 加载消息 → 更新状态 */
  const loadSession = useCallback(
    async (sessionId: string) => {
      // 停止当前流
      stopRecoveryPoll();
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
      queueRef.current = [];
      setIsStreaming(false);
      streamingRef.current = false;
      setPermissionRequest(null);
      permissionResolveRef.current = null;

      try {
        const msgs = await getSessionMessages(sessionId);
        const loaded: DirectChatMessage[] = msgs
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            id: m.id,
            role: m.role as "user" | "assistant",
            content: m.content,
            model: m.model ?? undefined,
          }));

        setMessages(loaded);
        messagesRef.current = loaded;
        saveMessages(loaded);

        conversationId.current = sessionId;
        saveConvId(sessionId);
      } catch (err) {
        console.error("加载会话失败:", err);
      }
    },
    [stopRecoveryPoll],
  );

  return {
    messages,
    isStreaming,
    selectedModel,
    setSelectedModel,
    sendMessage,
    clearChat,
    stopStreaming,
    permissionRequest,
    respondToPermission,
    loadSession,
    conversationId: conversationId.current,
  };
}
