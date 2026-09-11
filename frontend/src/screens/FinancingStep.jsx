import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  IndianRupee,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";

import {
  api,
  formatBpsPercent,
  formatMoney,
  formatRatioDecimal,
  paiseToRupeeString,
  rupeesToPaise,
} from "../api";
import { archetypeName } from "../archetypes";
import { PRIMARY_FINANCE_OFFER, defaultAssumptions } from "../financeOffers";
import { useLanguage } from "../i18n/LanguageContext";
import ExplainInMyLanguage from "./ExplainInMyLanguage";

// First scheduled instalment outside the moratorium; illustrative only
// since a step-up offer recalculates the payment again after month 12.
function firstRepaymentInstalment(schedule) {
  return schedule.find((row) => row.phase !== "moratorium") || null;
}

// PS-mandated derivation, shown verbatim on screen: margin -> project cost
// -> loan eligibility -> routed scheme.
function psSchemeDerivation(snapshot, t) {
  if (snapshot.cost_model !== "ps_scheme" || !snapshot.scheme_route?.scheme) {
    return null;
  }

  const margin = snapshot.stack.own_contribution_paise;
  const { scheme } = snapshot.scheme_route;

  return t("financing.psSchemeDerivation", {
    margin: formatMoney(margin),
    cost: formatMoney(snapshot.project.project_cost_paise),
    loan: formatMoney(snapshot.stack.term_loan_paise),
    scheme: scheme.name,
  });
}

