/**
 * 系统设置页面：Provider 配置 + API Key 管理 + 隐私管道设置
 */

import { useState, useEffect } from "react";
import { Settings, Key, Shield, Loader2, Save, CheckCircle, XCircle } from "lucide-react";
import { apiGet, apiFetch } from "@/shared/api/client";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

interface SecretsStatus {
  configured: Record<string, boolean>;
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [secretsStatus, setSecretsStatus] = useState<SecretsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<"providers" | "keys" | "privacy">("providers");

  // API Key 输入状态（不回显真实 key，仅接受新输入）
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});

  useEffect(() => {
    const load = async () => {
      try {
        const [cfg, secrets] = await Promise.all([
          apiGet<Record<string, unknown>>("/config"),
          apiGet<SecretsStatus>("/config/secrets/status"),
        ]);
        setConfig(cfg);
        setSecretsStatus(secrets);
      } catch (err) {
        toast.error(`加载配置失败: ${err}`);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleSaveConfig = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await apiFetch("/config", {
        method: "PUT",
        body: JSON.stringify({ config }),
      });
      toast.success("配置已保存");
    } catch (err) {
      toast.error(`保存失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveKeys = async () => {
    // 构建 secrets 结构
    const secrets: Record<string, unknown> = {};
    for (const [path, value] of Object.entries(keyInputs)) {
      if (!value.trim() || value === "***") continue;
      const parts = path.split(".");
      let current: Record<string, unknown> = secrets;
      for (let i = 0; i < parts.length - 1; i++) {
        current[parts[i]] = current[parts[i]] || {};
        current = current[parts[i]] as Record<string, unknown>;
      }
      current[parts[parts.length - 1]] = value.trim();
    }

    if (Object.keys(secrets).length === 0) {
      toast.info("没有需要保存的 Key");
      return;
    }

    setSaving(true);
    try {
      await apiFetch("/config/secrets", {
        method: "PUT",
        body: JSON.stringify({ secrets }),
      });
      toast.success("API Key 已保存");
      setKeyInputs({});
      // 刷新状态
      const status = await apiGet<SecretsStatus>("/config/secrets/status");
      setSecretsStatus(status);
    } catch (err) {
      toast.error(`保存失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  // 从 config 中提取 provider 列表
  const providers = config?.providers as Record<string, Record<string, unknown>> | undefined;

  const tabs = [
    { id: "providers" as const, label: t("settings.providers"), icon: Settings },
    { id: "keys" as const, label: t("settings.apiKeys"), icon: Key },
    { id: "privacy" as const, label: t("settings.privacy"), icon: Shield },
  ];

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
            <Settings className="w-5 h-5 text-primary" />
            {t("settings.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t("settings.description")}</p>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors flex-1 justify-center ${
                activeTab === tab.id
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Provider 配置 */}
        {activeTab === "providers" && providers && (
          <div className="space-y-3">
            {Object.entries(providers).map(([pid, pcfg]) => (
              <div key={pid} className="bg-card border border-border rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-foreground">{pid}</h3>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={!!pcfg.enabled}
                      onChange={(e) => {
                        if (!config) return;
                        const newProviders = { ...(config.providers as Record<string, unknown>) };
                        newProviders[pid] = { ...pcfg, enabled: e.target.checked };
                        setConfig({ ...config, providers: newProviders });
                      }}
                      className="rounded border-border"
                    />
                    启用
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  {pcfg.base_url ? <div>Base URL: <span className="text-foreground">{String(pcfg.base_url)}</span></div> : null}
                  {pcfg.models ? <div>模型: <span className="text-foreground">{Array.isArray(pcfg.models) ? (pcfg.models as string[]).join(", ") : String(pcfg.models)}</span></div> : null}
                </div>
              </div>
            ))}
            <button
              type="button"
              onClick={handleSaveConfig}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {t("settings.saveConfig")}
            </button>
          </div>
        )}

        {/* API Key 管理 */}
        {activeTab === "keys" && (
          <div className="space-y-3">
            {/* LLM 主 Key */}
            <KeyRow
              label="llm (默认)"
              path="llm.api_key"
              configured={secretsStatus?.configured?.llm}
              value={keyInputs["llm.api_key"] || ""}
              onChange={(v) => setKeyInputs({ ...keyInputs, "llm.api_key": v })}
              t={t}
            />

            {/* Provider Keys */}
            {providers && Object.keys(providers).map((pid) => (
              <KeyRow
                key={pid}
                label={pid}
                path={`providers.${pid}.api_key`}
                configured={secretsStatus?.configured?.[`providers.${pid}`]}
                value={keyInputs[`providers.${pid}.api_key`] || ""}
                onChange={(v) => setKeyInputs({ ...keyInputs, [`providers.${pid}.api_key`]: v })}
                t={t}
              />
            ))}

            <button
              type="button"
              onClick={handleSaveKeys}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {t("settings.saveKeys")}
            </button>
          </div>
        )}

        {/* 隐私保护设置 */}
        {activeTab === "privacy" && config && (
          <div className="space-y-4">
            {/* 主开关 + 法律依据 */}
            <div className="bg-card border border-border rounded-xl p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <h3 className="text-sm font-medium text-foreground">{t("settings.privacyEnabled")}</h3>
                  <p className="text-xs text-muted-foreground mt-1">{t("settings.privacyLegalBasis")}</p>
                </div>
                <input
                  type="checkbox"
                  checked={!!((config.privacy as Record<string, unknown>)?.enabled ?? true)}
                  onChange={(e) => {
                    const privacy = { ...(config.privacy as Record<string, unknown> || {}), enabled: e.target.checked };
                    setConfig({ ...config, privacy });
                  }}
                  className="mt-0.5 rounded border-border"
                />
              </div>
            </div>

            {/* 保护范围说明 */}
            <div className="bg-card border border-border rounded-xl p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-medium text-foreground">{t("settings.privacyScope")}</h3>
              </div>
              <p className="text-xs text-muted-foreground">{t("settings.privacyScopeDesc")}</p>
              <div className="grid grid-cols-3 gap-1.5">
                {(["scopePhone", "scopeIdCard", "scopeBankCard", "scopePassport", "scopeNameAddress", "scopeEmail"] as const).map((key) => (
                  <div key={key} className="flex items-center gap-1.5 text-xs text-foreground bg-primary/5 rounded-md px-2 py-1.5">
                    <CheckCircle className="w-3 h-3 text-primary shrink-0" />
                    {t(`settings.${key}`)}
                  </div>
                ))}
              </div>
              <div className="border-t border-border pt-3">
                <p className="text-xs font-medium text-muted-foreground mb-2">{t("settings.privacyNotScope")}</p>
                <ul className="space-y-1">
                  {(["notScopeDeidentified", "notScopeToolResult", "notScopeOutput"] as const).map((key) => (
                    <li key={key} className="text-xs text-muted-foreground flex items-start gap-1.5">
                      <span className="mt-0.5 text-muted-foreground/50">—</span>
                      {t(`settings.${key}`)}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* 敏感级别阈值 */}
            <div className="bg-card border border-border rounded-xl p-4 space-y-3">
              <h3 className="text-sm font-medium text-foreground">{t("settings.sensitivityLevels")}</h3>
              <p className="text-xs text-muted-foreground">{t("settings.sensitivityLevelsDesc")}</p>
              {(["critical", "high", "medium", "low"] as const).map((level) => {
                const levels = ((config.privacy as Record<string, unknown>)?.sensitivity_levels ?? {}) as Record<string, boolean>;
                const checked = levels[level] ?? (level !== "low");
                return (
                  <label key={level} className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        const privacy = (config.privacy as Record<string, unknown>) || {};
                        const sl = { ...(privacy.sensitivity_levels as Record<string, boolean> || {}) };
                        sl[level] = e.target.checked;
                        setConfig({ ...config, privacy: { ...privacy, sensitivity_levels: sl } });
                      }}
                      className="mt-0.5 rounded border-border"
                      disabled={level === "critical"}
                    />
                    <div>
                      <div className="text-sm font-medium text-foreground">{t(`settings.sensitivity_${level}`)}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{t(`settings.sensitivity_${level}_desc`)}</div>
                    </div>
                  </label>
                );
              })}
            </div>

            <button
              type="button"
              onClick={handleSaveConfig}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {t("settings.saveConfig")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function KeyRow({
  label,
  path,
  configured,
  value,
  onChange,
  t,
}: {
  label: string;
  path: string;
  configured?: boolean;
  value: string;
  onChange: (v: string) => void;
  t: (key: string) => string;
}) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 flex items-center gap-3">
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-sm font-medium text-foreground">{label}</span>
          {configured ? (
            <span className="flex items-center gap-1 text-xs text-green-500">
              <CheckCircle className="w-3 h-3" />
              {t("settings.keyConfigured")}
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <XCircle className="w-3 h-3" />
              {t("settings.keyNotConfigured")}
            </span>
          )}
        </div>
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={configured ? "已配置（输入新值可覆盖）" : `输入 ${label} API Key`}
          className="w-full bg-background border border-border rounded-lg px-3 py-1.5 text-sm text-foreground font-mono focus:border-primary/50 focus:ring-1 focus:ring-primary/20 focus:outline-none"
          autoComplete="off"
          data-key-path={path}
        />
      </div>
    </div>
  );
}
