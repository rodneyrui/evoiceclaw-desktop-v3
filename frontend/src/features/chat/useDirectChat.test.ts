/**
 * useDirectChat Hook 测试
 * 验证：localStorage 持久化、初始状态加载、sendMessage、clearChat、setSelectedModel、respondToPermission
 *
 * 注意：streamChat 和 recoverStream 均通过 vi.mock 替换，测试只关注 Hook 逻辑本身
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ─── Mock directChatApi（在所有 import 之前，由 vitest 自动 hoist）─────────
vi.mock("./directChatApi", () => ({
  streamChat: vi.fn(),
  recoverStream: vi.fn(),
}));

import { useDirectChat, type DirectChatMessage } from "./useDirectChat";
import { streamChat, recoverStream } from "./directChatApi";

// ─── 常量（与 hook 内部保持一致）──────────────────────────────────────────
const LS_MESSAGES_KEY = "evoiceclaw_v3_messages";
const LS_CONV_ID_KEY = "evoiceclaw_v3_conv_id";
const LS_MODEL_KEY = "evoiceclaw_v3_selected_model";

// ─── beforeEach / afterEach ───────────────────────────────────────────────

beforeEach(() => {
  vi.useFakeTimers();

  // recoverStream 默认返回空（无活跃流），防止 mount 后的 recovery useEffect 干扰
  vi.mocked(recoverStream).mockResolvedValue({
    active: false,
    full_text: "",
    model: "",
    provider: "",
    chunk_count: 0,
  });

  // streamChat 默认返回空生成器
  vi.mocked(streamChat).mockImplementation(async function* () {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ─── 初始状态 ─────────────────────────────────────────────────────────────

describe("useDirectChat — 初始状态", () => {
  it("无 localStorage 时 messages 为空数组", () => {
    const { result } = renderHook(() => useDirectChat());
    expect(result.current.messages).toEqual([]);
  });

  it("无 localStorage 时 isStreaming 为 false", () => {
    const { result } = renderHook(() => useDirectChat());
    expect(result.current.isStreaming).toBe(false);
  });

  it('无 localStorage 时 selectedModel 默认为 "auto"', () => {
    const { result } = renderHook(() => useDirectChat());
    expect(result.current.selectedModel).toBe("auto");
  });

  it("无 localStorage 时 permissionRequest 为 null", () => {
    const { result } = renderHook(() => useDirectChat());
    expect(result.current.permissionRequest).toBeNull();
  });

  it("从 localStorage 恢复 messages", () => {
    const saved: DirectChatMessage[] = [
      { id: "u1", role: "user", content: "Hello" },
      { id: "a1", role: "assistant", content: "Hi there" },
    ];
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify(saved));

    const { result } = renderHook(() => useDirectChat());

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].content).toBe("Hello");
    expect(result.current.messages[1].content).toBe("Hi there");
  });

  it("恢复时将 toolPhase: active 修正为 done", () => {
    const saved: DirectChatMessage[] = [
      { id: "a1", role: "assistant", content: "Working...", toolPhase: "active" },
    ];
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify(saved));

    const { result } = renderHook(() => useDirectChat());

    expect(result.current.messages[0].toolPhase).toBe("done");
  });

  it("恢复时将 isUrlFetching 重置为 false", () => {
    const saved: DirectChatMessage[] = [
      { id: "a1", role: "assistant", content: "Fetching...", isUrlFetching: true },
    ];
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify(saved));

    const { result } = renderHook(() => useDirectChat());

    expect(result.current.messages[0].isUrlFetching).toBe(false);
  });

  it("从 localStorage 恢复 selectedModel", () => {
    localStorage.setItem(LS_MODEL_KEY, "deepseek/deepseek-chat");

    const { result } = renderHook(() => useDirectChat());

    expect(result.current.selectedModel).toBe("deepseek/deepseek-chat");
  });

  it("localStorage 中 messages 格式非法时降级为空数组", () => {
    localStorage.setItem(LS_MESSAGES_KEY, "not_valid_json{{");

    const { result } = renderHook(() => useDirectChat());

    expect(result.current.messages).toEqual([]);
  });

  it("localStorage 中 messages 是非数组类型时降级为空数组", () => {
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify({ not: "array" }));

    const { result } = renderHook(() => useDirectChat());

    expect(result.current.messages).toEqual([]);
  });
});

// ─── sendMessage ──────────────────────────────────────────────────────────

describe("useDirectChat — sendMessage", () => {
  it("立即将用户消息添加到 messages", async () => {
    const { result } = renderHook(() => useDirectChat());

    await act(async () => {
      result.current.sendMessage("Hello!");
    });

    const userMsgs = result.current.messages.filter((m) => m.role === "user");
    expect(userMsgs).toHaveLength(1);
    expect(userMsgs[0].content).toBe("Hello!");
  });

  it("用户消息的 role 为 user", async () => {
    const { result } = renderHook(() => useDirectChat());

    await act(async () => {
      result.current.sendMessage("Test");
    });

    expect(result.current.messages[0].role).toBe("user");
  });

  it("用户消息的 id 有预期格式且非空", async () => {
    // 注意：vi.useFakeTimers() 冻结了 Date.now()，
    // 不在同一 tick 内连续测试多条消息 id 唯一性，改为验证格式
    const { result } = renderHook(() => useDirectChat());

    await act(async () => {
      result.current.sendMessage("Hello!");
    });

    const userMsgs = result.current.messages.filter((m) => m.role === "user");
    expect(userMsgs[0].id).toBeTruthy();
    expect(userMsgs[0].id).toMatch(/^user-/);
  });

  it("selectedModel 为空字符串时不添加消息", async () => {
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.setSelectedModel("");
    });

    await act(async () => {
      result.current.sendMessage("Hello!");
    });

    // selectedModelRef 为空，sendMessage 立即返回
    expect(result.current.messages).toHaveLength(0);
  });
});

// ─── clearChat ────────────────────────────────────────────────────────────

describe("useDirectChat — clearChat", () => {
  it("清空所有 messages", () => {
    const saved: DirectChatMessage[] = [
      { id: "u1", role: "user", content: "Hello" },
      { id: "a1", role: "assistant", content: "Hi" },
    ];
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify(saved));
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.clearChat();
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("从 localStorage 删除 messages 键", () => {
    localStorage.setItem(
      LS_MESSAGES_KEY,
      JSON.stringify([{ id: "u1", role: "user", content: "test" }]),
    );
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.clearChat();
    });

    expect(localStorage.getItem(LS_MESSAGES_KEY)).toBeNull();
  });

  it("生成新的 conversation ID", () => {
    const oldId = "old-conv-id";
    localStorage.setItem(LS_CONV_ID_KEY, oldId);
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.clearChat();
    });

    const newId = localStorage.getItem(LS_CONV_ID_KEY);
    expect(newId).not.toBe(oldId);
    expect(newId).toBeTruthy();
  });

  it("clearChat 后 messages 仍为空（不被 debounce 恢复）", () => {
    localStorage.setItem(
      LS_MESSAGES_KEY,
      JSON.stringify([{ id: "u1", role: "user", content: "test" }]),
    );
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.clearChat();
      vi.runAllTimers(); // 触发所有 setTimeout
    });

    expect(result.current.messages).toHaveLength(0);
  });
});

// ─── setSelectedModel ─────────────────────────────────────────────────────

describe("useDirectChat — setSelectedModel", () => {
  it("更新 selectedModel 状态", () => {
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.setSelectedModel("claude-sonnet-4-6");
    });

    expect(result.current.selectedModel).toBe("claude-sonnet-4-6");
  });

  it("持久化到 localStorage", () => {
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.setSelectedModel("gpt-4o-mini");
    });

    expect(localStorage.getItem(LS_MODEL_KEY)).toBe("gpt-4o-mini");
  });

  it("切换多次模型时保留最后一个", () => {
    const { result } = renderHook(() => useDirectChat());

    act(() => {
      result.current.setSelectedModel("model-a");
      result.current.setSelectedModel("model-b");
      result.current.setSelectedModel("model-c");
    });

    expect(result.current.selectedModel).toBe("model-c");
    expect(localStorage.getItem(LS_MODEL_KEY)).toBe("model-c");
  });
});

// ─── respondToPermission ──────────────────────────────────────────────────

describe("useDirectChat — respondToPermission", () => {
  it("调用后 permissionRequest 变为 null", () => {
    const { result } = renderHook(() => useDirectChat());

    // permissionRequest 初始为 null，即使在没有弹出请求的情况下调用也不应崩溃
    act(() => {
      result.current.respondToPermission(true);
    });

    expect(result.current.permissionRequest).toBeNull();
  });

  it("连续调用不崩溃", () => {
    const { result } = renderHook(() => useDirectChat());

    expect(() => {
      act(() => {
        result.current.respondToPermission(false);
        result.current.respondToPermission(true);
      });
    }).not.toThrow();
  });
});

// ─── localStorage 防抖持久化 ──────────────────────────────────────────────

describe("useDirectChat — messages 防抖持久化", () => {
  it("300ms 防抖后自动保存 messages", async () => {
    const { result } = renderHook(() => useDirectChat());

    await act(async () => {
      result.current.sendMessage("Persist me");
    });

    // 尚未到 300ms，localStorage 中可能没有新消息（取决于 mock 时机）
    // 推进 300ms 触发防抖
    act(() => {
      vi.advanceTimersByTime(300);
    });

    const saved = localStorage.getItem(LS_MESSAGES_KEY);
    expect(saved).not.toBeNull();

    const parsed: DirectChatMessage[] = JSON.parse(saved!);
    const userMsgs = parsed.filter((m) => m.role === "user");
    expect(userMsgs.length).toBeGreaterThanOrEqual(1);
    expect(userMsgs[0].content).toBe("Persist me");
  });

  it("messages 为空时不写入 localStorage", () => {
    const { result } = renderHook(() => useDirectChat());

    // 初始 messages 为空，不应触发写入
    act(() => {
      vi.advanceTimersByTime(300);
    });

    // setup.ts 中 beforeEach 清空了 localStorage，这里应仍为 null
    expect(localStorage.getItem(LS_MESSAGES_KEY)).toBeNull();
  });
});

// ─── stopStreaming ─────────────────────────────────────────────────────────

describe("useDirectChat — stopStreaming", () => {
  it("调用 stopStreaming 不崩溃（非流式状态下）", () => {
    const { result } = renderHook(() => useDirectChat());

    expect(() => {
      act(() => {
        result.current.stopStreaming();
      });
    }).not.toThrow();
  });
});
