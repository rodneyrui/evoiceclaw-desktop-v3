/**
 * directChatApi 测试
 * 验证：getAvailableModels、recoverStream、streamChat (SSE 解析)
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import {
  getAvailableModels,
  recoverStream,
  streamChat,
  type StreamChunk,
} from "./directChatApi";

// ─── SSE 流工具 ────────────────────────────────────────────────────────────

/**
 * 将 SSE 文本列表组合成可读流（模拟网络分片）
 */
function createSSEStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

/**
 * 将 StreamChunk 序列化为 SSE data 行
 */
function sseLines(chunks: StreamChunk[]): string {
  return chunks.map((c) => `data: ${JSON.stringify(c)}\n`).join("");
}

/**
 * 收集异步生成器的所有值
 */
async function collectAll<T>(
  gen: AsyncGenerator<T>,
): Promise<T[]> {
  const items: T[] = [];
  for await (const item of gen) {
    items.push(item);
  }
  return items;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ─── getAvailableModels ────────────────────────────────────────────────────

describe("getAvailableModels", () => {
  it("调用 GET /api/v1/chat/models", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", mockFetch);

    await getAvailableModels();

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/chat/models",
      expect.any(Object),
    );
  });

  it("返回模型列表", async () => {
    const models = [
      { id: "gpt-4o", name: "GPT-4o", provider: "openai", type: "api", mode: "fast" },
      { id: "deepseek/deepseek-chat", name: "DeepSeek Chat", provider: "deepseek", type: "api", mode: "fast" },
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => models,
    }));

    const result = await getAvailableModels();

    expect(result).toEqual(models);
    expect(result).toHaveLength(2);
  });

  it("API 报错时 throw Error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "Server error",
    }));

    await expect(getAvailableModels()).rejects.toThrow();
  });
});

// ─── recoverStream ─────────────────────────────────────────────────────────

describe("recoverStream", () => {
  it("成功时返回恢复数据", async () => {
    const data = {
      active: false,
      full_text: "Hello world",
      model: "gpt-4o",
      provider: "openai",
      chunk_count: 5,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => data,
    }));

    const result = await recoverStream("conv-123");

    expect(result).toEqual(data);
  });

  it("向 /api/v1/chat/{conversationId}/recover 发送请求", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ active: false, full_text: "", model: "", provider: "", chunk_count: 0 }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await recoverStream("my-conv-id");

    expect(mockFetch.mock.calls[0][0]).toBe("/api/v1/chat/my-conv-id/recover");
  });

  it("响应非 OK 时返回空结构（不 throw）", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
    }));

    const result = await recoverStream("gone-conv");

    expect(result.active).toBe(false);
    expect(result.full_text).toBe("");
    expect(result.chunk_count).toBe(0);
  });

  it("网络错误时返回空结构（不 throw）", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));

    const result = await recoverStream("offline-conv");

    expect(result.active).toBe(false);
    expect(result.full_text).toBe("");
    expect(result.model).toBe("");
  });
});

// ─── streamChat ────────────────────────────────────────────────────────────

describe("streamChat — 请求构造", () => {
  it("向 POST /api/v1/chat 发送请求", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([""]),
    });
    vi.stubGlobal("fetch", mockFetch);

    await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    expect(mockFetch.mock.calls[0][0]).toBe("/api/v1/chat");
    expect(mockFetch.mock.calls[0][1].method).toBe("POST");
  });

  it("请求体包含 message、model、conversation_id", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([""]),
    });
    vi.stubGlobal("fetch", mockFetch);

    await collectAll(
      streamChat({ message: "test msg", model: "deepseek/deepseek-chat", conversation_id: "conv-1" }),
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.message).toBe("test msg");
    expect(body.model).toBe("deepseek/deepseek-chat");
    expect(body.conversation_id).toBe("conv-1");
  });

  it("signal 不被序列化到 body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([""]),
    });
    vi.stubGlobal("fetch", mockFetch);

    const controller = new AbortController();
    await collectAll(
      streamChat({ message: "hi", model: "gpt-4o", signal: controller.signal }),
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.signal).toBeUndefined();
    // signal 应该被传到 fetch options，而不是 body
    expect(mockFetch.mock.calls[0][1].signal).toBe(controller.signal);
  });
});

describe("streamChat — SSE 解析", () => {
  it("正确解析多个 data 行", async () => {
    const chunks: StreamChunk[] = [
      { type: "text", content: "Hello" },
      { type: "text", content: " World" },
      { type: "end", content: "" },
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([sseLines(chunks)]),
    }));

    const received = await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    expect(received).toHaveLength(3);
    expect(received[0]).toEqual({ type: "text", content: "Hello" });
    expect(received[1]).toEqual({ type: "text", content: " World" });
    expect(received[2]).toEqual({ type: "end", content: "" });
  });

  it("解析包含 model 和 provider 字段的 chunk", async () => {
    const chunk: StreamChunk = {
      type: "text",
      content: "Hi",
      model: "gpt-4o",
      provider: "openai",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([sseLines([chunk])]),
    }));

    const received = await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    expect(received[0].model).toBe("gpt-4o");
    expect(received[0].provider).toBe("openai");
  });

  it("解析 tool_call 类型 chunk", async () => {
    const chunk: StreamChunk = {
      type: "tool_call",
      content: "",
      tool_call: { id: "tc-1", name: "web_search", arguments: { query: "test" } },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([sseLines([chunk])]),
    }));

    const received = await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    expect(received[0].type).toBe("tool_call");
    expect(received[0].tool_call?.name).toBe("web_search");
    expect(received[0].tool_call?.arguments).toEqual({ query: "test" });
  });

  it("忽略非 data: 开头的行（如空行和 event: 行）", async () => {
    const sseText =
      "event: message\n" +
      'data: {"type":"text","content":"Hi"}\n' +
      "\n" +
      'data: {"type":"end","content":""}\n';

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([sseText]),
    }));

    const received = await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    // 只有两个 data 行被 yield
    expect(received).toHaveLength(2);
    expect(received[0].content).toBe("Hi");
  });

  it("跳过 JSON 解析失败的 data 行，继续处理后续行", async () => {
    const sseText =
      "data: invalid_json_here\n" +
      'data: {"type":"text","content":"valid"}\n';

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([sseText]),
    }));

    const received = await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    expect(received).toHaveLength(1);
    expect(received[0].content).toBe("valid");
  });

  it("处理跨网络分片的 SSE 数据", async () => {
    // 模拟两次网络分片，第一片只有半行
    const part1 = 'data: {"type":"text","cont';
    const part2 = 'ent":"split"}\n';

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: createSSEStream([part1, part2]),
    }));

    const received = await collectAll(streamChat({ message: "hi", model: "gpt-4o" }));

    expect(received).toHaveLength(1);
    expect(received[0].content).toBe("split");
  });
});

describe("streamChat — 错误处理", () => {
  it("HTTP 非 OK 时 throw 包含响应文本的错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "Internal server error",
    }));

    await expect(
      collectAll(streamChat({ message: "hi", model: "gpt-4o" })),
    ).rejects.toThrow("Internal server error");
  });

  it("响应无 body 时 throw", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: null,
    }));

    await expect(
      collectAll(streamChat({ message: "hi", model: "gpt-4o" })),
    ).rejects.toThrow("响应无 body");
  });

  it("HTTP 500 且无响应文本时 throw 包含状态码", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => "",
    }));

    await expect(
      collectAll(streamChat({ message: "hi", model: "gpt-4o" })),
    ).rejects.toThrow("HTTP 503");
  });
});
