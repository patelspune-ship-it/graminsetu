import { useEffect, useState } from "react";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleHelp,
  Compass,
  FileBarChart,
  FileText,
  IndianRupee,
  Landmark,
  Leaf,
  LoaderCircle,
  MapPin,
  MapPinned,
  RefreshCw,
  Sparkles,
  ShieldCheck,
  Sprout,
  TriangleAlert,
  UserRound,
  Wallet,
} from "lucide-react";

import { api, formatMoney, paiseToRupeeString, rupeesToPaise } from "./api";
import MicButton from "./components/MicButton";
import { useLanguage } from "./i18n/LanguageContext";
import LanguageSelector from "./i18n/LanguageSelector";
import LocationMapPicker from "./screens/LocationMapPicker";
import VillageMapStep from "./screens/VillageMapStep";
import ViabilityStep from "./screens/ViabilityStep";
import FinancingStep from "./screens/FinancingStep";
import FundingStep from "./screens/FundingStep";
import FeasibilityReportStep from "./screens/FeasibilityReportStep";
import DprStep from "./screens/DprStep";

const SKILLS = [
  "farming",
  "basic_machine_operation",
  "animal_husbandry",
  "tailoring",
  "retail_sales",
  "food_processing",
  "bookkeeping",
];

const INITIAL_FORM = {
  surname: "",
  first_name: "",
  middle_name: "",
  preferred_language: "en",
  capital_rupees: "",
  skills: [],
  premises: "not_arranged",
  power: "unknown",
};

// Kept entirely separate from `form`/`ProfileCreate`: this is additional
// location context only, never sent to the backend, never used to look up
// nearby villages, and never touches village_lgd or scoring/evidence.
const INITIAL_BUSINESS_LOCATION = {
  address: "",
  pincode: "",
  latitude: null,
  longitude: null,
};

const STEPS = [
  { key: "village", icon: MapPin },
  { key: "profile", icon: UserRound },
  { key: "viability", icon: FileBarChart },
  { key: "financing", icon: Landmark },
  { key: "funding", icon: Wallet },
  { key: "feasibility", icon: Compass },
  { key: "report", icon: FileText },
];

const PREMISES_OPTIONS = ["owned", "rented", "not_arranged"];

const POWER_OPTIONS = ["single_phase", "three_phase", "unavailable", "unknown"];

function readSavedId() {
  try {
    return localStorage.getItem("graminsetu_assessment_id");
  } catch {
    return null;
  }
}

function writeSavedId(id) {
  try {
    if (id) {
      localStorage.setItem("graminsetu_assessment_id", id);
    } else {
      localStorage.removeItem("graminsetu_assessment_id");
    }
  } catch {
    // Storage may be disabled; the current session still works.
  }
}

