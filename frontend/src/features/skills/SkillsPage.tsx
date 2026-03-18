/**
 * Skill 管理页面：列表 + 安装 + 卸载
 */

import { useState, useEffect, useCallback } from "react";
import { Puzzle, Plus, Trash2, Shield, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { apiGet, apiPost, apiFetch } from "@/shared/api/client";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

interface SkillAction {
  command: string;
  pattern: string;
  description: string;
}

interface SkillItem {
  name: string;
  version: string;
  status: string;
  content_hash: string;
  reviewed_at: string;
  gatekeeper_model: string;
  actions: SkillAction[];
}

export default function SkillsPage() {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showInstall, setShowInstall] = useState(false);
  const [installName, setInstallName] = useState("");
  const [installContent, setInstallContent] = useState("");
  const [installing, setInstalling] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchSkills = useCallback(async () => {
    try {
      const list = await apiGet<SkillItem[]>("/skills");
      setSkills(list);
    } catch (err) {
      toast.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const handleInstall = async () => {
    if (!installName.trim() || !installContent.trim()) return;
    setInstalling(true);
    try {
      await apiPost("/skills", {
        name: installName.trim(),
        skill_md: installContent,
      });
      toast.success(`Skill "${installName}" 安装成功`);
      setInstallName("");
      setInstallContent("");
      setShowInstall(false);
      fetchSkills();
    } catch (err) {
      toast.error(`安装失败: ${err}`);
    } finally {
      setInstalling(false);
    }
  };

  const handleUninstall = async (name: string) => {
    if (!confirm(t("skills.confirmUninstall"))) return;
    try {
      await apiFetch(`/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
      toast.success(`Skill "${name}" 已卸载`);
      fetchSkills();
    } catch (err) {
      toast.error(`卸载失败: ${err}`);
    }
  };

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      approved: "bg-green-500/10 text-green-600",
      rewritten: "bg-yellow-500/10 text-yellow-600",
      rejected: "bg-red-500/10 text-red-600",
    };
    const labels: Record<string, string> = {
      approved: t("skills.approved"),
      rewritten: t("skills.rewritten"),
      rejected: t("skills.rejected"),
    };
    return (
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || "bg-muted text-muted-foreground"}`}>
        {labels[status] || status}
      </span>
    );
  };

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* 标题 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
              <Puzzle className="w-5 h-5 text-primary" />
              {t("skills.title")}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">{t("skills.description")}</p>
          </div>
          <button
            type="button"
            onClick={() => setShowInstall(!showInstall)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t("skills.install")}
          </button>
        </div>

        {/* 安装表单 */}
        {showInstall && (
          <div className="bg-card border border-border rounded-xl p-4 space-y-3">
            <input
              value={installName}
              onChange={(e) => setInstallName(e.target.value)}
              placeholder={t("skills.namePlaceholder")}
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none"
            />
            <textarea
              value={installContent}
              onChange={(e) => setInstallContent(e.target.value)}
              placeholder={t("skills.contentPlaceholder")}
              rows={8}
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground font-mono resize-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowInstall(false)}
                className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                onClick={handleInstall}
                disabled={installing || !installName.trim() || !installContent.trim()}
                className="flex items-center gap-2 px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {installing && <Loader2 className="w-3 h-3 animate-spin" />}
                {installing ? t("skills.installing") : t("skills.install")}
              </button>
            </div>
          </div>
        )}

        {/* Skills 列表 */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : skills.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Shield className="w-12 h-12 text-muted-foreground/30 mb-3" />
            <p className="text-muted-foreground text-sm">{t("skills.noSkills")}</p>
            <p className="text-muted-foreground/60 text-xs mt-1">{t("skills.noSkillsHint")}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {skills.map((skill) => (
              <div key={skill.name} className="bg-card border border-border rounded-xl overflow-hidden">
                <div
                  className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setExpanded(expanded === skill.name ? null : skill.name)}
                >
                  <div className="flex items-center gap-3">
                    <Puzzle className="w-4 h-4 text-muted-foreground" />
                    <span className="font-medium text-sm text-foreground">{skill.name}</span>
                    <span className="text-xs text-muted-foreground">v{skill.version}</span>
                    {statusBadge(skill.status)}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleUninstall(skill.name); }}
                      className="p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                      title={t("skills.uninstall")}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                    {expanded === skill.name ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
                  </div>
                </div>

                {expanded === skill.name && (
                  <div className="border-t border-border px-4 py-3 space-y-2 bg-muted/30">
                    <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                      <div>审查模型: <span className="text-foreground">{skill.gatekeeper_model}</span></div>
                      <div>审查时间: <span className="text-foreground">{skill.reviewed_at}</span></div>
                      <div>Hash: <span className="text-foreground font-mono">{skill.content_hash}</span></div>
                    </div>
                    {skill.actions.length > 0 && (
                      <div className="mt-2">
                        <p className="text-xs font-medium text-muted-foreground mb-1">{t("skills.actions")}:</p>
                        <div className="space-y-1">
                          {skill.actions.map((a, i) => (
                            <div key={i} className="flex items-center gap-2 text-xs">
                              <code className="px-1.5 py-0.5 bg-muted rounded font-mono text-foreground">{a.command}</code>
                              <span className="text-muted-foreground">{a.description}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
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
