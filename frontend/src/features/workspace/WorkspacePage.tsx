/**
 * 工作区管理页面：列表 + 注册 + 激活 + 注销 + 文件树
 */

import { useState, useEffect, useCallback } from "react";
import {
  FolderOpen, Plus, Trash2, CheckCircle2, Circle,
  ChevronDown, ChevronUp, Loader2, Terminal, Globe,
} from "lucide-react";
import { apiGet, apiPost, apiFetch } from "@/shared/api/client";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

interface Workspace {
  id: string;
  name: string;
  path: string;
  description: string;
  created_at: string;
  last_accessed: string;
  active: boolean;
  shell_enabled: boolean;
  shell_level: string;
  network_whitelist: string[];
  env_vars: Record<string, string>;
}

export default function WorkspacePage() {
  const { t } = useTranslation();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [regName, setRegName] = useState("");
  const [regPath, setRegPath] = useState("");
  const [regDesc, setRegDesc] = useState("");
  const [registering, setRegistering] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [treeData, setTreeData] = useState<Record<string, string>>({});
  const [treeLoading, setTreeLoading] = useState<string | null>(null);

  const fetchWorkspaces = useCallback(async () => {
    try {
      const list = await apiGet<Workspace[]>("/workspaces");
      setWorkspaces(list);
    } catch (err) {
      toast.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const handleRegister = async () => {
    if (!regName.trim() || !regPath.trim()) return;
    setRegistering(true);
    try {
      await apiPost("/workspaces", {
        name: regName.trim(),
        path: regPath.trim(),
        description: regDesc.trim(),
      });
      toast.success(`工作区 "${regName}" 注册成功`);
      setRegName(""); setRegPath(""); setRegDesc("");
      setShowRegister(false);
      fetchWorkspaces();
    } catch (err) {
      toast.error(`注册失败: ${err}`);
    } finally {
      setRegistering(false);
    }
  };

  const handleActivate = async (ws: Workspace) => {
    if (ws.active) return;
    setActivating(ws.id);
    try {
      await apiPost(`/workspaces/${ws.id}/activate`);
      toast.success(`已激活工作区 "${ws.name}"`);
      fetchWorkspaces();
    } catch (err) {
      toast.error(`激活失败: ${err}`);
    } finally {
      setActivating(null);
    }
  };

  const handleUnregister = async (ws: Workspace) => {
    if (!confirm(t("workspace.confirmUnregister"))) return;
    try {
      await apiFetch(`/workspaces/${ws.id}`, { method: "DELETE" });
      toast.success(`工作区 "${ws.name}" 已注销`);
      fetchWorkspaces();
    } catch (err) {
      toast.error(`注销失败: ${err}`);
    }
  };

  const handleViewTree = async (ws: Workspace) => {
    if (treeData[ws.id]) return;
    setTreeLoading(ws.id);
    try {
      const res = await apiGet<{ tree: string }>(`/workspaces/${ws.id}/tree`);
      setTreeData((prev) => ({ ...prev, [ws.id]: res.tree }));
    } catch (err) {
      toast.error(`获取文件树失败: ${err}`);
    } finally {
      setTreeLoading(null);
    }
  };

  const toggleExpand = (id: string) => {
    setExpanded(expanded === id ? null : id);
  };

  const formatDate = (iso: string) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("zh-CN", {
        month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* 标题 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
              <FolderOpen className="w-5 h-5 text-primary" />
              {t("workspace.title")}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">{t("workspace.description")}</p>
          </div>
          <button
            type="button"
            onClick={() => setShowRegister(!showRegister)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t("workspace.register")}
          </button>
        </div>

        {/* 注册表单 */}
        {showRegister && (
          <div className="bg-card border border-border rounded-xl p-4 space-y-3">
            <input
              value={regName}
              onChange={(e) => setRegName(e.target.value)}
              placeholder={t("workspace.namePlaceholder")}
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none"
            />
            <input
              value={regPath}
              onChange={(e) => setRegPath(e.target.value)}
              placeholder={t("workspace.pathPlaceholder")}
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground font-mono focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none"
            />
            <input
              value={regDesc}
              onChange={(e) => setRegDesc(e.target.value)}
              placeholder={t("workspace.descriptionPlaceholder")}
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowRegister(false)}
                className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                onClick={handleRegister}
                disabled={registering || !regName.trim() || !regPath.trim()}
                className="flex items-center gap-2 px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {registering && <Loader2 className="w-3 h-3 animate-spin" />}
                {registering ? t("workspace.registering") : t("workspace.register")}
              </button>
            </div>
          </div>
        )}

        {/* 工作区列表 */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <FolderOpen className="w-12 h-12 text-muted-foreground/30 mb-3" />
            <p className="text-muted-foreground text-sm">{t("workspace.noWorkspaces")}</p>
            <p className="text-muted-foreground/60 text-xs mt-1">{t("workspace.noWorkspacesHint")}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {workspaces.map((ws) => (
              <div key={ws.id} className="bg-card border border-border rounded-xl overflow-hidden">

                {/* 卡片头部 */}
                <div
                  className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => toggleExpand(ws.id)}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    {ws.active
                      ? <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                      : <Circle className="w-4 h-4 text-muted-foreground shrink-0" />
                    }
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm text-foreground">{ws.name}</span>
                        {ws.active && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/10 text-green-600">
                            {t("workspace.active")}
                          </span>
                        )}
                        {ws.shell_enabled && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-orange-500/10 text-orange-600 flex items-center gap-1">
                            <Terminal className="w-3 h-3" />
                            {ws.shell_level}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">{ws.path}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    {!ws.active && (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); handleActivate(ws); }}
                        disabled={activating === ws.id}
                        className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-50 transition-colors"
                      >
                        {activating === ws.id
                          ? <Loader2 className="w-3 h-3 animate-spin" />
                          : <CheckCircle2 className="w-3 h-3" />
                        }
                        {t("workspace.activate")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleUnregister(ws); }}
                      className="p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                      title={t("workspace.unregister")}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                    {expanded === ws.id
                      ? <ChevronUp className="w-4 h-4 text-muted-foreground" />
                      : <ChevronDown className="w-4 h-4 text-muted-foreground" />
                    }
                  </div>
                </div>

                {/* 展开详情 */}
                {expanded === ws.id && (
                  <div className="border-t border-border px-4 py-3 space-y-3 bg-muted/30">

                    {/* 基本信息 */}
                    <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                      {ws.description && (
                        <div className="col-span-2">
                          描述: <span className="text-foreground">{ws.description}</span>
                        </div>
                      )}
                      <div>{t("workspace.createdAt")}: <span className="text-foreground">{formatDate(ws.created_at)}</span></div>
                      <div>{t("workspace.lastAccessed")}: <span className="text-foreground">{formatDate(ws.last_accessed)}</span></div>
                      <div>
                        Shell: <span className="text-foreground">
                          {ws.shell_enabled
                            ? `${t("workspace.shellEnabled")} (${ws.shell_level})`
                            : t("workspace.shellDisabled")}
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Globe className="w-3 h-3" />
                        {t("workspace.networkWhitelist")}:{" "}
                        <span className="text-foreground">
                          {ws.network_whitelist.length > 0
                            ? ws.network_whitelist.join(", ")
                            : t("workspace.noWhitelist")}
                        </span>
                      </div>
                    </div>

                    {/* 文件树 */}
                    <div>
                      <button
                        type="button"
                        onClick={() => handleViewTree(ws)}
                        disabled={treeLoading === ws.id}
                        className="flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
                      >
                        {treeLoading === ws.id
                          ? <Loader2 className="w-3 h-3 animate-spin" />
                          : <FolderOpen className="w-3 h-3" />
                        }
                        {treeLoading === ws.id ? t("workspace.loadingTree") : t("workspace.viewTree")}
                      </button>
                      {treeData[ws.id] && (
                        <pre className="mt-2 p-3 bg-background rounded-lg text-xs font-mono text-foreground overflow-auto max-h-64 border border-border">
                          {treeData[ws.id]}
                        </pre>
                      )}
                    </div>

                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
