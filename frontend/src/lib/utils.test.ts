/**
 * cn() 工具函数测试
 * 验证：类名合并、条件类名、Tailwind 冲突解决
 */

import { describe, it, expect } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  // ─── 基础合并 ───────────────────────────────────────────────────────────

  it("无参数时返回空字符串", () => {
    expect(cn()).toBe("");
  });

  it("合并多个类名", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("只传一个类名时原样返回", () => {
    expect(cn("text-sm")).toBe("text-sm");
  });

  // ─── 条件类名 ──────────────────────────────────────────────────────────

  it("忽略 false 值", () => {
    expect(cn("foo", false, "bar")).toBe("foo bar");
  });

  it("忽略 null 值", () => {
    expect(cn("foo", null, "bar")).toBe("foo bar");
  });

  it("忽略 undefined 值", () => {
    expect(cn("foo", undefined, "bar")).toBe("foo bar");
  });

  it("对象语法：true 的 key 被保留", () => {
    expect(cn({ "text-red-500": true, "text-blue-500": false })).toBe(
      "text-red-500",
    );
  });

  it("对象语法：全部为 false 时返回空字符串", () => {
    expect(cn({ hidden: false, visible: false })).toBe("");
  });

  // ─── 数组语法 ──────────────────────────────────────────────────────────

  it("处理类名数组", () => {
    expect(cn(["foo", "bar"])).toBe("foo bar");
  });

  it("处理嵌套数组", () => {
    expect(cn(["foo", ["bar", "baz"]])).toBe("foo bar baz");
  });

  // ─── Tailwind 冲突解决（tailwind-merge）───────────────────────────────

  it("内边距冲突：后者覆盖前者", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("文字颜色冲突：后者覆盖前者", () => {
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
  });

  it("不同维度的 Tailwind 类不产生冲突", () => {
    const result = cn("p-2", "m-4");
    expect(result).toContain("p-2");
    expect(result).toContain("m-4");
  });

  // ─── 混合场景 ──────────────────────────────────────────────────────────

  it("混合字符串、对象、数组", () => {
    const result = cn("base", { active: true, disabled: false }, ["extra"]);
    expect(result).toBe("base active extra");
  });

  it("组件变体场景：isActive 覆盖默认颜色", () => {
    const isActive = true;
    const result = cn("bg-gray-100", { "bg-blue-500": isActive });
    expect(result).toBe("bg-blue-500");
  });
});
