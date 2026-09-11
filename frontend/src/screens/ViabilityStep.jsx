import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  CircleHelp,
  LoaderCircle,
  MapPin,
  RefreshCw,
} from "lucide-react";

import { api, formatMoney, formatRatioPercent } from "../api";
import { archetypeName, SUB_SCORE_LABELS } from "../archetypes";

const VERDICT_TEXT_STYLES = {
  STRONG: "text-emerald-700",
  MODERATE: "text-amber-700",
  WEAK: "text-stone-600",
  INSUFFICIENT_DATA: "text-stone-500",
};

const STATUS_STYLES = {
  OK: "border-emerald-200 bg-emerald-50 text-emerald-900",
  PARTIAL_COVERAGE: "border-amber-200 bg-amber-50 text-amber-900",
  OUT_OF_COVERAGE: "border-red-200 bg-red-50 text-red-900",
};

// The five mini-metrics shown on every compact card, in a fixed order.
// market_gap is deliberately excluded here — it still appears in the
// expanded detail view alongside its full note.
const MINI_METRICS = [
  { key: "demand", short: "Demand" },
  { key: "inputs", short: "Input" },
  { key: "infrastructure", short: "Infra" },
  { key: "skills", short: "Skill" },
  { key: "capital", short: "Capital" },
];

function bpsToPercent(bps) {
  return `${(bps / 100).toFixed(bps % 100 === 0 ? 0 : 1)}%`;
}

function coverageBadgeStyle(bps) {
  if (bps >= 10_000) return "bg-emerald-100 text-emerald-800";
  if (bps >= 5_000) return "bg-amber-100 text-amber-800";
  return "bg-stone-200 text-stone-700";
}

