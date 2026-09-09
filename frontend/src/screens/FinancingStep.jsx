import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  IndianRupee,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";

import { api, formatMoney, formatRatioDecimal, rupeesToPaise } from "../api";
import { archetypeName } from "../archetypes";
import { PRIMARY_FINANCE_OFFER, defaultAssumptions } from "../financeOffers";

function paiseToRupeeString(paise) {
  const whole = Math.trunc(paise / 100);
  const cents = Math.abs(paise % 100);
  return cents ? `${whole}.${String(cents).padStart(2, "0")}` : String(whole);
}

// First scheduled instalment outside the moratorium; illustrative only
// since a step-up offer recalculates the payment again after month 12.
function firstRepaymentInstalment(schedule) {
  return schedule.find((row) => row.phase !== "moratorium") || null;
}

export default function FinancingStep({
  assessment,
  viabilityItem,
  financialModel,
  onGenerated,
  onBack,
  onContinue,
}) {
  const capitalCapPaise = assessment.profile.own_capital_paise;
  const [capitalRupees, setCapitalRupees] = useState(
    paiseToRupeeString(capitalCapPaise)
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function generate(event) {
    event.preventDefault();
    setError("");

    let availablePaise;
    try {
      availablePaise = rupeesToPaise(capitalRupees);
    } catch (err) {
      setError(err.message);
      return;
    }

    if (availablePaise > capitalCapPaise) {
      setError(
        `Project funds cannot exceed your recorded capital of ${formatMoney(capitalCapPaise)}.`
      );
      return;
    }

    setLoading(true);
    try {
      const assumptions = defaultAssumptions();
      const result = await api("/financial-model", {
        method: "POST",
        body: JSON.stringify({
          assessment_id: assessment.id,
          archetype_id: viabilityItem.archetype_id,
          available_for_project_paise: availablePaise,
          finance: PRIMARY_FINANCE_OFFER,
          assumptions,
        }),
      });
      onGenerated(result, {
        available_for_project_paise: availablePaise,
        assumptions,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const snapshot = financialModel?.snapshot;
  const instalment = snapshot ? firstRepaymentInstalment(snapshot.stack.schedule) : null;
  const year1Surplus = snapshot
    ? Math.round(snapshot.surplus.slice(0, 12).reduce((sum, value) => sum + value, 0) / 12)
    : null;

  return (
    <section className="card fade-in">
      <p className="eyebrow">Step 04 / Financial summary</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        {archetypeName(viabilityItem.archetype_id)}
      </h2>
      <p className="mt-2 text-base leading-6 text-stone-500">
        This is an illustrative, unverified scenario — not a loan offer or
        approval. Figures use a single illustrative finance term; compare
        alternatives in the next step.
      </p>

      <form onSubmit={generate} className="mt-6 grid gap-5 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="project-capital">
            Capital available for this project
          </label>
          <div className="relative">
            <span className="pointer-events-none absolute left-4 top-[21px] text-stone-500">
              ₹
            </span>
            <input
              id="project-capital"
              className="field !pl-9"
              inputMode="decimal"
              required
              maxLength={12}
              value={capitalRupees}
              onChange={(event) => setCapitalRupees(event.target.value)}
            />
          </div>
          <p className="mt-2 text-base leading-6 text-stone-500">
            Up to your recorded capital of {formatMoney(capitalCapPaise)}.
          </p>
        </div>

        <div className="flex items-end">
          <button type="submit" className="btn-primary w-full" disabled={loading}>
            {loading ? (
              <>
                <LoaderCircle size={17} className="animate-spin" />
                Calculating…
              </>
            ) : financialModel ? (
              "Recalculate"
            ) : (
              "Generate financial model"
            )}
          </button>
        </div>
      </form>

      {error && (
        <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800">
          {error}
        </div>
      )}

      {snapshot && (
        <div className="mt-7 space-y-5">
          {!snapshot.stack.feasible && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-base leading-6 text-red-900">
              <p className="font-semibold">
                This illustrative finance term is not feasible as modelled:
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {snapshot.stack.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <SummaryTile label="Total project cost" value={formatMoney(snapshot.project.project_cost_paise)} />
            <SummaryTile label="Your own contribution" value={formatMoney(snapshot.stack.own_contribution_paise)} />
            <SummaryTile label="Term loan required" value={formatMoney(snapshot.stack.term_loan_paise)} />
            <SummaryTile
              label="Working capital cash credit"
              value={formatMoney(snapshot.stack.cash_credit_paise)}
            />
            <SummaryTile
              label="Illustrative monthly instalment (EMI)"
              value={instalment ? formatMoney(instalment.payment_paise) : "Unknown — no repayment months in schedule"}
              note={
                instalment
                  ? "Step-up terms recalculate this instalment after month 12."
                  : null
              }
            />
            <SummaryTile
              label="Average monthly pre-debt surplus (Year 1)"
              value={year1Surplus !== null ? formatMoney(year1Surplus) : "Unknown"}
              note="Before term payments and cash-credit interest."
            />
          </div>

          <div>
            <h3 className="text-lg font-bold">Debt service coverage ratio (DSCR)</h3>
            <div className="mt-3 overflow-x-auto rounded-2xl border border-stone-200">
              <table className="w-full min-w-[420px] text-left text-base">
                <thead className="bg-stone-50 text-stone-500">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Year</th>
                    <th className="px-4 py-3 font-semibold">Cash available</th>
                    <th className="px-4 py-3 font-semibold">Debt service</th>
                    <th className="px-4 py-3 font-semibold">DSCR</th>
                    <th className="px-4 py-3 font-semibold">Meets 1.25×</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.dscr.map((row) => (
                    <tr key={row.year} className="border-t border-stone-100">
                      <td className="px-4 py-3">{row.year}</td>
                      <td className="px-4 py-3">{formatMoney(row.cash_available_paise)}</td>
                      <td className="px-4 py-3">{formatMoney(row.debt_service_paise)}</td>
                      <td className="px-4 py-3">
                        {row.ratio ? `${formatRatioDecimal(row.ratio)}×` : "Unknown — no debt service that year"}
                      </td>
                      <td className="px-4 py-3">
                        {row.meets_1_25 === null ? "Unknown" : row.meets_1_25 ? "Yes" : "No"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {snapshot.stack.warnings.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-base leading-6 text-stone-500">
              {snapshot.stack.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}

          <div className="flex items-start gap-3 rounded-xl bg-stone-50 p-4">
            <ShieldCheck size={19} className="mt-0.5 shrink-0 text-forest" />
            <p className="text-base leading-6 text-stone-500">
              Assumption status: {financialModel.assumption_status.replace(/_/g, " ")}.
              {" "}
              Owner drawings are assumed at ₹3,000/month and incremental working
              capital at ₹0/month for this scenario.
            </p>
          </div>
        </div>
      )}

      <div className="mt-8 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
        <button type="button" className="btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} /> Back
        </button>

        <button
          type="button"
          className="btn-primary"
          disabled={!financialModel}
          onClick={onContinue}
        >
          Compare funding options <ArrowRight size={17} />
        </button>
      </div>
    </section>
  );
}

function SummaryTile({ label, value, note }) {
  return (
    <div className="rounded-2xl border border-stone-200 p-4">
      <dt className="flex items-center gap-2 text-base text-stone-500">
        <IndianRupee size={15} /> {label}
      </dt>
      <dd className="mt-2 text-lg font-bold">{value}</dd>
      {note && <p className="mt-1 text-base leading-6 text-stone-500">{note}</p>}
    </div>
  );
}
