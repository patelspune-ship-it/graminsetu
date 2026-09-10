import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";

import { api, formatMoney } from "../api";
import { FUNDING_OPTIONS } from "../financeOffers";

function toFinanceInput({ label, note, ...offer }) {
  return offer;
}

const OFFER_META = Object.fromEntries(
  FUNDING_OPTIONS.map((offer) => [offer.id, offer])
);

export default function FundingStep({
  assessment,
  archetypeId,
  financingRequest,
  fundingResult,
  financialModel,
  onGenerated,
  onSelectOffer,
  onBack,
  onContinue,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectingId, setSelectingId] = useState(null);
  const [selectError, setSelectError] = useState("");

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const result = await api("/capital-stack", {
        method: "POST",
        body: JSON.stringify({
          assessment_id: assessment.id,
          archetype_id: archetypeId,
          available_for_project_paise: financingRequest.available_for_project_paise,
          assumptions: financingRequest.assumptions,
          offers: FUNDING_OPTIONS.map(toFinanceInput),
        }),
      });
      onGenerated(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!fundingResult) generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Which offer's numbers the report (DPR step) will actually use.
  const activeOfferId = financialModel?.snapshot?.stack?.offer_id ?? null;

  async function useForReport(offer) {
    setSelectingId(offer.id);
    setSelectError("");
    try {
      const result = await api("/financial-model", {
        method: "POST",
        body: JSON.stringify({
          assessment_id: assessment.id,
          archetype_id: archetypeId,
          available_for_project_paise: financingRequest.available_for_project_paise,
          finance: toFinanceInput(offer),
          assumptions: financingRequest.assumptions,
        }),
      });
      onSelectOffer(result);
    } catch (err) {
      setSelectError(err.message);
    } finally {
      setSelectingId(null);
    }
  }

  const feasible = fundingResult?.options.filter((option) => option.result.feasible) || [];
  const infeasible = fundingResult?.options.filter((option) => !option.result.feasible) || [];

  return (
    <section className="card fade-in">
      <p className="eyebrow">Step 05 / Funding options</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        Compare illustrative funding scenarios
      </h2>
      <p className="mt-2 text-base leading-6 text-stone-500">
        These are illustrative scenario terms, not confirmed lender offers.
        Feasibility is based on the same financial model as the previous step.
      </p>

      {error && (
        <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800">
          <p>{error}</p>
          <button
            type="button"
            onClick={generate}
            className="mt-3 inline-flex items-center gap-2 font-semibold"
          >
            <RefreshCw size={16} /> Try again
          </button>
        </div>
      )}

      {selectError && (
        <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800">
          {selectError}
        </div>
      )}

      {loading ? (
        <div className="mt-6 flex items-center gap-3 text-base text-stone-500">
          <LoaderCircle className="animate-spin" size={20} />
          Comparing funding scenarios…
        </div>
      ) : fundingResult ? (
        <>
          <p className="mt-6 text-base leading-6 text-stone-500">
            {fundingResult.ranking_policy}
          </p>
          <p className="mt-2 text-base leading-6 text-stone-500">
            Pick which offer the project report should use below — it does
            not have to be the one from the previous step.
          </p>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div>
              <h3 className="flex items-center gap-2 text-lg font-bold text-emerald-800">
                <CircleCheck size={19} /> Feasible ({feasible.length})
              </h3>
              <div className="mt-3 space-y-3">
                {feasible.length === 0 && (
                  <p className="text-base text-stone-500">
                    No offer is feasible under this scenario.
                  </p>
                )}
                {feasible.map((option) => (
                  <OfferCard
                    key={option.result.offer_id}
                    option={option}
                    isActive={option.result.offer_id === activeOfferId}
                    isSelecting={selectingId === option.result.offer_id}
                    onUse={() => useForReport(OFFER_META[option.result.offer_id])}
                  />
                ))}
              </div>
            </div>

            <div>
              <h3 className="flex items-center gap-2 text-lg font-bold text-red-800">
                <CircleAlert size={19} /> Not feasible ({infeasible.length})
              </h3>
              <div className="mt-3 space-y-3">
                {infeasible.length === 0 && (
                  <p className="text-base text-stone-500">
                    Every compared offer is feasible.
                  </p>
                )}
                {infeasible.map((option) => (
                  <OfferCard
                    key={option.result.offer_id}
                    option={option}
                    isActive={option.result.offer_id === activeOfferId}
                    isSelecting={selectingId === option.result.offer_id}
                    onUse={() => useForReport(OFFER_META[option.result.offer_id])}
                  />
                ))}
              </div>
            </div>
          </div>
        </>
      ) : null}

      <div className="mt-8 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
        <button type="button" className="btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} /> Back
        </button>

        <div className="flex flex-col items-end gap-2">
          {fundingResult && (
            <p className="text-base text-stone-500">
              Report will use:{" "}
              <span className="font-semibold text-stone-700">
                {activeOfferId
                  ? OFFER_META[activeOfferId]?.label || activeOfferId
                  : "the illustrative offer from the previous step"}
              </span>
            </p>
          )}

          <button
            type="button"
            className="btn-primary"
            disabled={!fundingResult}
            onClick={onContinue}
          >
            Continue to project report <ArrowRight size={17} />
          </button>
        </div>
      </div>
    </section>
  );
}

function OfferCard({ option, isActive, isSelecting, onUse }) {
  const meta = OFFER_META[option.result.offer_id];
  const { result } = option;

  return (
    <div
      className={`rounded-2xl border p-4 ${
        isActive
          ? "border-forest ring-1 ring-forest"
          : result.feasible
            ? "border-emerald-200 bg-emerald-50/40"
            : "border-red-200 bg-red-50/40"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-base font-bold">{meta?.label || option.result.offer_id}</h4>
        <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-base font-semibold text-stone-600">
          Rank {option.rank}
        </span>
      </div>

      {meta?.note && <p className="mt-1 text-base leading-6 text-stone-500">{meta.note}</p>}

      <dl className="mt-3 space-y-1 text-base leading-6">
        <Row label="Tenure" value={`${option.tenure_months} months`} />
        <Row label="Peak monthly debt service" value={formatMoney(result.max_monthly_debt_service_paise)} />
        <Row label="Total interest over horizon" value={formatMoney(result.total_interest_over_offer_horizon_paise)} />
        {result.pending_backended_subsidy_paise > 0 && (
          <Row
            label="Pending back-ended subsidy (not upfront)"
            value={formatMoney(result.pending_backended_subsidy_paise)}
          />
        )}
      </dl>

      {!result.feasible && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-base leading-6 text-red-800">
          {result.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className={`mt-3 inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-base font-semibold ${
          isActive
            ? "border-forest bg-forest text-white"
            : "border-stone-200 text-stone-600 hover:border-forest/40"
        }`}
        disabled={isSelecting}
        onClick={onUse}
      >
        {isSelecting ? (
          <>
            <LoaderCircle size={15} className="animate-spin" /> Updating…
          </>
        ) : isActive ? (
          <>
            <Check size={15} /> Used for report
          </>
        ) : (
          "Use this offer for the report"
        )}
      </button>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-stone-500">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  );
}
