import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  Grid2x2,
  Lightbulb,
  LoaderCircle,
  MapPin,
  RefreshCw,
  Tag,
  TriangleAlert,
  Users,
} from "lucide-react";

import { api } from "../api";
import { archetypeName } from "../archetypes";
import { useLanguage } from "../i18n/LanguageContext";

const CARDS = [
  { key: "market_reach", labelKey: "feasibility.card.marketReach", icon: MapPin },
  { key: "opportunity_analysis", labelKey: "feasibility.card.opportunityAnalysis", icon: Lightbulb },
  { key: "swot", labelKey: "feasibility.card.swot", icon: Grid2x2 },
  { key: "threats", labelKey: "feasibility.card.threats", icon: TriangleAlert },
  { key: "competitor_mapping", labelKey: "feasibility.card.competitorMapping", icon: Users },
  { key: "product_market_value", labelKey: "feasibility.card.productMarketValue", icon: Tag },
];

// Narrative built only from figures already computed elsewhere in this
// assessment. Generating it does not change the financing scenario; it
// is attached to the report only when the user continues past this step.
export default function FeasibilityReportStep({
  assessment,
  viabilityItem,
  financialModel,
  financingRequest,
  onGenerated,
  onBack,
  onContinue,
}) {
  const { t, language } = useLanguage();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attaching, setAttaching] = useState(false);
  const [openCard, setOpenCard] = useState("market_reach");

  const snapshot = financialModel.snapshot;

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const result = await api("/llm/feasibility-report", {
        method: "POST",
        timeoutMs: 45000,
        body: JSON.stringify({
          village_lgd: assessment.profile.village_id,
          archetype_id: viabilityItem.archetype_id,
          project_cost_paise: snapshot.project.project_cost_paise,
          available_for_project_paise: snapshot.stack.own_contribution_paise,
          lang: assessment.profile.preferred_language,
        }),
      });
      setReport(result);
    } catch (err) {
      setReport(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!report && !loading) generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-submits the same financing scenario, this time with the generated
  // report attached, so it flows into the DPR PDF. If generation failed,
  // the user can still continue without one — the DPR states its absence
  // explicitly rather than blocking the rest of the flow.
  async function continueToFunding() {
    if (!report) {
      onContinue();
      return;
    }

    setAttaching(true);
    setError("");
    try {
      const result = await api("/financial-model", {
        method: "POST",
        body: JSON.stringify({
          assessment_id: assessment.id,
          archetype_id: viabilityItem.archetype_id,
          available_for_project_paise: financingRequest.available_for_project_paise,
          finance: snapshot.finance_offer,
          assumptions: financingRequest.assumptions,
          feasibility_report: report,
        }),
      });
      onGenerated(result, financingRequest);
      onContinue();
    } catch (err) {
      setError(err.message);
    } finally {
      setAttaching(false);
    }
  }

  return (
    <section className="card fade-in">
      <p className="eyebrow">{t("feasibility.eyebrow")}</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        {t("feasibility.heading")}
      </h2>
      <p className="mt-2 text-base leading-6 text-stone-500">
        {t("feasibility.subheading", {
          archetype: archetypeName(viabilityItem.archetype_id, language),
        })}
      </p>

      {loading && (
        <div className="mt-6 flex items-center gap-3 text-base text-stone-500">
          <LoaderCircle className="animate-spin" size={20} />
          {t("feasibility.generating")}
        </div>
      )}

      {error && (
        <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800">
          <p>{error}</p>
          <button
            type="button"
            onClick={generate}
            className="mt-3 inline-flex items-center gap-2 font-semibold"
          >
            <RefreshCw size={16} /> {t("common.tryAgain")}
          </button>
        </div>
      )}

      {report && (
        <div className="mt-6 space-y-3">
          {CARDS.map(({ key, labelKey, icon: Icon }) => (
            <ExpandableCard
              key={key}
              label={t(labelKey)}
              icon={Icon}
              isOpen={openCard === key}
              onToggle={() => setOpenCard(openCard === key ? null : key)}
            >
              <SectionBody sectionKey={key} data={report[key]} />
            </ExpandableCard>
          ))}
        </div>
      )}

      <div className="mt-8 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
        <button type="button" className="btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} /> {t("common.back")}
        </button>

        <button
          type="button"
          className="btn-primary"
          disabled={attaching}
          onClick={continueToFunding}
        >
          {attaching ? (
            <>
              <LoaderCircle size={17} className="animate-spin" />
              {t("feasibility.attaching")}
            </>
          ) : (
            <>
              {t("feasibility.continueReport")} <ArrowRight size={17} />
            </>
          )}
        </button>
      </div>
    </section>
  );
}

function ExpandableCard({ label, icon: Icon, isOpen, onToggle, children }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-stone-200">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 p-4 text-left"
        aria-expanded={isOpen}
      >
        <span className="flex items-center gap-2 text-base font-bold">
          <Icon size={18} className="shrink-0 text-forest" /> {label}
        </span>
        <ChevronDown
          size={18}
          className={`shrink-0 text-stone-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
        />
      </button>
      {isOpen && (
        <div className="border-t border-stone-100 p-4 text-base leading-6 text-stone-700">
          {children}
        </div>
      )}
    </div>
  );
}

function SectionBody({ sectionKey, data }) {
  const { t } = useLanguage();

  if (sectionKey === "swot") {
    return (
      <dl className="grid gap-4 sm:grid-cols-2">
        {["strengths", "weaknesses", "opportunities", "threats"].map((key) => (
          <div key={key}>
            <dt className="text-base font-semibold capitalize text-stone-800">
              {t(`feasibility.swot.${key}`)}
            </dt>
            <dd className="mt-1 text-stone-600">{data[key]}</dd>
          </div>
        ))}
      </dl>
    );
  }

  if (sectionKey === "competitor_mapping") {
    return (
      <div>
        {data.value_percent && (
          <p className="text-lg font-bold text-stone-800">{data.value_percent}</p>
        )}
        <p className="mt-1 text-stone-600">
          {data.note || t("feasibility.noMarketGapEvidence")}
        </p>
        <p className="mt-2 text-base text-stone-400">
          {t("feasibility.passthroughNote")}
        </p>
      </div>
    );
  }

  return <p>{data}</p>;
}
