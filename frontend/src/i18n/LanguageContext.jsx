import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import translations from "./translations";

const STORAGE_KEY = "graminsetu_ui_language";
const DEFAULT_LANGUAGE = "en";

function readSavedLanguage() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved && translations[saved] ? saved : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

function writeSavedLanguage(language) {
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // Storage may be disabled; the toggle still works for this session.
  }
}

function interpolate(template, vars) {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, key) =>
    key in vars ? String(vars[key]) : match
  );
}

const LanguageContext = createContext(null);

// Persisted independently of the assessment (a different localStorage key,
// never cleared by "Start New"), so the language a user picks on the first
// screen stays selected across every step, a page reload, and starting a
// fresh assessment. This is purely a static UI-string toggle — it is not
// used by, and does not affect, the Gemini "Explain in my language" feature
// or the feasibility-report LLM call, which keep their own language choice.
export function LanguageProvider({ children }) {
  const [language, setLanguageState] = useState(readSavedLanguage);

  useEffect(() => {
    writeSavedLanguage(language);
  }, [language]);

  const setLanguage = useCallback((next) => {
    setLanguageState(translations[next] ? next : DEFAULT_LANGUAGE);
  }, []);

  const t = useCallback(
    (key, vars) => {
      const dict = translations[language] || translations[DEFAULT_LANGUAGE];
      const value = dict[key] ?? translations[DEFAULT_LANGUAGE][key] ?? key;
      return interpolate(value, vars);
    },
    [language]
  );

  const value = useMemo(() => ({ language, setLanguage, t }), [language, setLanguage, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
}
