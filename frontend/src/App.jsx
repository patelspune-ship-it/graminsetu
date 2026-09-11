import { useEffect, useState } from "react";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleHelp,
  Compass,
  FileBarChart,
  FileText,
  IndianRupee,
  Landmark,
  Leaf,
  LoaderCircle,
  MapPin,
  RefreshCw,
  Sparkles,
  ShieldCheck,
  Sprout,
  TriangleAlert,
  UserRound,
  Wallet,
} from "lucide-react";

import { api, formatMoney, paiseToRupeeString, rupeesToPaise } from "./api";
import ViabilityStep from "./screens/ViabilityStep";
import FinancingStep from "./screens/FinancingStep";
import FundingStep from "./screens/FundingStep";
import FeasibilityReportStep from "./screens/FeasibilityReportStep";
import DprStep from "./screens/DprStep";

const SKILLS = [
  ["farming", "Farming"],
  ["basic_machine_operation", "Machine operation"],
  ["animal_husbandry", "Animal husbandry"],
  ["tailoring", "Tailoring"],
  ["retail_sales", "Retail & sales"],
  ["food_processing", "Food processing"],
  ["bookkeeping", "Bookkeeping"],
];

const INITIAL_FORM = {
  applicant_name: "",
  preferred_language: "en",
  capital_rupees: "",
  skills: [],
  premises: "not_arranged",
  power: "unknown",
};

const STEPS = [
  { title: "Your village", note: "Choose your location", icon: MapPin },
  { title: "Your profile", note: "Skills and investment", icon: UserRound },
  { title: "Viability", note: "Evidence-based scoring", icon: FileBarChart },
  { title: "Financing", note: "Cost, loan, DSCR", icon: Landmark },
  { title: "Funding options", note: "Compare scenarios", icon: Wallet },
  { title: "Feasibility report", note: "Market, SWOT, pricing", icon: Compass },
  { title: "Report", note: "Download the PDF", icon: FileText },
];

const PREMISES_LABELS = {
  owned: "Owned premises",
  rented: "Rented premises",
  not_arranged: "Not arranged yet",
};

