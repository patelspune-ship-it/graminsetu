import { useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  LoaderCircle,
} from "lucide-react";

import { api, formatMoney } from "../api";
import { archetypeName } from "../archetypes";

export default function DprStep({ archetypeId, financialModel, onBack, onStartNew }) {
  const [dpr, setDpr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const snapshot = financialModel.snapshot;

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const result = await api("/dpr/generate", {
        method: "POST",
        body: JSON.stringify({ session_id: financialModel.session_id }),
      });
      setDpr(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card fade-in">
      <p className="eyebrow">Step 06 / Detailed project report</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        Generate your report
      </h2>
      <p className="mt-2 text-base leading-6 text-stone-500">
        This builds a PDF summarising {archetypeName(archetypeId)} using the
        illustrative, unverified assumptions from the previous steps. It is
        not a loan application and implies no lender approval.
      </p>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <MiniStat label="Project cost" value={formatMoney(snapshot.project.project_cost_paise)} />
        <MiniStat label="Own contribution" value={formatMoney(snapshot.stack.own_contribution_paise)} />
        <MiniStat label="Term loan" value={formatMoney(snapshot.stack.term_loan_paise)} />
      </div>

      {error && (
        <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-base text-red-800">
          {error}
        </div>
      )}

      {dpr ? (
        <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <div className="flex items-center gap-3 text-emerald-900">
            <CheckCircle2 size={22} />
            <p className="text-lg font-bold">Report ready</p>
          </div>
          <a
            href={dpr.download_url}
            target="_blank"
            rel="noreferrer"
            className="btn-primary mt-4 w-full sm:w-auto"
          >
            <Download size={17} /> Download PDF
          </a>
        </div>
      ) : (
        <button
          type="button"
          className="btn-primary mt-6 w-full sm:w-auto"
          disabled={loading}
          onClick={generate}
        >
          {loading ? (
            <>
              <LoaderCircle size={17} className="animate-spin" />
              Generating report… this can take a moment
            </>
          ) : (
            <>
              <FileText size={17} /> Generate report
            </>
          )}
        </button>
      )}

      <div className="mt-8 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
        <button type="button" className="btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} /> Back
        </button>

        <button type="button" className="btn-secondary" onClick={onStartNew}>
          Start another assessment
        </button>
      </div>
    </section>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded-2xl border border-stone-200 p-4">
      <p className="text-base text-stone-500">{label}</p>
      <p className="mt-1 text-lg font-bold">{value}</p>
    </div>
  );
}
