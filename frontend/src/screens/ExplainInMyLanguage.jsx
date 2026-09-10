import { useState } from "react";
import { Languages, LoaderCircle, TriangleAlert } from "lucide-react";

import { api } from "../api";

const LANGUAGES = [
  ["en", "English"],
  ["hi", "हिन्दी — Hindi"],
  ["mr", "मराठी — Marathi"],
];

// Renders a language picker and button that asks the backend LLM to
// restate already-computed figures in plain language. A failure here
// never blocks the rest of the screen — it only affects this panel.
export default function ExplainInMyLanguage({ computedData, defaultLang = "en" }) {
  const [lang, setLang] = useState(defaultLang);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [explanation, setExplanation] = useState("");

  async function explain() {
    setLoading(true);
    setError("");

    try {
      const result = await api("/llm/explain", {
        method: "POST",
        timeoutMs: 45000,
        body: JSON.stringify({ computed_data: computedData, lang }),
      });
      setExplanation(result.explanation);
    } catch (err) {
      setExplanation("");
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Languages size={18} className="shrink-0 text-forest" />

        <select
          className="field !w-auto !py-2"
          value={lang}
          onChange={(event) => {
            setLang(event.target.value);
            setExplanation("");
            setError("");
          }}
          aria-label="Explanation language"
        >
          {LANGUAGES.map(([id, label]) => (
            <option key={id} value={id}>{label}</option>
          ))}
        </select>

        <button
          type="button"
          className="btn-secondary"
          disabled={loading}
          onClick={explain}
        >
          {loading ? (
            <>
              <LoaderCircle size={16} className="animate-spin" />
              Explaining…
            </>
          ) : (
            "Explain in my language"
          )}
        </button>
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 text-base leading-6 text-red-700">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" />
          <p>Could not fetch an explanation right now. {error}</p>
        </div>
      )}

      {explanation && (
        <p className="mt-3 whitespace-pre-line text-base leading-7 text-stone-700">
          {explanation}
        </p>
      )}
    </div>
  );
}
