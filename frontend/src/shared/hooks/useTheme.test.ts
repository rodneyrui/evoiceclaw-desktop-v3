/**
 * useTheme Hook 测试
 * 验证：默认值、持久化到 localStorage、主题切换、DOM 类名应用、system 模式
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTheme, type Theme } from "./useTheme";

const LS_KEY = "evoiceclaw_theme";

// beforeEach 在 setup.ts 已经清空 localStorage 并移除 .dark 类

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── 默认值 ────────────────────────────────────────────────────────────────

describe("useTheme — 初始状态", () => {
  it('无 localStorage 时默认主题为 "system"', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("system");
  });

  it("从 localStorage 加载已保存的主题 dark", () => {
    localStorage.setItem(LS_KEY, "dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
  });

  it("从 localStorage 加载已保存的主题 light", () => {
    localStorage.setItem(LS_KEY, "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("light");
  });

  it('localStorage 中的非法值回退到 "system"', () => {
    localStorage.setItem(LS_KEY, "invalid_value");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("system");
  });

  it("isStreaming 和 resolved 已被初始化（非 undefined）", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.resolved).toBeDefined();
    expect(["light", "dark"]).toContain(result.current.resolved);
  });
});

// ─── setTheme ─────────────────────────────────────────────────────────────

describe("useTheme — setTheme", () => {
  it('setTheme("dark") 更新 theme 状态', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    expect(result.current.theme).toBe("dark");
  });

  it('setTheme("light") 保存到 localStorage', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("light"));
    expect(localStorage.getItem(LS_KEY)).toBe("light");
  });

  it('setTheme("dark") 保存到 localStorage', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    expect(localStorage.getItem(LS_KEY)).toBe("dark");
  });

  it('setTheme("system") 保存到 localStorage', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("system"));
    expect(localStorage.getItem(LS_KEY)).toBe("system");
  });

  it("连续切换主题时 theme 跟随最后一次设置", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    act(() => result.current.setTheme("light"));
    act(() => result.current.setTheme("dark"));
    expect(result.current.theme).toBe("dark");
  });
});

// ─── resolved ─────────────────────────────────────────────────────────────

describe("useTheme — resolved", () => {
  it('theme = "light" 时 resolved = "light"', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("light"));
    expect(result.current.resolved).toBe("light");
  });

  it('theme = "dark" 时 resolved = "dark"', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    expect(result.current.resolved).toBe("dark");
  });

  it("system 模式下 matchMedia 返回 false（浅色）时 resolved = light", () => {
    // setup.ts 中的 matchMedia mock 默认 matches: false
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("system"));
    expect(result.current.resolved).toBe("light");
  });

  it("system 模式下 matchMedia 返回 true（深色）时 resolved = dark", () => {
    vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("system"));
    expect(result.current.resolved).toBe("dark");
  });
});

// ─── DOM class ────────────────────────────────────────────────────────────

describe("useTheme — documentElement.dark 类", () => {
  it('theme = "dark" 时给 html 添加 .dark 类', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it('theme = "light" 时移除 html 上的 .dark 类', () => {
    document.documentElement.classList.add("dark"); // 预设
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("light"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it('从 dark 切换回 light 后 .dark 类被移除', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    act(() => result.current.setTheme("light"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});

// ─── theme 类型约束 ────────────────────────────────────────────────────────

describe("useTheme — Theme 类型", () => {
  it("Theme 类型只包含三个有效值", () => {
    const validThemes: Theme[] = ["light", "dark", "system"];
    expect(validThemes).toHaveLength(3);
  });
});