export default function FinancingStep({
  assessment,
  viabilityItem,
  financialModel,
  onGenerated,
  onBack,
  onContinue,
}) {
  const { t, language } = useLanguage();
  const capitalCapPaise = assessment.profile.own_capital_paise;
  const [capitalRupees, setCapitalRupees] = useState(
    paiseToRupeeString(capitalCapPaise)
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Applicant-chosen tenure/moratorium, overriding the routed scheme's own
  // default. Both stay null until the first successful generation seeds
  // them with that scheme's default (see runQuery below); `customizedRef`
  // then tracks whether the applicant has since moved away from it.
  const [tenureMonths, setTenureMonths] = useState(null);
  const [moratoriumMonths, setMoratoriumMonths] = useState(null);
  const [schemeDefault, setSchemeDefault] = useState(null);
  const customizedRef = useRef(false);
  const lastAvailablePaiseRef = useRef(null);
  const recomputeTimerRef = useRef(null);

  useEffect(() => () => clearTimeout(recomputeTimerRef.current), []);

  async function runQuery({ availablePaise, tenureOverrideMonths, moratoriumOverrideMonths }) {
    setLoading(true);
    setError("");
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
          tenure_override_months: tenureOverrideMonths,
          moratorium_override_months: moratoriumOverrideMonths,
        }),
      });

      lastAvailablePaiseRef.current = availablePaise;
      if (!customizedRef.current) {
        const offer = result.snapshot.finance_offer;
        setSchemeDefault({ tenure: offer.tenure_months, moratorium: offer.moratorium_months });
        setTenureMonths(offer.tenure_months);
        setMoratoriumMonths(offer.moratorium_months);
      }
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
        t("financing.capitalExceeds", { amount: formatMoney(capitalCapPaise) })
      );
      return;
    }

    await runQuery({
      availablePaise,
      tenureOverrideMonths: customizedRef.current ? tenureMonths : null,
      moratoriumOverrideMonths: customizedRef.current ? moratoriumMonths : null,
    });
  }

  // Debounced live recompute: fires while the applicant is still dragging
  // the tenure/moratorium controls, without re-submitting the capital form.
  function scheduleRecompute(nextTenureMonths, nextMoratoriumMonths) {
    if (lastAvailablePaiseRef.current === null) return;
    clearTimeout(recomputeTimerRef.current);
    recomputeTimerRef.current = setTimeout(() => {
      runQuery({
        availablePaise: lastAvailablePaiseRef.current,
        tenureOverrideMonths: nextTenureMonths,
        moratoriumOverrideMonths: nextMoratoriumMonths,
      });
    }, 350);
  }

  function handleTenureChange(rawValue) {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    const nextTenure = Math.min(360, Math.max(1, Math.round(value)));
    const nextMoratorium = Math.min(moratoriumMonths ?? 0, nextTenure - 1);
    customizedRef.current = true;
    setTenureMonths(nextTenure);
    setMoratoriumMonths(nextMoratorium);
    scheduleRecompute(nextTenure, nextMoratorium);
  }

  function handleMoratoriumChange(rawValue) {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    const maxMoratorium = Math.max(0, (tenureMonths ?? 1) - 1);
    const nextMoratorium = Math.min(maxMoratorium, Math.max(0, Math.round(value)));
    customizedRef.current = true;
    setMoratoriumMonths(nextMoratorium);
    scheduleRecompute(tenureMonths, nextMoratorium);
  }

  const snapshot = financialModel?.snapshot;
  const instalment = snapshot ? firstRepaymentInstalment(snapshot.stack.schedule) : null;
  const year1Surplus = snapshot
    ? Math.round(snapshot.surplus.slice(0, 12).reduce((sum, value) => sum + value, 0) / 12)
    : null;
  const derivation = snapshot ? psSchemeDerivation(snapshot, t) : null;

  return (
    <section className="card fade-in">
      <p className="eyebrow">{t("financing.eyebrow")}</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        {archetypeName(viabilityItem.archetype_id, language)}
      </h2>
      <p className="mt-2 text-base leading-6 text-stone-500">
        {t("financing.disclaimer")}
      </p>

      <form onSubmit={generate} className="mt-6 grid gap-5 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="project-capital">
            {t("financing.capitalLabel")}
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
            {t("financing.capitalHelp", { amount: formatMoney(capitalCapPaise) })}
          </p>
        </div>

        <div className="flex items-end">
          <button type="submit" className="btn-primary w-full" disabled={loading}>
            {loading ? (
              <>
                <LoaderCircle size={17} className="animate-spin" />
                {t("financing.calculating")}
              </>
            ) : financialModel ? (
              t("financing.recalculate")
            ) : (
              t("financing.generate")
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
          <ExplainInMyLanguage
            computedData={{
              archetype: archetypeName(viabilityItem.archetype_id),
              viability_score: viabilityItem.result.score,
              viability_verdict: viabilityItem.result.verdict,
              total_project_cost_paise: snapshot.project.project_cost_paise,
              own_contribution_paise: snapshot.stack.own_contribution_paise,
              term_loan_paise: snapshot.stack.term_loan_paise,
              cash_credit_paise: snapshot.stack.cash_credit_paise,
              feasible: snapshot.stack.feasible,
              infeasibility_reasons: snapshot.stack.reasons,
              monthly_instalment_paise: instalment ? instalment.payment_paise : null,
              average_monthly_surplus_year1_paise: year1Surplus,
              dscr_by_year: snapshot.dscr,
              warnings: snapshot.stack.warnings,
              assumption_status: financialModel.assumption_status,
            }}
            defaultLang={assessment.profile.preferred_language}
          />

          {!snapshot.stack.feasible && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-base leading-6 text-red-900">
              <p className="font-semibold">
                {t("financing.notFeasibleTitle")}
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {snapshot.stack.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}

          {derivation && (
            <div className="rounded-2xl border border-forest/30 bg-forest/5 p-4 text-base leading-6">
              <p className="font-semibold">{derivation}</p>
              <p className="mt-1 text-stone-500">
                {t("financing.interestTenureNote", {
                  rate: formatBpsPercent(snapshot.finance_offer.annual_rate_bps),
                  tenure: snapshot.finance_offer.tenure_months,
                  moratorium: snapshot.finance_offer.moratorium_months,
                })}
              </p>
            </div>
          )}

          {snapshot.cost_model === "ps_scheme" && schemeDefault && (
            <div className="rounded-2xl border border-stone-200 p-4">
              <h3 className="text-lg font-bold">{t("financing.tenureTitle")}</h3>
              <p className="mt-1 text-base leading-6 text-stone-500">
                {t("financing.tenureHelp")}
              </p>

              <div className="mt-4 grid gap-5 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="tenure-months">
                    {t("financing.loanTenure", { months: tenureMonths })}
                  </label>
                  <input
                    id="tenure-months"
                    type="range"
                    className="w-full"
                    min={1}
                    max={360}
                    step={1}
                    value={tenureMonths ?? 0}
                    disabled={loading}
                    onChange={(event) => handleTenureChange(event.target.value)}
                  />
                  <p className="mt-1 text-base leading-6 text-stone-500">
                    {t("financing.schemeDefaultTenure", { months: schemeDefault.tenure })}
                  </p>
                </div>

                <div>
                  <label className="label" htmlFor="moratorium-months">
                    {t("financing.moratoriumLabel", { months: moratoriumMonths })}
                  </label>
                  <input
                    id="moratorium-months"
                    type="range"
                    className="w-full"
                    min={0}
                    max={Math.max(0, (tenureMonths ?? 1) - 1)}
                    step={1}
                    value={moratoriumMonths ?? 0}
                    disabled={loading}
                    onChange={(event) => handleMoratoriumChange(event.target.value)}
                  />
                  <p className="mt-1 text-base leading-6 text-stone-500">
                    {t("financing.schemeDefaultMoratorium", { months: schemeDefault.moratorium })}
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <SummaryTile label={t("financing.tile.totalProjectCost")} value={formatMoney(snapshot.project.project_cost_paise)} />
            <SummaryTile label={t("financing.tile.ownContribution")} value={formatMoney(snapshot.stack.own_contribution_paise)} />
            <SummaryTile label={t("financing.tile.termLoanRequired")} value={formatMoney(snapshot.stack.term_loan_paise)} />
            <SummaryTile
              label={t("financing.tile.workingCapitalRequirement")}
              value={formatMoney(snapshot.project.working_capital.requirement_paise)}
              note={t("financing.tile.workingCapitalRequirementNote")}
            />
            <SummaryTile
              label={t("financing.tile.workingCapitalCashCredit")}
              value={formatMoney(snapshot.stack.cash_credit_paise)}
            />
            <SummaryTile
              label={t("financing.tile.monthlyInstalment")}
              value={instalment ? formatMoney(instalment.payment_paise) : t("financing.unknownNoRepayment")}
              note={
                instalment
                  ? t("financing.tile.monthlyInstalmentNote")
                  : null
              }
            />
            <SummaryTile
              label={t("financing.tile.avgMonthlySurplus")}
              value={year1Surplus !== null ? formatMoney(year1Surplus) : t("financing.unknown")}
              note={t("financing.tile.avgMonthlySurplusNote")}
            />
          </div>

          <div>
            <h3 className="text-lg font-bold">{t("financing.dscrTitle")}</h3>
            <div className="mt-3 overflow-x-auto rounded-2xl border border-stone-200">
              <table className="w-full min-w-[420px] text-left text-base">
                <thead className="bg-stone-50 text-stone-500">
                  <tr>
                    <th className="px-4 py-3 font-semibold">{t("financing.dscr.year")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.dscr.cashAvailable")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.dscr.debtService")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.dscr.dscr")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.dscr.meets125")}</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.dscr.map((row) => (
                    <tr key={row.year} className="border-t border-stone-100">
                      <td className="px-4 py-3">{row.year}</td>
                      <td className="px-4 py-3">{formatMoney(row.cash_available_paise)}</td>
                      <td className="px-4 py-3">{formatMoney(row.debt_service_paise)}</td>
                      <td className="px-4 py-3">
                        {row.ratio ? `${formatRatioDecimal(row.ratio)}×` : t("financing.unknownNoDebtService")}
                      </td>
                      <td className="px-4 py-3">
                        {row.meets_1_25 === null ? t("financing.unknown") : row.meets_1_25 ? t("financing.yes") : t("financing.no")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h3 className="text-lg font-bold">{t("financing.opCostsTitle")}</h3>
            <p className="mt-1 text-base leading-6 text-stone-500">
              {t("financing.opCostsSub")}
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <SummaryTile
                label={t("financing.opCosts.monthlyRevenue")}
                value={formatMoney(snapshot.operational_costs.monthly_revenue_paise)}
              />
              <SummaryTile
                label={t("financing.opCosts.monthlyVariableCost")}
                value={formatMoney(snapshot.operational_costs.monthly_variable_cost_paise)}
              />
              <SummaryTile
                label={t("financing.opCosts.monthlyFixedCost")}
                value={formatMoney(snapshot.operational_costs.monthly_fixed_cost_paise)}
              />
              <SummaryTile
                label={t("financing.opCosts.totalMonthlyOperatingCost")}
                value={formatMoney(snapshot.operational_costs.monthly_total_operating_cost_paise)}
              />
            </div>
          </div>

          <div>
            <h3 className="text-lg font-bold">{t("financing.quarterlyTitle")}</h3>
            <p className="mt-1 text-base leading-6 text-stone-500">
              {t("financing.quarterlySub", { count: snapshot.quarterly_schedule.length })}
            </p>
            <div className="mt-3 max-h-80 overflow-y-auto overflow-x-auto rounded-2xl border border-stone-200">
              <table className="w-full min-w-[560px] text-left text-base">
                <thead className="sticky top-0 bg-stone-50 text-stone-500">
                  <tr>
                    <th className="px-4 py-3 font-semibold">{t("financing.qtr.qtr")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.qtr.opening")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.qtr.interestPaid")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.qtr.principalPaid")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.qtr.payment")}</th>
                    <th className="px-4 py-3 font-semibold">{t("financing.qtr.closing")}</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.quarterly_schedule.map((row) => (
                    <tr key={row.quarter} className="border-t border-stone-100">
                      <td className="px-4 py-3">{row.quarter}</td>
                      <td className="px-4 py-3">{formatMoney(row.opening_paise)}</td>
                      <td className="px-4 py-3">{formatMoney(row.interest_paid_paise)}</td>
                      <td className="px-4 py-3">{formatMoney(row.principal_paid_paise)}</td>
                      <td className="px-4 py-3">{formatMoney(row.payment_paise)}</td>
                      <td className="px-4 py-3">{formatMoney(row.closing_paise)}</td>
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
              {t("financing.assumptionStatus", {
                status: financialModel.assumption_status.replace(/_/g, " "),
              })}
              {" "}
              {t("financing.assumptionNote")}
            </p>
          </div>
        </div>
      )}

      <div className="mt-8 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
        <button type="button" className="btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} /> {t("common.back")}
        </button>

        <button
          type="button"
          className="btn-primary"
          disabled={!financialModel}
          onClick={onContinue}
        >
          {t("financing.compareFunding")} <ArrowRight size={17} />
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
