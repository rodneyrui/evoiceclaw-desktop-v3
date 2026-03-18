/**
 * API 客户端测试
 * 验证：apiFetch / apiGet / apiPost 的请求构造、响应解析、错误处理
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, apiGet, apiPost } from "./client";

// ─── 工具：构造 mock fetch response ────────────────────────────────────────

function mockOkResponse(data: unknown) {
  return {
    ok: true,
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

function mockErrorResponse(status: number, statusText: string, body = "") {
  return {
    ok: false,
    status,
    statusText,
    text: async () => body,
    json: async () => { throw new Error("should not parse error body"); },
  };
}

// ─── apiFetch ──────────────────────────────────────────────────────────────

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("向 /api/v1 + path 发送请求", async () => {
    vi.mocked(fetch).mockResolvedValue(mockOkResponse({}) as Response);

    await apiFetch("/test");

    expect(fetch).toHaveBeenCalledWith("/api/v1/test", expect.any(Object));
  });

  it("成功时返回解析后的 JSON", async () => {
    const data = { id: 1, name: "test" };
    vi.mocked(fetch).mockResolvedValue(mockOkResponse(data) as Response);

    const result = await apiFetch<typeof data>("/items");

    expect(result).toEqual(data);
  });

  it("请求头包含 Content-Type: application/json", async () => {
    vi.mocked(fetch).mockResolvedValue(mockOkResponse({}) as Response);

    await apiFetch("/test");

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect((options.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
  });

  it("非 OK 响应且有错误文本时 throw 该文本", async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockErrorResponse(404, "Not Found", "Resource not found") as unknown as Response,
    );

    await expect(apiFetch("/missing")).rejects.toThrow("Resource not found");
  });

  it("非 OK 响应且错误文本为空时 throw 含状态码的默认信息", async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockErrorResponse(500, "Internal Server Error", "") as unknown as Response,
    );

    await expect(apiFetch("/broken")).rejects.toThrow("API Error: 500");
  });

  it("传入自定义请求头时，自定义头包含在最终请求中", async () => {
    // 注意：apiFetch 用 ...options 展开覆盖了 headers 属性，
    // 因此自定义头会替换默认的 Content-Type 头（这是当前实现的实际行为）
    vi.mocked(fetch).mockResolvedValue(mockOkResponse({}) as Response);

    await apiFetch("/test", {
      headers: { "X-Custom-Header": "my-value" },
    });

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = options.headers as Record<string, string>;
    expect(headers["X-Custom-Header"]).toBe("my-value");
  });
});

// ─── apiGet ────────────────────────────────────────────────────────────────

describe("apiGet", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockOkResponse([]) as Response));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("发送 GET 请求", async () => {
    await apiGet("/items");

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(options.method).toBe("GET");
  });

  it("返回服务端数据", async () => {
    const items = [{ id: 1 }, { id: 2 }];
    vi.mocked(fetch).mockResolvedValue(mockOkResponse(items) as Response);

    const result = await apiGet<typeof items>("/items");

    expect(result).toEqual(items);
  });
});

// ─── apiPost ───────────────────────────────────────────────────────────────

describe("apiPost", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockOkResponse({ created: true }) as Response),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("发送 POST 请求", async () => {
    await apiPost("/items", { name: "test" });

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(options.method).toBe("POST");
  });

  it("将 body 序列化为 JSON 字符串", async () => {
    const payload = { name: "test", value: 42 };
    await apiPost("/items", payload);

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(options.body).toBe(JSON.stringify(payload));
  });

  it("不传 body 时 body 为 undefined", async () => {
    await apiPost("/items");

    const options = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(options.body).toBeUndefined();
  });

  it("返回服务端响应数据", async () => {
    const response = { id: 99, created: true };
    vi.mocked(fetch).mockResolvedValue(mockOkResponse(response) as Response);

    const result = await apiPost<typeof response>("/items", {});

    expect(result).toEqual(response);
  });
});
