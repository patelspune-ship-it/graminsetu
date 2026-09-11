import translations from "./i18n/translations";

// Display labels only. The backend's ARCHETYPES registry
// (backend/app/archetypes/configs/*.json) remains the source of truth
// for every number used in scoring or financial calculations.
export const ARCHETYPE_LABELS = {
  dairy_collection: {
    name: "Milk Collection Service Point",
    skills: ["Animal husbandry", "Bookkeeping"],
  },
  dal_mill: {
    name: "Small Dal Milling Service",
    skills: ["Machine operation", "Food processing"],
  },
  flour_mill: {
    name: "Small Flour Mill",
    skills: ["Machine operation"],
  },
  kirana_store: {
    name: "Small Kirana Store",
    skills: ["Retail & sales", "Bookkeeping"],
  },
  onion_storage: {
    name: "Ventilated Onion Storage Service",
    skills: ["Farming", "Bookkeeping"],
  },
  tailoring_unit: {
    name: "Small Tailoring Unit",
    skills: ["Tailoring"],
  },
};

// `lang` defaults to English so every pre-existing call site (including the
// data blob sent to the Gemini "Explain in my language" feature) keeps its
// original behaviour unless it explicitly opts into the UI language.
export function archetypeName(id, lang = "en") {
  const dict = translations[lang] || translations.en;
  return dict[`archetype.${id}`] || ARCHETYPE_LABELS[id]?.name || id;
}

export const SUB_SCORE_LABELS = {
  market_gap: "Market gap",
  demand: "Demand",
  inputs: "Input availability",
  infrastructure: "Infrastructure",
  skills: "Skill fit",
  capital: "Capital fit",
};

export function subScoreLabel(name, lang = "en") {
  const dict = translations[lang] || translations.en;
  return dict[`subscore.${name}`] || SUB_SCORE_LABELS[name] || name;
}
