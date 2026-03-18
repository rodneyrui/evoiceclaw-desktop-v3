import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import zhCN from "./locales/zh-CN.json";
import enUS from "./locales/en-US.json";

export const LS_LANG_KEY = "evoiceclaw_lang";

function loadLang(): string {
  try {
    return localStorage.getItem(LS_LANG_KEY) || "zh-CN";
  } catch {
    return "zh-CN";
  }
}

i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { translation: zhCN },
    "en-US": { translation: enUS },
  },
  lng: loadLang(),
  fallbackLng: "zh-CN",
  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