function metricBarColor(pct) {
  if (pct >= 70) return "bg-emerald-500";
  if (pct >= 40) return "bg-amber-500";
  return "bg-red-400";
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
  const [expandedId, setExpandedId] = useState(null);

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

  const sorted = data ? sortItems(data.items) : [];
  const top3 = sorted.slice(0, 3);
  const rest = sorted.slice(3);

  function toggle(id) {
    setExpandedId((current) => (current === id ? null : id));
  }

  return (
    <section className="card fade-in">
      <p className="eyebrow">Step 03 / Business viability</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        What could work in {assessment.village.name}?
      </h2>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800"
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
            className={`mt-3 rounded-xl border px-3 py-2 text-sm leading-5 ${STATUS_STYLES[data.status]}`}
          >
            <span className="font-semibold">{data.status.replace(/_/g, " ")}.</span>{" "}
            {data.message}
          </div>

          {top3.length > 0 && (
            <div className="mt-4 space-y-2">
              {top3.map((item, index) => (
                <RankedCard
                  key={item.archetype_id}
                  rank={index + 1}
                  item={item}
                  expanded={expandedId === item.archetype_id}
                  onToggle={() => toggle(item.archetype_id)}
                  onSelect={() => onSelect(item, data)}
                />
              ))}
            </div>
          )}

          {rest.length > 0 && (
            <>
              <p className="mt-6 text-sm font-semibold uppercase tracking-wide text-stone-400">
                More options
              </p>
              <div className="mt-2 space-y-2">
                {rest.map((item, index) => (
                  <RankedCard
                    key={item.archetype_id}
                    rank={index + 4}
                    item={item}
                    expanded={expandedId === item.archetype_id}
                    onToggle={() => toggle(item.archetype_id)}
                    onSelect={() => onSelect(item, data)}
                  />
                ))}
              </div>
            </>
          )}

          {sorted.length === 0 && (
            <p className="mt-4 text-base text-stone-500">
              No archetype could be scored for this village yet.
            </p>
          )}

          <details className="mt-6 rounded-xl border border-stone-200 bg-stone-50 p-3 text-sm leading-6 text-stone-600">
            <summary className="cursor-pointer list-none font-semibold text-ink">
              About this ranking
            </summary>
            <div className="mt-2 space-y-2">
              <p className="flex items-start gap-2">
                <MapPin size={15} className="mt-0.5 shrink-0 text-forest" />
                {assessment.village.name}, {assessment.village.district}
              </p>
              <p className="flex items-start gap-2">
                <CircleHelp size={15} className="mt-0.5 shrink-0 text-forest" />
                <span>
                  <span className="font-semibold text-ink">Source: </span>
                  {assessment.village.source}
                </span>
              </p>
              <p>{data.capital_fit_basis}</p>
              {data.missing_archetype_ids.length > 0 && (
                <p>
                  <span className="font-semibold text-ink">No local data yet for: </span>
                  {data.missing_archetype_ids.map(archetypeName).join(", ")}
                </p>
              )}
            </div>
          </details>
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

function MiniMetric({ label, sub }) {
  const known = sub && sub.value !== null;
  const pct = known
    ? Math.round((sub.value.numerator / sub.value.denominator) * 100)
    : null;

  return (
    <div
      className="flex min-w-0 flex-1 flex-col items-center gap-1"
      title={sub ? SUB_SCORE_LABELS[sub.name] || sub.name : label}
    >
      <span className="text-[10px] font-medium leading-none text-stone-500">
        {label}
      </span>
      {known ? (
        <div className="h-1.5 w-full rounded-full bg-stone-200">
          {/* A real 0% still gets a visible sliver — an empty-looking bar
              would be indistinguishable from "no data" at a glance. */}
          <div
            className={`h-1.5 rounded-full ${metricBarColor(pct)}`}
            style={{ width: `${Math.max(pct, 8)}%` }}
          />
        </div>
      ) : (
        <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-stone-200 text-[9px] font-bold leading-none text-stone-500">
          ?
        </span>
      )}
    </div>
  );
}

function RankedCard({ rank, item, expanded, onToggle, onSelect }) {
  const { result } = item;
  const isKnown = result.score !== null;
  const byName = Object.fromEntries(result.sub_scores.map((sub) => [sub.name, sub]));

  const knownSubScores = result.sub_scores.filter((sub) => sub.value !== null);
  const unknownSubScores = result.sub_scores.filter((sub) => sub.value === null);

  return (
    <div
      className={`overflow-hidden rounded-2xl border transition ${
        expanded ? "border-forest/50 bg-forest/5" : "border-stone-200"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 p-3 text-left"
        aria-expanded={expanded}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-sm font-bold text-white">
          {rank}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="truncate text-sm font-bold text-ink">
              {archetypeName(item.archetype_id)}
            </h3>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${coverageBadgeStyle(result.evidence_coverage_bps)}`}
            >
              {bpsToPercent(result.evidence_coverage_bps)}
            </span>
          </div>

          <div className="mt-2 flex gap-2">
            {MINI_METRICS.map(({ key, short }) => (
              <MiniMetric key={key} label={short} sub={byName[key]} />
            ))}
          </div>
        </div>

        <ChevronDown
          size={16}
          className={`shrink-0 text-stone-400 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      {expanded && (
        <div className="border-t border-stone-100 p-4 pt-3">
          <p className="text-base text-stone-500">
            Illustrative own contribution: {formatMoney(item.required_own_contribution_paise)}
          </p>

          <p className="mt-3 text-base leading-6 text-stone-500">
            {isKnown ? (
              <>
                Verdict:{" "}
                <span className={`font-semibold ${VERDICT_TEXT_STYLES[result.verdict] || ""}`}>
                  {result.verdict.replace(/_/g, " ")}
                </span>{" "}
                · score {result.score}/100
              </>
            ) : (
              <>
                Score can't be pinned down yet — possible range{" "}
                <span className="font-semibold text-ink">
                  {result.lower_bound_score}–{result.upper_bound_score}
                </span>{" "}
                depending on the missing evidence below.
              </>
            )}
          </p>

          {knownSubScores.length > 0 && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {knownSubScores.map((sub) => (
                <div key={sub.name} className="rounded-xl bg-stone-50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-base font-semibold text-ink">
                      {SUB_SCORE_LABELS[sub.name] || sub.name}
                    </span>
                    <span className="text-base text-stone-500">
                      weight {bpsToPercent(sub.weight_bps)}
                    </span>
                  </div>

                  <p className="mt-1 text-base font-semibold">{formatRatioPercent(sub.value)}</p>

                  <p className="mt-1 text-base leading-6 text-stone-500">{sub.note}</p>
                </div>
              ))}
            </div>
          )}

          {unknownSubScores.length > 0 && (
            <details className="group mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-3">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-base font-semibold text-amber-900">
                <span>What we couldn't verify ({unknownSubScores.length})</span>
                <ChevronDown size={18} className="shrink-0 transition group-open:rotate-180" />
              </summary>

              <div className="mt-3 space-y-3">
                {unknownSubScores.map((sub) => (
                  <div key={sub.name} className="rounded-xl bg-white p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-base font-semibold text-ink">
                        {SUB_SCORE_LABELS[sub.name] || sub.name}
                      </span>
                      <span className="text-base text-stone-500">
                        weight {bpsToPercent(sub.weight_bps)}
                      </span>
                    </div>
                    <p className="mt-1 text-base leading-6 text-stone-500">{sub.note}</p>
                  </div>
                ))}
              </div>
            </details>
          )}

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
      )}
    </div>
  );
}