function App() {
  const { t, language } = useLanguage();
  const [step, setStep] = useState(0);
  const [villageId, setVillageId] = useState("");
  const [villages, setVillages] = useState([]);
  const [form, setForm] = useState(INITIAL_FORM);
  const [businessLocation, setBusinessLocation] = useState(INITIAL_BUSINESS_LOCATION);
  const [showLocationPicker, setShowLocationPicker] = useState(false);
  const [assessment, setAssessment] = useState(null);

  const [viabilityItem, setViabilityItem] = useState(null);
  const [financialModel, setFinancialModel] = useState(null);
  const [financingRequest, setFinancingRequest] = useState(null);
  const [fundingResult, setFundingResult] = useState(null);

  const [health, setHealth] = useState("checking");
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState(true);
  const [saving, setSaving] = useState(false);
  const [freeText, setFreeText] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setLoadError("");

    Promise.all([api("/health"), api("/villages")])
      .then(([status, records]) => {
        if (cancelled) return;
        setHealth(status.database === "connected" ? "online" : "offline");
        setVillages(records);
      })
      .catch((err) => {
        if (cancelled) return;
        setHealth("offline");
        setLoadError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useEffect(() => {
    let cancelled = false;
    const savedId = readSavedId();

    if (!savedId) {
      setRestoring(false);
      return;
    }

    api(`/assessments/${savedId}`)
      .then((saved) => {
        if (cancelled) return;
        setAssessment(saved);
        setStep(2);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(t("app.restoreError", { message: err.message }));
        }
      })
      .finally(() => {
        if (!cancelled) setRestoring(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedVillage = villages.find(
    (village) => village.id === villageId
  );

  function updateForm(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function toggleSkill(skill) {
    setForm((current) => ({
      ...current,
      skills: current.skills.includes(skill)
        ? current.skills.filter((item) => item !== skill)
        : [...current.skills, skill],
    }));
  }

  function startNew() {
    writeSavedId(null);
    setAssessment(null);
    setForm(INITIAL_FORM);
    setBusinessLocation(INITIAL_BUSINESS_LOCATION);
    setShowLocationPicker(false);
    setVillageId("");
    setViabilityItem(null);
    setFinancialModel(null);
    setFinancingRequest(null);
    setFundingResult(null);
    setFreeText("");
    setExtractError("");
    setError("");
    setStep(0);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function selectViabilityItem(item) {
    setViabilityItem(item);
    setFinancialModel(null);
    setFinancingRequest(null);
    setFundingResult(null);
    setStep(3);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function recordFinancialModel(result, requestPayload) {
    setFinancialModel(result);
    setFinancingRequest(requestPayload);
    setFundingResult(null);
  }

  // Carries a specific compared offer through to the report, instead of
  // the single locked offer generated by the Financing step.
  function selectOfferForReport(result) {
    setFinancialModel(result);
  }

  async function extractProfileFromText() {
    setExtractError("");
    setExtracting(true);

    try {
      const fields = await api("/llm/extract-profile", {
        method: "POST",
        timeoutMs: 45000,
        body: JSON.stringify({ text: freeText }),
      });

      setForm((current) => ({
        ...current,
        capital_rupees:
          fields.own_capital_paise === null
            ? current.capital_rupees
            : paiseToRupeeString(fields.own_capital_paise),
        skills: fields.skills === null ? current.skills : fields.skills,
        premises: fields.premises === null ? current.premises : fields.premises,
        power: fields.power === null ? current.power : fields.power,
      }));
    } catch (err) {
      setExtractError(err.message);
    } finally {
      setExtracting(false);
    }
  }

  async function saveProfile(event) {
    event.preventDefault();
    setError("");

    if (!selectedVillage) {
      setError(t("app.chooseVillageError"));
      setStep(0);
      return;
    }

    const applicantName = [form.first_name, form.middle_name, form.surname]
      .map((part) => part.trim())
      .filter(Boolean)
      .join(" ");

    if (applicantName.length > 100) {
      setError(t("app.nameLengthError"));
      return;
    }

    setSaving(true);

    try {
      const ownCapitalPaise = rupeesToPaise(form.capital_rupees);

      const saved = await api("/assessments", {
        method: "POST",
        body: JSON.stringify({
          applicant_name: applicantName,
          village_id: villageId,
          preferred_language: form.preferred_language,
          own_capital_paise: ownCapitalPaise,
          skills: form.skills,
          premises: form.premises,
          power: form.power,
        }),
      });

      writeSavedId(saved.id);
      setAssessment(saved);
      setStep(2);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-8">
          <a href="/" className="flex items-center gap-3" aria-label="GraminSetu home">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-forest text-lime">
              <Sprout size={25} strokeWidth={1.8} />
            </div>

            <div>
              <div className="text-xl font-extrabold tracking-tight">
                Gramin<span className="text-forest">Setu</span>
              </div>
              <div className="text-[11px] text-stone-500">
                गांव से उद्यम तक
              </div>
            </div>
          </a>

          <div className="flex items-center gap-3">
            <span className="hidden rounded-full bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-600 sm:block">
              {t("header.pilotBadge")}
            </span>

            <span className="flex items-center gap-2 text-xs text-stone-600">
              <span
                className={`h-2 w-2 rounded-full ${
                  health === "online"
                    ? "bg-emerald-500"
                    : health === "offline"
                      ? "bg-red-400"
                      : "bg-amber-400"
                }`}
              />
              <span className="hidden sm:inline">
                {health === "online"
                  ? t("header.status.online")
                  : health === "offline"
                    ? t("header.status.offline")
                    : t("header.status.connecting")}
              </span>
              <span className="sm:hidden">
                {health === "online" ? t("header.status.onlineShort") : t("header.status.devShort")}
              </span>
            </span>

            <LanguageSelector />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-9">
        <section
          className={`hero-pattern relative mb-8 overflow-hidden rounded-[28px] border border-[#e1e7d5] bg-[#edf2e4] p-6 sm:p-9 sm:block ${
            step > 0 ? "hidden" : ""
          }`}
        >
          <div className="relative z-10 max-w-2xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-forest/15 bg-white/70 px-3 py-1.5 text-xs font-semibold text-forest">
              <Leaf size={14} />
              {t("header.tagline")}
            </div>

            <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
              {t("hero.titleLine1")}
              <br className="sm:hidden" /> {t("hero.titleLine2")}
            </h1>

            <p className="mt-3 max-w-xl text-sm leading-7 text-[#526353] sm:text-base">
              {t("hero.description")}
            </p>

            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs font-medium text-forest">
              <span className="flex items-center gap-1.5">
                <ShieldCheck size={15} /> {t("hero.badge.transparent")}
              </span>
              <span className="flex items-center gap-1.5">
                <IndianRupee size={15} /> {t("hero.badge.noFee")}
              </span>
              <span className="flex items-center gap-1.5">
                <MapPin size={15} /> {t("hero.badge.pilotVillages")}
              </span>
            </div>
          </div>

          <Sprout
            className="absolute -bottom-10 right-6 hidden rotate-12 text-forest/10 lg:block"
            size={240}
            strokeWidth={1}
            aria-hidden="true"
          />
        </section>

        <div className="grid items-start gap-7 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <div className="card !p-4 sm:!p-5">
              <p className="mb-5 hidden text-xs font-bold uppercase tracking-widest text-stone-400 lg:block">
                {t("sidebar.heading")}
              </p>

              {step > 0 && (
                <div className="flex items-center gap-2 text-xs font-semibold text-stone-500 sm:hidden">
                  <span className="shrink-0 text-forest">
                    {t("sidebar.stepCounter", { current: step + 1, total: STEPS.length })}
                  </span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
                    <div
                      className="h-1.5 rounded-full bg-forest transition-all"
                      style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
                    />
                  </div>
                  <span className="shrink-0 truncate text-stone-600">
                    {t(`steps.${STEPS[step].key}.title`)}
                  </span>
                </div>
              )}

              <ol
                className={`grid-cols-3 gap-2 lg:grid lg:grid-cols-1 lg:gap-3 ${
                  step > 0 ? "hidden sm:grid" : "grid"
                }`}
              >
                {STEPS.map((item, index) => {
                  const Icon = item.icon;
                  const active = step === index;
                  const complete = step > index;

                  return (
                    <li
                      key={item.key}
                      aria-current={active ? "step" : undefined}
                      className={`flex flex-col items-center gap-2 rounded-2xl px-2 py-3 text-center lg:flex-row lg:gap-3 lg:px-3 lg:text-left ${
                        active ? "bg-forest/7" : ""
                      }`}
                    >
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                          active
                            ? "bg-forest text-white"
                            : complete
                              ? "bg-lime/60 text-forest"
                              : "bg-stone-100 text-stone-400"
                        }`}
                      >
                        {complete ? <Check size={18} /> : <Icon size={18} />}
                      </div>

                      <div>
                        <p
                          className={`text-xs font-semibold lg:text-sm ${
                            active ? "text-forest" : "text-stone-600"
                          }`}
                        >
                          {t(`steps.${item.key}.title`)}
                        </p>
                        <p className="mt-1 hidden text-xs text-stone-400 lg:block">
                          {t(`steps.${item.key}.note`)}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>

            <div className="hidden rounded-2xl border border-stone-200 bg-white/60 p-5 lg:block">
              <CircleHelp size={20} className="mb-3 text-forest" />
              <h3 className="text-sm font-semibold">{t("sidebar.helpTitle")}</h3>
              <p className="mt-2 text-xs leading-6 text-stone-500">
                {t("sidebar.helpBody")}
              </p>
            </div>

            <div className="hidden px-2 text-xs leading-6 text-stone-400 lg:block">
              {t("sidebar.buildNote1")}
              <br />
              {t("sidebar.buildNote2")}
            </div>
          </aside>

          <div className="min-w-0 space-y-5">
            {(error || loadError) && (
              <div
                role="alert"
                className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
              >
                <p>{error || loadError}</p>

                {loadError && (
                  <button
                    type="button"
                    onClick={() => setReloadKey((value) => value + 1)}
                    className="mt-3 inline-flex items-center gap-2 font-semibold"
                  >
                    <RefreshCw size={15} /> {t("app.retryConnection")}
                  </button>
                )}
              </div>
            )}

            {restoring ? (
              <div className="card flex items-center gap-3 text-sm text-stone-500">
                <LoaderCircle className="animate-spin" size={20} />
                {t("app.checkingSaved")}
              </div>
            ) : (
              <>
                {step === 0 && (
                  <VillageMapStep
                    villages={villages}
                    loading={loading}
                    villageId={villageId}
                    setVillageId={setVillageId}
                    selectedVillage={selectedVillage}
                    onContinue={() => {
                      setError("");
                      setStep(1);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  />
                )}

                {step === 1 && (
                  <form onSubmit={saveProfile} className="card fade-in">
                    <p className="eyebrow">{t("profile.eyebrow")}</p>
                    <h2 className="mt-2 text-2xl font-bold tracking-tight">
                      {t("profile.heading")}
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-stone-500">
                      {t("profile.subheading")}
                    </p>

                    <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-stone-100 px-3 py-2 text-xs text-stone-600">
                      <MapPin size={14} />
                      {selectedVillage?.name}, {selectedVillage?.district}
                    </div>

                    <div className="mt-6 rounded-2xl border border-dashed border-forest/30 bg-forest/5 p-4">
                      <label className="label" htmlFor="free-text">
                        {t("profile.freeText.label")}
                      </label>
                      <p className="mt-1 text-xs text-stone-500">
                        {t("profile.freeText.help")}
                      </p>
                      <textarea
                        id="free-text"
                        className="field mt-3 min-h-24"
                        placeholder="उदा. माझ्याकडे 50,000 रुपये आहेत, मला शेतीचे काम येते, स्वतःची जागा आहे..."
                        value={freeText}
                        onChange={(event) => setFreeText(event.target.value)}
                      />
                      <div className="mt-3 flex flex-wrap items-center gap-3">
                        <MicButton
                          lang={language}
                          onTranscript={(transcript) =>
                            setFreeText((current) =>
                              current.trim() ? `${current.trim()} ${transcript}` : transcript
                            )
                          }
                        />
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={extracting || !freeText.trim()}
                          onClick={extractProfileFromText}
                        >
                          {extracting ? (
                            <>
                              <LoaderCircle size={16} className="animate-spin" />
                              {t("profile.freeText.reading")}
                            </>
                          ) : (
                            <>
                              <Sparkles size={16} /> {t("profile.freeText.fillButton")}
                            </>
                          )}
                        </button>
                      </div>
                      {extractError && (
                        <div className="mt-3 flex items-start gap-2 text-sm leading-6 text-red-700">
                          <TriangleAlert size={15} className="mt-0.5 shrink-0" />
                          <p>{t("profile.freeText.error", { message: extractError })}</p>
                        </div>
                      )}
                    </div>

                    <div className="mt-6 grid gap-5 sm:grid-cols-2">
                      <div className="sm:col-span-2">
                        <div className="grid gap-4 sm:grid-cols-3">
                          <div>
                            <label className="label" htmlFor="surname">
                              {t("profile.name.surname")}
                            </label>
                            <input
                              id="surname"
                              className="field"
                              placeholder={t("profile.name.namePlaceholder")}
                              autoComplete="family-name"
                              required
                              minLength={2}
                              maxLength={50}
                              value={form.surname}
                              onChange={(event) =>
                                updateForm("surname", event.target.value)
                              }
                            />
                          </div>

                          <div>
                            <label className="label" htmlFor="first-name">
                              {t("profile.name.first")}
                            </label>
                            <input
                              id="first-name"
                              className="field"
                              placeholder={t("profile.name.namePlaceholder")}
                              autoComplete="given-name"
                              required
                              minLength={2}
                              maxLength={50}
                              value={form.first_name}
                              onChange={(event) =>
                                updateForm("first_name", event.target.value)
                              }
                            />
                          </div>

                          <div>
                            <label className="label" htmlFor="middle-name">
                              {t("profile.name.middle")}
                            </label>
                            <input
                              id="middle-name"
                              className="field"
                              placeholder={t("profile.name.middlePlaceholder")}
                              autoComplete="additional-name"
                              maxLength={50}
                              value={form.middle_name}
                              onChange={(event) =>
                                updateForm("middle_name", event.target.value)
                              }
                            />
                          </div>
                        </div>

                        <p className="mt-2 text-xs text-stone-500">
                          {t("profile.name.disclaimer")}
                        </p>
                      </div>

                      <div>
                        <label className="label" htmlFor="language">
                          {t("profile.language.label")}
                        </label>
                        <select
                          id="language"
                          className="field"
                          value={form.preferred_language}
                          onChange={(event) =>
                            updateForm("preferred_language", event.target.value)
                          }
                        >
                          <option value="en">English</option>
                          <option value="mr">मराठी — Marathi</option>
                          <option value="hi">हिन्दी — Hindi</option>
                        </select>
                        <p className="mt-2 text-xs text-stone-400">
                          {t("profile.language.note")}
                        </p>
                      </div>

                      <div className="sm:col-span-2">
                        <label className="label" htmlFor="capital">
                          {t("profile.capital.label")}
                        </label>

                        <div className="relative">
                          <span className="pointer-events-none absolute left-4 top-[21px] text-stone-500">
                            ₹
                          </span>
                          <input
                            id="capital"
                            className="field !pl-9"
                            inputMode="decimal"
                            placeholder="50000"
                            required
                            maxLength={12}
                            pattern="[0-9]{1,9}([.][0-9]{1,2})?"
                            title={t("profile.capital.title")}
                            value={form.capital_rupees}
                            onChange={(event) =>
                              updateForm("capital_rupees", event.target.value)
                            }
                          />
                        </div>

                        <p className="mt-2 text-xs leading-5 text-stone-500">
                          {t("profile.capital.help")}
                        </p>
                      </div>
                    </div>

                    <fieldset className="mt-6">
                      <legend className="label">{t("profile.skills.legend")}</legend>
                      <p className="mt-1 text-xs text-stone-500">
                        {t("profile.skills.help")}
                      </p>

                      <div className="mt-3 flex flex-wrap gap-2">
                        {SKILLS.map((id) => {
                          const selected = form.skills.includes(id);

                          return (
                            <button
                              key={id}
                              type="button"
                              aria-pressed={selected}
                              onClick={() => toggleSkill(id)}
                              className={`inline-flex min-h-11 items-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                                selected
                                  ? "border-forest bg-forest/5 font-medium text-forest"
                                  : "border-stone-200 text-stone-600 hover:border-forest/40"
                              }`}
                            >
                              {selected && <Check size={14} />}
                              {t(`skills.${id}`)}
                            </button>
                          );
                        })}
                      </div>
                    </fieldset>

                    <div className="mt-6 grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="premises">
                          {t("profile.premises.label")}
                        </label>
                        <select
                          id="premises"
                          className="field"
                          value={form.premises}
                          onChange={(event) =>
                            updateForm("premises", event.target.value)
                          }
                        >
                          {PREMISES_OPTIONS.map((id) => (
                            <option key={id} value={id}>{t(`premises.${id}`)}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="label" htmlFor="power">
                          {t("profile.power.label")}
                        </label>
                        <select
                          id="power"
                          className="field"
                          value={form.power}
                          onChange={(event) =>
                            updateForm("power", event.target.value)
                          }
                        >
                          {POWER_OPTIONS.map((id) => (
                            <option key={id} value={id}>{t(`power.${id}`)}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <fieldset className="mt-6 rounded-2xl border border-stone-200 p-4">
                      <legend className="label px-1">{t("profile.location.heading")}</legend>
                      <p className="mt-1 text-xs leading-5 text-stone-500">
                        {t("profile.location.subtitle")}
                      </p>

                      <div className="mt-4 grid gap-5 sm:grid-cols-2">
                        <div>
                          <label className="label" htmlFor="business-address">
                            {t("profile.location.addressLabel")}
                          </label>
                          <input
                            id="business-address"
                            className="field"
                            placeholder={t("profile.location.addressPlaceholder")}
                            maxLength={200}
                            value={businessLocation.address}
                            onChange={(event) =>
                              setBusinessLocation((current) => ({
                                ...current,
                                address: event.target.value,
                              }))
                            }
                          />
                        </div>

                        <div>
                          <label className="label" htmlFor="business-pincode">
                            {t("profile.location.pincodeLabel")}
                          </label>
                          <input
                            id="business-pincode"
                            className="field"
                            inputMode="numeric"
                            placeholder={t("profile.location.pincodePlaceholder")}
                            maxLength={6}
                            pattern="[0-9]{6}"
                            value={businessLocation.pincode}
                            onChange={(event) =>
                              setBusinessLocation((current) => ({
                                ...current,
                                pincode: event.target.value.replace(/\D/g, "").slice(0, 6),
                              }))
                            }
                          />
                        </div>
                      </div>

                      <button
                        type="button"
                        className="btn-secondary mt-4"
                        onClick={() => setShowLocationPicker(true)}
                      >
                        <MapPinned size={16} /> {t("profile.location.selectOnMap")}
                      </button>

                      {businessLocation.latitude !== null && businessLocation.longitude !== null && (
                        <div className="mt-4 flex items-start gap-2 rounded-xl bg-forest/5 p-3 text-sm text-forest">
                          <CheckCircle2 size={17} className="mt-0.5 shrink-0" />
                          <div className="min-w-0">
                            <p className="font-semibold">{t("profile.location.selected")}</p>
                            {businessLocation.address && (
                              <p className="mt-0.5 text-stone-600">{businessLocation.address}</p>
                            )}
                            <p className="mt-0.5 text-stone-500">
                              {t("profile.location.coordinates", {
                                lat: businessLocation.latitude.toFixed(5),
                                lng: businessLocation.longitude.toFixed(5),
                              })}
                            </p>
                            <button
                              type="button"
                              className="mt-2 text-xs font-semibold text-forest underline"
                              onClick={() => setShowLocationPicker(true)}
                            >
                              {t("profile.location.changeLocation")}
                            </button>
                          </div>
                        </div>
                      )}
                    </fieldset>

                    <div className="mt-6 flex items-start gap-3 rounded-xl bg-stone-50 p-4">
                      <ShieldCheck size={19} className="mt-0.5 shrink-0 text-forest" />
                      <p className="text-xs leading-6 text-stone-500">
                        {t("profile.privacy")}
                      </p>
                    </div>

                    <div className="mt-7 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={saving}
                        onClick={() => {
                          setError("");
                          setStep(0);
                        }}
                      >
                        <ArrowLeft size={16} /> {t("common.back")}
                      </button>

                      <button
                        type="submit"
                        className="btn-primary"
                        disabled={saving}
                      >
                        {saving ? (
                          <>
                            <LoaderCircle size={17} className="animate-spin" />
                            {t("profile.saving")}
                          </>
                        ) : (
                          <>
                            {t("profile.save")} <ArrowRight size={17} />
                          </>
                        )}
                      </button>
                    </div>
                  </form>
                )}

                {step === 2 && assessment && (
                  <ViabilityStep
                    assessment={assessment}
                    onSelect={selectViabilityItem}
                    onBack={() => setStep(1)}
                  />
                )}

                {step === 3 && assessment && viabilityItem && (
                  <FinancingStep
                    assessment={assessment}
                    viabilityItem={viabilityItem}
                    financialModel={financialModel}
                    onGenerated={recordFinancialModel}
                    onBack={() => setStep(2)}
                    onContinue={() => {
                      setStep(4);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  />
                )}

                {step === 4 && financingRequest && (
                  <FundingStep
                    assessment={assessment}
                    archetypeId={viabilityItem.archetype_id}
                    financingRequest={financingRequest}
                    fundingResult={fundingResult}
                    financialModel={financialModel}
                    onGenerated={setFundingResult}
                    onSelectOffer={selectOfferForReport}
                    onBack={() => setStep(3)}
                    onContinue={() => {
                      setStep(5);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  />
                )}

                {step === 5 && financialModel && (
                  <FeasibilityReportStep
                    assessment={assessment}
                    viabilityItem={viabilityItem}
                    financialModel={financialModel}
                    financingRequest={financingRequest}
                    onGenerated={recordFinancialModel}
                    onBack={() => setStep(4)}
                    onContinue={() => {
                      setStep(6);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  />
                )}

                {step === 6 && financialModel && (
                  <DprStep
                    archetypeId={viabilityItem.archetype_id}
                    financialModel={financialModel}
                    onBack={() => setStep(5)}
                    onStartNew={startNew}
                  />
                )}
              </>
            )}

            <div className="grid gap-3 sm:grid-cols-3">
              <FeatureNote
                icon={MapPin}
                title={t("features.viability.title")}
                description={t("features.viability.desc")}
              />
              <FeatureNote
                icon={Wallet}
                title={t("features.capital.title")}
                description={t("features.capital.desc")}
              />
              <FeatureNote
                icon={FileText}
                title={t("features.report.title")}
                description={t("features.report.desc")}
              />
            </div>

            <p className="text-center text-[11px] leading-5 text-stone-400">
              {t("footer.disclaimer")}
            </p>
          </div>
        </div>
      </main>

      <footer className="mx-auto mt-6 flex max-w-7xl flex-col gap-2 border-t border-stone-200 px-4 py-6 text-xs text-stone-400 sm:flex-row sm:justify-between sm:px-8">
        <p>{t("footer.tagline")}</p>
        <p>{t("footer.buildInfo")}</p>
      </footer>

      {showLocationPicker && (
        <LocationMapPicker
          villageCenter={
            selectedVillage?.latitude != null && selectedVillage?.longitude != null
              ? [selectedVillage.latitude, selectedVillage.longitude]
              : null
          }
          initialPosition={
            businessLocation.latitude !== null && businessLocation.longitude !== null
              ? { lat: businessLocation.latitude, lng: businessLocation.longitude }
              : null
          }
          onCancel={() => setShowLocationPicker(false)}
          onConfirm={(position) => {
            setBusinessLocation((current) => ({
              ...current,
              latitude: position.lat,
              longitude: position.lng,
            }));
            setShowLocationPicker(false);
          }}
        />
      )}
    </div>
  );
}

function FeatureNote({ icon: Icon, title, description }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-stone-200/70 bg-white/50 p-4">
      <Icon size={18} className="mt-0.5 shrink-0 text-forest/70" />
      <div>
        <p className="text-xs font-semibold">{title}</p>
        <p className="mt-1 text-[11px] leading-5 text-stone-500">
          {description}
        </p>
      </div>
    </div>
  );
}

export default App;