const POWER_LABELS = {
  single_phase: "Single-phase",
  three_phase: "Three-phase",
  unavailable: "No connection",
  unknown: "Needs verification",
};

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
  const [step, setStep] = useState(0);
  const [district, setDistrict] = useState("Nashik");
  const [villageId, setVillageId] = useState("");
  const [villages, setVillages] = useState([]);
  const [form, setForm] = useState(INITIAL_FORM);
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
          setError(`Could not restore the previous assessment. ${err.message}`);
        }
      })
      .finally(() => {
        if (!cancelled) setRestoring(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const [villageQuery, setVillageQuery] = useState("");

  const districtVillages = villages.filter(
    (village) => village.district === district
  );

  const filteredVillages = districtVillages.filter((village) =>
    village.name.toLowerCase().includes(villageQuery.trim().toLowerCase())
  );

  const visibleVillages = filteredVillages.slice(0, 24);

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
      setError("Choose a village before saving your profile.");
      setStep(0);
      return;
    }

    setSaving(true);

    try {
      const ownCapitalPaise = rupeesToPaise(form.capital_rupees);

      const saved = await api("/assessments", {
        method: "POST",
        body: JSON.stringify({
          applicant_name: form.applicant_name.trim(),
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
              Maharashtra pilot
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
                  ? "Backend connected"
                  : health === "offline"
                    ? "Backend offline"
                    : "Connecting"}
              </span>
              <span className="sm:hidden">
                {health === "online" ? "Online" : "Dev build"}
              </span>
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-9">
        <section className="hero-pattern relative mb-8 overflow-hidden rounded-[28px] border border-[#e1e7d5] bg-[#edf2e4] p-6 sm:p-9">
          <div className="relative z-10 max-w-2xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-forest/15 bg-white/70 px-3 py-1.5 text-xs font-semibold text-forest">
              <Leaf size={14} />
              Local context. Clear next steps.
            </div>

            <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
              Your village.
              <br className="sm:hidden" /> Your next opportunity.
            </h1>

            <p className="mt-3 max-w-xl text-sm leading-7 text-[#526353] sm:text-base">
              Start with your location, skills and available capital.
              Build a business plan grounded in your circumstances.
            </p>

            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs font-medium text-forest">
              <span className="flex items-center gap-1.5">
                <ShieldCheck size={15} /> Transparent assumptions
              </span>
              <span className="flex items-center gap-1.5">
                <IndianRupee size={15} /> No fee in this demo
              </span>
              <span className="flex items-center gap-1.5">
                <MapPin size={15} /> Nashik & Jalgaon
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
                Your assessment
              </p>

              <ol className="grid grid-cols-3 gap-2 lg:grid-cols-1 lg:gap-3">
                {STEPS.map((item, index) => {
                  const Icon = item.icon;
                  const active = step === index;
                  const complete = step > index;

                  return (
                    <li
                      key={item.title}
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
                          {item.title}
                        </p>
                        <p className="mt-1 hidden text-xs text-stone-400 lg:block">
                          {item.note}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>

            <div className="hidden rounded-2xl border border-stone-200 bg-white/60 p-5 lg:block">
              <CircleHelp size={20} className="mb-3 text-forest" />
              <h3 className="text-sm font-semibold">Designed to explain, not guess.</h3>
              <p className="mt-2 text-xs leading-6 text-stone-500">
                Missing local evidence will be shown as missing—not silently
                converted into a confident recommendation.
              </p>
            </div>

            <div className="hidden px-2 text-xs leading-6 text-stone-400 lg:block">
              Development build 0.1
              <br />
              Village data, viability, financing and DPR are live.
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
                    <RefreshCw size={15} /> Retry connection
                  </button>
                )}
              </div>
            )}

            {restoring ? (
              <div className="card flex items-center gap-3 text-sm text-stone-500">
                <LoaderCircle className="animate-spin" size={20} />
                Checking for a saved assessment…
              </div>
            ) : (
              <>
                {step === 0 && (
                  <section className="card fade-in">
                    <p className="eyebrow">Step 01 / Location</p>
                    <h2 className="mt-2 text-2xl font-bold tracking-tight">
                      Where will you start?
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-stone-500">
                      Location will anchor the market, input and infrastructure
                      evidence used in your assessment.
                    </p>

                    <div className="grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="state">State</label>
                        <input
                          id="state"
                          className="field"
                          value="Maharashtra"
                          disabled
                        />
                      </div>

                      <div>
                        <label className="label" htmlFor="district">District</label>
                        <select
                          id="district"
                          className="field"
                          value={district}
                          onChange={(event) => {
                            setDistrict(event.target.value);
                            setVillageId("");
                            setVillageQuery("");
                          }}
                        >
                          <option>Nashik</option>
                          <option>Jalgaon</option>
                        </select>
                      </div>
                    </div>

                    <fieldset className="mt-6">
                      <legend className="label">Choose your village</legend>

                      {loading ? (
                        <div className="mt-4 flex items-center gap-2 text-sm text-stone-500">
                          <LoaderCircle size={17} className="animate-spin" />
                          Loading locations…
                        </div>
                      ) : districtVillages.length === 0 ? (
                        <p className="mt-4 text-sm text-stone-500">
                          No records loaded. Check the backend connection.
                        </p>
                      ) : (
                        <>
                          <input
                            type="search"
                            className="field mt-3"
                            placeholder={`Search ${districtVillages.length} villages by name…`}
                            value={villageQuery}
                            onChange={(event) => setVillageQuery(event.target.value)}
                          />

                          <div className="mt-3 grid gap-3 sm:grid-cols-2">
                            {visibleVillages.map((village) => {
                              const selected = villageId === village.id;

                              return (
                                <label
                                  key={village.id}
                                  className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition ${
                                    selected
                                      ? "border-forest bg-forest/5"
                                      : "border-stone-200 hover:border-forest/40"
                                  }`}
                                >
                                  <input
                                    type="radio"
                                    name="village"
                                    value={village.id}
                                    checked={selected}
                                    onChange={() => setVillageId(village.id)}
                                    className="mt-1 h-4 w-4 accent-[#176448]"
                                  />

                                  <div className="min-w-0 flex-1">
                                    <div className="text-sm font-semibold">
                                      {village.name}
                                    </div>
                                    <div className="mt-1 text-xs leading-5 text-stone-500">
                                      {village.district}
                                    </div>
                                    <div className="mt-1 text-xs leading-5 text-stone-400">
                                      {village.source}
                                    </div>
                                  </div>

                                  <MapPin size={18} className="mt-0.5 shrink-0 text-forest" />
                                </label>
                              );
                            })}
                          </div>

                          {filteredVillages.length === 0 ? (
                            <p className="mt-3 text-sm text-stone-500">
                              No village matches that search.
                            </p>
                          ) : filteredVillages.length > visibleVillages.length ? (
                            <p className="mt-3 text-sm text-stone-500">
                              Showing {visibleVillages.length} of {filteredVillages.length}{" "}
                              matches. Keep typing to narrow the list.
                            </p>
                          ) : null}
                        </>
                      )}
                    </fieldset>

                    <div className="mt-8 flex justify-end border-t border-stone-100 pt-5">
                      <button
                        type="button"
                        className="btn-primary w-full sm:w-auto"
                        disabled={!selectedVillage || loading}
                        onClick={() => {
                          setError("");
                          setStep(1);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Continue to your profile <ArrowRight size={17} />
                      </button>
                    </div>
                  </section>
                )}

                {step === 1 && (
                  <form onSubmit={saveProfile} className="card fade-in">
                    <p className="eyebrow">Step 02 / Entrepreneur profile</p>
                    <h2 className="mt-2 text-2xl font-bold tracking-tight">
                      Tell us about your starting point.
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-stone-500">
                      It is okay to start small. Enter what you have today—not
                      what you hope a bank will approve.
                    </p>

                    <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-stone-100 px-3 py-2 text-xs text-stone-600">
                      <MapPin size={14} />
                      {selectedVillage?.name}, {selectedVillage?.district}
                    </div>

                    <div className="mt-6 rounded-2xl border border-dashed border-forest/30 bg-forest/5 p-4">
                      <label className="label" htmlFor="free-text">
                        Optional: describe yourself in your own words
                      </label>
                      <p className="mt-1 text-xs text-stone-500">
                        Write in Hindi, Marathi or English. We will try to
                        pre-fill capital, skills, premises and power below —
                        you can still review and correct every field.
                      </p>
                      <textarea
                        id="free-text"
                        className="field mt-3 min-h-24"
                        placeholder="उदा. माझ्याकडे 50,000 रुपये आहेत, मला शेतीचे काम येते, स्वतःची जागा आहे..."
                        value={freeText}
                        onChange={(event) => setFreeText(event.target.value)}
                      />
                      <div className="mt-3 flex flex-wrap items-center gap-3">
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={extracting || !freeText.trim()}
                          onClick={extractProfileFromText}
                        >
                          {extracting ? (
                            <>
                              <LoaderCircle size={16} className="animate-spin" />
                              Reading…
                            </>
                          ) : (
                            <>
                              <Sparkles size={16} /> Fill fields from my description
                            </>
                          )}
                        </button>
                      </div>
                      {extractError && (
                        <div className="mt-3 flex items-start gap-2 text-sm leading-6 text-red-700">
                          <TriangleAlert size={15} className="mt-0.5 shrink-0" />
                          <p>Could not read that description right now. {extractError}</p>
                        </div>
                      )}
                    </div>

                    <div className="mt-6 grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="name">
                          Applicant name
                        </label>
                        <input
                          id="name"
                          className="field"
                          placeholder="Use a demo name for testing"
                          autoComplete="name"
                          required
                          minLength={2}
                          maxLength={100}
                          value={form.applicant_name}
                          onChange={(event) =>
                            updateForm("applicant_name", event.target.value)
                          }
                        />
                      </div>

                      <div>
                        <label className="label" htmlFor="language">
                          Preferred advisory language
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
                          Preference saved; translation is not connected yet.
                        </p>
                      </div>

                      <div className="sm:col-span-2">
                        <label className="label" htmlFor="capital">
                          Your own available capital
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
                            title="Enter rupees without commas, with up to two decimal places."
                            value={form.capital_rupees}
                            onChange={(event) =>
                              updateForm("capital_rupees", event.target.value)
                            }
                          />
                        </div>

                        <p className="mt-2 text-xs leading-5 text-stone-500">
                          Savings you can contribute. Exclude loans and expected
                          subsidies. Enter 0 if no funds are available.
                        </p>
                      </div>
                    </div>

                    <fieldset className="mt-6">
                      <legend className="label">Skills you already have</legend>
                      <p className="mt-1 text-xs text-stone-500">
                        Select all that apply. You may leave this empty.
                      </p>

                      <div className="mt-3 flex flex-wrap gap-2">
                        {SKILLS.map(([id, label]) => {
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
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    </fieldset>

                    <div className="mt-6 grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="premises">
                          Business premises
                        </label>
                        <select
                          id="premises"
                          className="field"
                          value={form.premises}
                          onChange={(event) =>
                            updateForm("premises", event.target.value)
                          }
                        >
                          {Object.entries(PREMISES_LABELS).map(([id, label]) => (
                            <option key={id} value={id}>{label}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="label" htmlFor="power">
                          Electricity at business premises
                        </label>
                        <select
                          id="power"
                          className="field"
                          value={form.power}
                          onChange={(event) =>
                            updateForm("power", event.target.value)
                          }
                        >
                          {Object.entries(POWER_LABELS).map(([id, label]) => (
                            <option key={id} value={id}>{label}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div className="mt-6 flex items-start gap-3 rounded-xl bg-stone-50 p-4">
                      <ShieldCheck size={19} className="mt-0.5 shrink-0 text-forest" />
                      <p className="text-xs leading-6 text-stone-500">
                        This local development build has no authentication.
                        Use test information only. We do not need Aadhaar,
                        bank account numbers or credit reports.
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
                        <ArrowLeft size={16} /> Back
                      </button>

                      <button
                        type="submit"
                        className="btn-primary"
                        disabled={saving}
                      >
                        {saving ? (
                          <>
                            <LoaderCircle size={17} className="animate-spin" />
                            Saving profile…
                          </>
                        ) : (
                          <>
                            Save assessment <ArrowRight size={17} />
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
                title="Local viability"
                description="Evidence-backed ranking"
              />
              <FeatureNote
                icon={Wallet}
                title="Capital planning"
                description="Affordability before borrowing"
              />
              <FeatureNote
                icon={FileText}
                title="Project report"
                description="Traceable financial assumptions"
              />
            </div>

            <p className="text-center text-[11px] leading-5 text-stone-400">
              Viability, financing and report figures are illustrative and
              unverified. GraminSetu is not a lender and does not guarantee
              approval.
            </p>
          </div>
        </div>
      </main>

      <footer className="mx-auto mt-6 flex max-w-7xl flex-col gap-2 border-t border-stone-200 px-4 py-6 text-xs text-stone-400 sm:flex-row sm:justify-between sm:px-8">
        <p>GraminSetu · Built for rural enterprise</p>
        <p>SIH prototype · Development environment · v0.1</p>
      </footer>
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
