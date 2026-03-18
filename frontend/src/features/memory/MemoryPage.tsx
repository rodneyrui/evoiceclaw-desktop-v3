/**
 * 记忆管理页面（占位）
 */

import { Brain } from "lucide-react";
import { useTranslation } from "react-i18next";

export default function MemoryPage() {
  const { t } = useTranslation();

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
            <Brain className="w-5 h-5 text-primary" />
            {t("memory.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t("memory.description")}</p>
        </div>

        <div className="flex flex-col items-center justify-center py-20 text-center">
          <Brain className="w-16 h-16 text-muted-foreground/20 mb-4" />
          <p className="text-muted-foreground text-sm">{t("memory.comingSoon")}</p>
        </div>
      </div>
    </div>
  );
}
