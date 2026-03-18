import { lazy } from "react";
import { Routes, Route } from "react-router-dom";
import { Layout } from "@/shared/components/Layout";

const ChatPage = lazy(() => import("@/features/chat/ChatPage"));
const SkillsPage = lazy(() => import("@/features/skills/SkillsPage"));
const MemoryPage = lazy(() => import("@/features/memory/MemoryPage"));
const WorkspacePage = lazy(() => import("@/features/workspace/WorkspacePage"));
const AuditPage = lazy(() => import("@/features/audit/AuditPage"));
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage"));

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/skills" element={<SkillsPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
