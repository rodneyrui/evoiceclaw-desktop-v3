/**
 * 审计日志页面：查询 + 过滤 + 列表展示
 */

import { useState, useEffect, useCallback } from "react";
import { FileText, Search, RefreshCw, Loader2 } from "lucide-react";
import { apiGet } from "@/shared/api/client";
import { useTranslation } from "react-i18next";

interface AuditEntry {
  id: string;
  trace_id: string;
  timestamp: string;
  level: string;
  component: string;
  action: string;
  detail: string;
  duration_ms: number | null;
  user_id: string;
}

interface AuditResponse {
  items: AuditEntry[];
  total: number;
}

const LEVEL_COLORS: Record<string, string> = {
  INFO: "text-blue-500",
  WARN: "text-yellow-500",
  ERROR: "text-red-500",
};

const COMPONENTS = ["shell", "gatekeeper", "skill_service"];

export default function AuditPage() {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [component, setComponent] = useState("");
  const [level, setLevel] = useState("");
  const [traceId, setTraceId] = useState("");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (component) params.set("component", component);
      if (level) params.set("level", level);
      if (traceId.trim()) params.set("trace_id", traceId.trim());
      params.set("limit", "200");

      const qs = params.toString();
      const data = await apiGet<AuditResponse>(`/audit${qs ? `?${qs}` : ""}`);
      setEntries(data.items);
    } catch {
      // 静默
    } finally {
      setLoading(false);
    }
  }, [component, level, traceId]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-5xl mx-auto space-y-4">
        {/* 标题 */}
        <div>
          <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
            <FileText className="w-5 h-5 text-primary" />
            {t("audit.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t("audit.description")}</p>
        </div>

        {/* 过滤条件 */}
        <div className="flex items-center gap-3 flex-wrap">
          <select
            value={component}
            onChange={(e) => setComponent(e.target.value)}
            className="bg-card border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none"
          >
            <option value="">{t("audit.allComponents")}</option>
            {COMPONENTS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="bg-card border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none"
          >
            <option value="">{t("audit.allLevels")}</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
          </select>

          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              value={traceId}
              onChange={(e) => setTraceId(e.target.value)}
              placeholder={t("audit.filterTraceId")}
              className="w-full bg-card border border-border rounded-lg pl-9 pr-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none"
            />
          </div>

          <button
            type="button"
            onClick={fetchLogs}
            className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title={t("common.refresh")}
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {/* 日志列表 */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <FileText className="w-12 h-12 text-muted-foreground/30 mb-3" />
            <p className="text-muted-foreground text-sm">{t("audit.noLogs")}</p>
            <p className="text-muted-foreground/60 text-xs mt-1">{t("audit.noLogsHint")}</p>
          </div>
        ) : (
          <div className="border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 border-b border-border">
                <tr>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">时间</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">级别</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">组件</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">动作</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Trace</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">详情</th>
                  <th className="text-right px-3 py-2 font-medium text-muted-foreground">耗时</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id} className="border-b border-border last:border-b-0 hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {entry.timestamp.replace("T", " ").replace("Z", "")}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-xs font-medium ${LEVEL_COLORS[entry.level] || "text-foreground"}`}>
                        {entry.level}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs font-mono text-foreground">{entry.component}</td>
                    <td className="px-3 py-2 text-xs font-medium text-foreground">{entry.action}</td>
                    <td className="px-3 py-2 text-xs font-mono text-muted-foreground">{entry.trace_id}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground max-w-[300px] truncate" title={entry.detail}>
                      {entry.detail}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground text-right whitespace-nowrap">
                      {entry.duration_ms != null ? `${entry.duration_ms}ms` : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
