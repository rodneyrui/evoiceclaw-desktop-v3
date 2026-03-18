/**
 * 全局布局：侧边栏导航 + 主内容区
 *
 * V3 简化版：仅保留对话入口（后续 Phase 逐步增加 Skills、Memory 等页面）
 */

import { Suspense } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  MessageSquare,
  Puzzle,
  Brain,
  FolderKanban,
  FileText,
  Settings,
  Loader2,
  Sun,
  Moon,
} from "lucide-react";
import { useTheme } from "@/shared/hooks/useTheme";
import { useTranslation } from "react-i18next";
import { LS_LANG_KEY } from "@/i18n";

export function Layout() {
  const location = useLocation();
  const { resolved, setTheme } = useTheme();
  const { t, i18n } = useTranslation();

  const navItems = [
    { icon: MessageSquare, label: t("layout.nav.chat"), path: "/" },
    { icon: Puzzle, label: t("layout.nav.skills"), path: "/skills" },
    { icon: Brain, label: t("layout.nav.memory"), path: "/memory" },
    {
      icon: FolderKanban,
      label: t("layout.nav.workspace"),
      path: "/workspace",
    },
    { icon: FileText, label: t("layout.nav.audit"), path: "/audit" },
    { icon: Settings, label: t("layout.nav.settings"), path: "/settings" },
  ];

  return (
    <div className="flex min-h-screen bg-background text-foreground font-sans">
      <div className="h-screen w-[200px] bg-sidebar border-r border-border flex flex-col fixed left-0 top-0 z-50">
        <div className="p-6 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <span className="text-sm font-bold text-primary">AI</span>
          </div>
          <div>
            <span className="font-bold text-sm tracking-tight text-foreground">
              eVoiceClaw
            </span>
            <span className="block text-[10px] text-muted-foreground">
              AI OS v3
            </span>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map((item) => {
            const isActive =
              location.pathname === item.path ||
              (item.path !== "/" && location.pathname.startsWith(item.path));
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="p-3 mt-auto space-y-1">
          <button
            type="button"
            onClick={() => {
              const next =
                i18n.language === "zh-CN" ? "en-US" : "zh-CN";
              i18n.changeLanguage(next);
              try {
                localStorage.setItem(LS_LANG_KEY, next);
              } catch {
                /* ignore */
              }
            }}
            className="flex items-center gap-3 px-3 py-2.5 w-full rounded-lg text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title={t("layout.language")}
          >
            <span className="w-4 h-4 flex items-center justify-center text-xs font-bold">
              {i18n.language === "zh-CN" ? "EN" : "中"}
            </span>
            {i18n.language === "zh-CN" ? "English" : "中文"}
          </button>
          <button
            type="button"
            onClick={() =>
              setTheme(resolved === "dark" ? "light" : "dark")
            }
            className="flex items-center gap-3 px-3 py-2.5 w-full rounded-lg text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title={
              resolved === "dark"
                ? t("layout.lightMode")
                : t("layout.darkMode")
            }
          >
            {resolved === "dark" ? (
              <Sun className="w-4 h-4" />
            ) : (
              <Moon className="w-4 h-4" />
            )}
            {resolved === "dark"
              ? t("layout.lightMode")
              : t("layout.darkMode")}
          </button>
        </div>
      </div>

      <main className="flex-1 ml-[200px] relative overflow-hidden flex flex-col h-screen">
        <Suspense
          fallback={
            <div className="flex-1 flex items-center justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
