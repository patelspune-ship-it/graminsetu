import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  LoaderCircle,
  MapPin,
  RefreshCw,
} from "lucide-react";

import { api, formatMoney, formatRatioPercent } from "../api";
import { archetypeName, SUB_SCORE_LABELS } from "../archetypes";

const VERDICT_STYLES = {
  STRONG: "bg-emerald-100 text-emerald-800",
  MODERATE: "bg-amber-100 text-amber-800",
  WEAK: "bg-stone-200 text-stone-700",
  INSUFFICIENT_DATA: "bg-stone-100 text-stone-600",
};

const STATUS_STYLES = {
  OK: "border-emerald-200 bg-emerald-50 text-emerald-900",
  PARTIAL_COVERAGE: "border-amber-200 bg-amber-50 text-amber-900",
  OUT_OF_COVERAGE: "border-red-200 bg-red-50 text-red-900",
};

function bpsToPercent(bps) {
  return `${(bps / 100).toFixed(bps % 100 === 0 ? 0 : 1)}%`;
}

function sortItems(items) {
  return [...items].sort((a, b) => {
    const scoreA = a.result.score;
    const scoreB = b.result.score;
    if (scoreA === null && scoreB === null) return 0;
    if (scoreA === null) return 1;
    if (scoreB === null) return -1;
    return scoreB - scoreA;
  });
}

export default function ViabilityStep({ assessment, onSelect, onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const villageLgd = assessment.profile.village_id;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    api(`/villages/${encodeURIComponent(villageLgd)}/viability?assessment_id=${assessment.id}`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [villageLgd, assessment.id, reloadKey]);

  return (
    <section className="card fade-in">
      <p className="eyebrow">Step 03 / Business viability</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        What could work in {assessment.village.name}?
      </h2>

      <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-stone-100 px-3 py-2 text-base text-stone-600">
        <MapPin size={16} />
        {assessment.village.name}, {assessment.village.district}
      </div>

      <div className="mt-3 flex items-start gap-2 rounded-xl border border-stone-200 bg-stone-50 p-4">
        <CircleHelp size={18} className="mt-0.5 shrink-0 text-forest" />
        <p className="text-base leading-6 text-stone-600">
          <span className="font-semibold text-ink">Source: </span>
          {assessment.village.source}
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="mt-3 inline-flex items-center gap-2 font-semibold"
          >
            <RefreshCw size={16} /> Try again
          </button>
        </div>
      )}

      {loading ? (
        <div className="mt-6 flex items-center gap-3 text-base text-stone-500">
          <LoaderCircle className="animate-spin" size={20} />
          Scoring local business options…
        </div>
      ) : data ? (
        <>
          <div
            className={`mt-6 rounded-2xl border p-4 text-base leading-6 ${STATUS_STYLES[data.status]}`}
          >
            <p className="font-semibold">{data.status.replace(/_/g, " ")}</p>
            <p className="mt-1">{data.message}</p>
          </div>

          <p className="mt-3 text-base leading-6 text-stone-500">
            {data.capital_fit_basis}
          </p>

          {data.missing_archetype_ids.length > 0 && (
            <p className="mt-3 text-base leading-6 text-stone-500">
              <span className="font-semibold">No local data yet for: </span>
              {data.missing_archetype_ids.map(archetypeName).join(", ")}
            </p>
          )}

          <div className="mt-6 space-y-4">
            {sortItems(data.items).map((item) => (
              <ViabilityCard
                key={item.archetype_id}
                item={item}
                onSelect={() => onSelect(item, data)}
              />
            ))}

            {data.items.length === 0 && (
              <p className="text-base text-stone-500">
                No archetype could be scored for this village yet.
              </p>
            )}
          </div>
        </>
      ) : null}

      <div className="mt-8 flex justify-start border-t border-stone-100 pt-5">
        <button type="button" className="btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} /> Back
        </button>
      </div>
    </section>
  );
}

function ViabilityCard({ item, onSelect }) {
  const { result } = item;
  const isKnown = result.score !== null;

  return (
    <div className="rounded-2xl border border-stone-200 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold">{archetypeName(item.archetype_id)}</h3>
          <p className="mt-1 text-base text-stone-500">
            Illustrative own contribution: {formatMoney(item.required_own_contribution_paise)}
          </p>
        </div>

        <span
          className={`shrink-0 rounded-full px-3 py-1.5 text-base font-semibold ${VERDICT_STYLES[result.verdict] || VERDICT_STYLES.INSUFFICIENT_DATA}`}
        >
          {isKnown
            ? `${result.verdict} · ${result.score}/100`
            : `Unknown · range ${result.lower_bound_score}–${result.upper_bound_score}`}
        </span>
      </div>

      <p className="mt-3 text-base text-stone-500">
        Evidence coverage: {bpsToPercent(result.evidence_coverage_bps)} of scoring weight
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {result.sub_scores.map((sub) => (
          <div key={sub.name} className="rounded-xl bg-stone-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-base font-semibold text-ink">
                {SUB_SCORE_LABELS[sub.name] || sub.name}
              </span>
              <span className="text-base text-stone-500">
                weight {bpsToPercent(sub.weight_bps)}
              </span>
            </div>

            <p className="mt-1 text-base font-semibold">
              {sub.value !== null ? (
                formatRatioPercent(sub.value)
              ) : (
                <span className="text-amber-700">Unknown</span>
              )}
            </p>

            <p className="mt-1 text-base leading-6 text-stone-500">{sub.note}</p>
          </div>
        ))}
      </div>

      {result.warnings.length > 0 && (
        <ul className="mt-4 list-disc space-y-1 pl-5 text-base leading-6 text-stone-500">
          {result.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className="btn-primary mt-4 w-full sm:w-auto"
        onClick={onSelect}
      >
        Explore financing for this business <ArrowRight size={17} />
      </button>
    </div>
  );
}
