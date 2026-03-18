/**
 * 主题管理 Hook：支持 light / dark / system 三种模式
 *
 * - 持久化到 localStorage("evoiceclaw_theme")
 * - system 模式下监听 prefers-color-scheme 媒体查询
 * - 在 <html> 元素上添加/移除 .dark 类
 */

import { useState, useEffect, useCallback } from "react";

export type Theme = "light" | "dark" | "system";

const LS_KEY = "evoiceclaw_theme";

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function loadTheme(): Theme {
  try {
    const saved = localStorage.getItem(LS_KEY);
    if (saved === "light" || saved === "dark" || saved === "system")
      return saved;
  } catch {
    // ignore
  }
  return "system";
}

function applyTheme(resolved: "light" | "dark") {
  const root = document.documentElement;
  if (resolved === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(loadTheme);
  const [resolved, setResolved] = useState<"light" | "dark">(
    () =>
      (loadTheme() === "system" ? getSystemTheme() : loadTheme()) as
        | "light"
        | "dark",
  );

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem(LS_KEY, t);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    const r = theme === "system" ? getSystemTheme() : theme;
    setResolved(r);
    applyTheme(r);
  }, [theme]);

  // 监听系统主题变化（仅 system 模式下生效）
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      const r = e.matches ? "dark" : "light";
      setResolved(r);
      applyTheme(r);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  return { theme, setTheme, resolved };
}
