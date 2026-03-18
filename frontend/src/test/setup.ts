/**
 * Vitest 全局 setup 文件
 * 在每个测试文件之前执行一次
 */

import "@testing-library/jest-dom";
import { vi, beforeEach, afterEach } from "vitest";

// ─── localStorage mock ─────────────────────────────────────────────────────
// jsdom 自带 localStorage，但在测试间需要能清空。
// 提供一个干净的 in-memory 实现以保证测试隔离。
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = String(value);
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    get length() {
      return Object.keys(store).length;
    },
    key: (index: number) => Object.keys(store)[index] ?? null,
  };
})();

Object.defineProperty(window, "localStorage", {
  value: localStorageMock,
  writable: true,
});

// ─── matchMedia mock ───────────────────────────────────────────────────────
// jsdom 不实现 matchMedia，手动提供默认（浅色）mock
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,        // 默认：非暗色
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated 但部分库仍调用
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ─── 每个测试前清理 ────────────────────────────────────────────────────────
beforeEach(() => {
  localStorageMock.clear();
  document.documentElement.classList.remove("dark");
});

afterEach(() => {
  vi.restoreAllMocks();
});
