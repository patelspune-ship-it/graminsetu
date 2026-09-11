import { Languages } from "lucide-react";

import { useLanguage } from "./LanguageContext";
import { LANGUAGE_OPTIONS } from "./translations";

// Rendered once in the app header, which is always on screen regardless of
// assessment step — so it stays available on every page. Switching here
// updates the current page immediately (React context) and persists via
// localStorage for every later screen.
export default function LanguageSelector() {
  const { language, setLanguage, t } = useLanguage();

  return (
    <label className="flex items-center gap-1.5 text-xs text-stone-600">
      <Languages size={15} className="hidden shrink-0 text-forest sm:block" />
      <span className="sr-only">{t("header.languageLabel")}</span>
      <select
        aria-label={t("header.languageLabel")}
        className="rounded-full border border-stone-200 bg-white px-2.5 py-1.5 text-xs font-medium text-stone-700 outline-none transition focus:border-forest focus:ring-2 focus:ring-forest/15"
        value={language}
        onChange={(event) => setLanguage(event.target.value)}
      >
        {LANGUAGE_OPTIONS.map((option) => (
          <option key={option.code} value={option.code}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
