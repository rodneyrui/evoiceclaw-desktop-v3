/**
 * 直聊 API 客户端：支持 SSE 流式接收 LLM 响应
 *
 * 适配 V3 后端 API（无鉴权，tool_call.name 替代 function_name，
 * 新增 url_detected 类型，移除 verification/correction/approval_request）。
 */

import { apiGet, apiFetch } from "@/shared/api/client";

/** 可用模型信息 */
export interface ChatModel {
  id: string; // 如 "deepseek/deepseek-chat" 或 "cli:claude"
  name: string; // 如 "DeepSeek Chat"
  provider: string; // 如 "deepseek" 或 "cli"
  type: "api" | "cli";
  mode: string; // "fast" | "analysis"
}

/** SSE 流式块 */
export interface StreamChunk {
  type:
    | "text"
    | "thinking"
    | "error"
    | "end"
    | "tool_call"
    | "tool_result"
    | "url_detected"
    | "permission_request"
    | "browser_opened";
  content: string;
  model?: string;
  provider?: string;
  usage?: Record<string, number>;
  tool_call?: {
    id: string;
    name: string;
    arguments: Record<string, unknown>;
  };
}

/** 获取可用模型列表 */
export async function getAvailableModels(): Promise<ChatModel[]> {
  return apiGet<ChatModel[]>("/chat/models");
}

/** 断线恢复：获取已缓冲的流式内容 */
export interface StreamRecovery {
  active: boolean;
  full_text: string;
  model: string;
  provider: string;
  chunk_count: number;
}

export async function recoverStream(conversationId: string): Promise<StreamRecovery> {
  try {
    const res = await fetch(`/api/v1/chat/${conversationId}/recover`);
    if (!res.ok) {
      return { active: false, full_text: "", model: "", provider: "", chunk_count: 0 };
    }
    return await res.json();
  } catch {
    return { active: false, full_text: "", model: "", provider: "", chunk_count: 0 };
  }
}

/** 流式发送消息并逐块返回 LLM 响应 */
export async function* streamChat(params: {
  message: string;
  model: string;
  conversation_id?: string;
  system_prompt?: string;
  signal?: AbortSignal;
}): AsyncGenerator<StreamChunk, void, undefined> {
  const { signal, ...body } = params;
  const res = await fetch("/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }

  if (!res.body) {
    throw new Error("响应无 body");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const chunk = JSON.parse(line.slice(6)) as StreamChunk;
          yield chunk;
        } catch {
          // 忽略解析错误
        }
      }
    }
  }
}

/** 会话信息 */
export interface SessionInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

/** 会话消息 */
export interface SessionMessage {
  id: string;
  role: string;
  content: string;
  model: string | null;
  created_at: string;
}

/** 获取对话列表 */
export async function getSessions(limit = 50, offset = 0): Promise<SessionInfo[]> {
  return apiGet<SessionInfo[]>(`/sessions?limit=${limit}&offset=${offset}`);
}

/** 获取指定会话的历史消息 */
export async function getSessionMessages(sessionId: string, limit = 200): Promise<SessionMessage[]> {
  return apiGet<SessionMessage[]>(`/sessions/${sessionId}/messages?limit=${limit}`);
}

/** 删除指定会话 */
export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/sessions/${sessionId}`, { method: "DELETE" });
}
