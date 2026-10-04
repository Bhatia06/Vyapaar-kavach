import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  api,
  ApiError,
  type CandidateOut,
  type CaseOut,
  type PaymentDetail,
  type Recommendation,
  type RefundOut,
  type TimelineItem,
} from "../api";
import { useAuth } from "../auth";
import { Badge } from "../components/Badge";
import { Stat } from "../components/Stat";
import { formatPaise, formatTime, humanize } from "../format";

export default function CaseDetail() {
  const { id = "" } = useParams();
  const { me } = useAuth();

  const [caseData, setCaseData] = useState<CaseOut | null>(null);
  const [payment, setPayment] = useState<PaymentDetail | null>(null);
  const [candidates, setCandidates] = useState<CandidateOut[]>([]);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [reco, setReco] = useState<Recommendation | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [refreshBusy, setRefreshBusy] = useState(false);
  const [providerDown, setProviderDown] = useState(false);

  const [noteText, setNoteText] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);

  const [resolution, setResolution] = useState("");
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [staleVersion, setStaleVersion] = useState(false);

  const [exportMd, setExportMd] = useState<string | null>(null);
  const [exportSha, setExportSha] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const canResolve = me?.role === "owner";
  const canExport = me?.role === "owner" || me?.role === "researcher";

  const loadCase = useCallback(async () => {
    const c = await api.case(id);
    setCaseData(c);
    if (c.match_status === "MATCHED" && c.payment_id) {
      setPayment(await api.payment(c.payment_id));
    }
    if (c.match_status === "UNMATCHED") {
      setCandidates(await api.matchCandidates(id));
    }
    return c;
  }, [id]);

  const loadTimeline = useCallback(async () => {
    setTimeline(await api.timeline(id));
  }, [id]);

  const loadReco = useCallback(async () => {
    setReco(await api.recommendation(id));
  }, [id]);

  useEffect(() => {
    setLoadError(null);
    Promise.all([loadCase(), loadTimeline(), loadReco()]).catch((err) =>
      setLoadError(err instanceof ApiError ? err.message : "Failed to load case")
    );
  }, [loadCase, loadTimeline, loadReco]);

  async function confirmMatch(paymentId: string) {
    try {
      const updated = await api.matchCase(id, paymentId);
      setCaseData(updated);
      if (updated.payment_id) setPayment(await api.payment(updated.payment_id));
      await Promise.all([loadTimeline(), loadReco()]);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Match failed");
    }
  }

  async function refreshFromProvider() {
    if (!caseData?.payment_id) return;
    setRefreshBusy(true);
    setProviderDown(false);
    try {
      const res = await api.refreshPayment(caseData.payment_id);
      setPayment({ ...res.payment, refunds: res.refunds } as PaymentDetail);
      await Promise.all([loadCase(), loadTimeline(), loadReco()]);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setProviderDown(true);
      } else {
        setLoadError(err instanceof ApiError ? err.message : "Refresh failed");
      }
    } finally {
      setRefreshBusy(false);
    }
  }

  async function addNote() {
    if (!noteText.trim()) return;
    setNoteError(null);
    try {
      await api.addNote(id, noteText.trim());
      setNoteText("");
      await loadTimeline();
    } catch (err) {
      setNoteError(err instanceof ApiError ? err.message : "Failed to add note");
    }
  }

  async function resolveCase() {
    if (!caseData || !resolution.trim()) return;
    setResolveError(null);
    setStaleVersion(false);
    try {
      const updated = await api.resolveCase(id, resolution.trim(), caseData.version);
      setCaseData(updated);
      setResolution("");
      await loadTimeline();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setStaleVersion(true);
        const fresh = await api.case(id);
        setCaseData(fresh);
      } else if (err instanceof ApiError && err.status === 403) {
        setResolveError("Only the owner role can resolve cases.");
      } else {
        setResolveError(err instanceof ApiError ? err.message : "Resolve failed");
      }
    }
  }

  async function exportCase() {
    setExportError(null);
    try {
      const exp = await api.createExport(id);
      setExportSha(exp.sha256);
      const md = await api.exportText(exp.export_id, "md");
      setExportMd(md);
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : "Export failed");
    }
  }

  async function downloadJson() {
    setExportError(null);
    try {
      const exp = await api.createExport(id);
      setExportSha(exp.sha256);
      const json = await api.exportText(exp.export_id, "json");
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `case-${id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : "Download failed");
    }
  }

  if (loadError) {
    return (
      <div className="page">
        <div className="alert alert-error">{loadError}</div>
        <Link to="/" className="btn btn-outline">
          Back to home
        </Link>
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="page">
        <p>
          <span className="spinner" /> Loading case…
        </p>
      </div>
    );
  }

  return (
    <div className="page">
      <p className="small">
        <Link to="/" style={{ color: "var(--indigo)" }}>
          ← Back to payments
        </Link>
      </p>

      {/* Header */}
      <div className="card">
        <div className="case-header">
          <Badge kind="status" value={caseData.claim_type} />
          <Badge kind="status" value={caseData.status} />
          <Badge kind="match" value={caseData.match_status} />
          {caseData.claimed_amount_paise != null && (
            <strong>{formatPaise(caseData.claimed_amount_paise)}</strong>
          )}
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          Created {formatTime(caseData.created_at)} by {caseData.created_by}
          {caseData.reference_text ? ` · Reference: ${caseData.reference_text}` : ""}
        </p>
        {caseData.status === "RESOLVED" && (
          <div className="alert alert-info" style={{ marginTop: 12 }}>
            <strong>Resolved</strong>
            {caseData.resolved_at ? ` on ${formatTime(caseData.resolved_at)}` : ""}
            {caseData.resolved_by ? ` by ${caseData.resolved_by}` : ""}
            {caseData.resolution_text && (
              <>
                <br />
                {caseData.resolution_text}
              </>
            )}
          </div>
        )}
      </div>

      {/* Match candidates */}
      {caseData.match_status === "UNMATCHED" && (
        <div className="card">
          <h2>Match candidates</h2>
          {candidates.length === 0 && (
            <p className="muted small">No candidate payments found for this claim yet.</p>
          )}
          {candidates.map((cand) => (
            <div
              key={cand.payment_id}
              className="card"
              style={{ background: "#f8fafc", marginBottom: 10 }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                <strong>{cand.order_ref}</strong>
                <span className="mono small">{cand.provider_txn_id}</span>
                <Badge kind="status" value={cand.status} />
              </div>
              <p className="small" style={{ margin: "8px 0" }}>
                {formatPaise(cand.amount_paise)} {cand.currency} · created{" "}
                {formatTime(cand.created_at)}
              </p>
              <p className="small muted" style={{ margin: "8px 0" }}>
                Why suggested: {cand.reason}
              </p>
              <button
                className="btn btn-teal"
                onClick={() => void confirmMatch(cand.payment_id)}
              >
                Confirm match
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Payment + refunds */}
      {caseData.match_status === "MATCHED" && payment && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
            <h2>Matched payment</h2>
            <button
              className="btn btn-primary"
              disabled={refreshBusy}
              onClick={() => void refreshFromProvider()}
            >
              {refreshBusy ? "Refreshing…" : "Refresh from provider"}
            </button>
          </div>
          {providerDown && (
            <div className="alert alert-error">
              Provider unavailable — showing last verified state.
            </div>
          )}
          <div className="stat-grid">
            <Stat label="Order ref" value={payment.order_ref} />
            <Stat label="Amount" value={formatPaise(payment.amount_paise)} />
            <Stat
              label="Status"
              value={<Badge kind="status" value={payment.status} />}
            />
            <Stat
              label="Verification"
              value={<Badge kind="verification" value={payment.verification} />}
            />
            <Stat label="Last checked" value={formatTime(payment.last_checked_at)} />
            <Stat label="Provider txn" value={<span className="mono small">{payment.provider_txn_id}</span>} />
          </div>

          {payment.refunds.length > 0 && (
            <>
              <h2 style={{ marginTop: 18 }}>Refunds</h2>
              {payment.refunds.map((r: RefundOut) => (
                <div
                  key={r.id}
                  className="card"
                  style={{ background: "#f8fafc", marginBottom: 10 }}
                >
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                    <strong className="mono">{r.refund_ref}</strong>
                    <Badge kind="status" value={r.status} />
                  </div>
                  <p className="small" style={{ margin: "8px 0 0" }}>
                    {formatPaise(r.amount_paise)} {r.currency} · Origin: {humanize(r.origin)} ·
                    Last checked: {formatTime(r.last_checked_at)}
                  </p>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* Recommendation */}
      {reco && (
        <div className="card reco-panel">
          <h2>Recommendation</h2>
          <p style={{ fontSize: 16, margin: "4px 0" }}>
            <strong>Suggested action: {humanize(reco.action)}</strong>{" "}
            <span className="muted small">(policy {reco.policy_version})</span>
          </p>
          <p style={{ margin: "8px 0" }}>{reco.summary}</p>
          {reco.reason_codes.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              {reco.reason_codes.map((rc) => (
                <span key={rc} className="chip">
                  {rc}
                </span>
              ))}
            </div>
          )}
          {reco.missing_facts.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div className="small" style={{ fontWeight: 700 }}>
                Missing facts
              </div>
              <ul className="small" style={{ margin: "4px 0", paddingLeft: 20 }}>
                {reco.missing_facts.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="small muted" style={{ margin: 0 }}>
            Model used for this action: No · Execution allowed:{" "}
            <strong>No — read-only prototype</strong>
            {reco.provider_last_checked_at && (
              <> · Provider last checked: {formatTime(reco.provider_last_checked_at)}</>
            )}
          </p>
        </div>
      )}

      {/* Evidence timeline */}
      <div className="card">
        <h2>Evidence timeline</h2>
        {timeline.length === 0 ? (
          <p className="muted small">No timeline entries yet.</p>
        ) : (
          <table className="data timeline-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Kind</th>
                <th>Source</th>
                <th>Verification</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {[...timeline].reverse().map((t, i) => (
                <tr key={`${t.at}-${i}`}>
                  <td>{formatTime(t.at)}</td>
                  <td>{humanize(t.kind)}</td>
                  <td>
                    <Badge kind="source" value={t.source_kind} />
                  </td>
                  <td>
                    {t.verification_status ? (
                      <Badge kind="verification" value={t.verification_status} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="small">{t.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <h2 style={{ marginTop: 18 }}>Add a note</h2>
        {noteError && <div className="alert alert-error">{noteError}</div>}
        <div className="field">
          <textarea
            placeholder="Record what the customer said or what you checked…"
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
          />
        </div>
        <button className="btn btn-outline" onClick={() => void addNote()} disabled={!noteText.trim()}>
          Add note
        </button>
      </div>

      {/* Resolve (owner only) */}
      {canResolve && caseData.status === "OPEN" && (
        <div className="card">
          <h2>Resolve case</h2>
          {staleVersion && (
            <div className="alert alert-error">The case changed — please refresh.</div>
          )}
          {resolveError && <div className="alert alert-error">{resolveError}</div>}
          <div className="field">
            <label htmlFor="resolution">Resolution</label>
            <textarea
              id="resolution"
              placeholder="How this was resolved…"
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
            />
          </div>
          <button
            className="btn btn-primary"
            disabled={!resolution.trim()}
            onClick={() => void resolveCase()}
          >
            Mark resolved
          </button>
        </div>
      )}

      {/* Export (owner/researcher) */}
      {canExport && (
        <div className="card">
          <h2>Audit export</h2>
          {exportError && <div className="alert alert-error">{exportError}</div>}
          <div className="btn-row">
            <button className="btn btn-outline" onClick={() => void exportCase()}>
              Export markdown
            </button>
            <button className="btn btn-outline" onClick={() => void downloadJson()}>
              Download JSON
            </button>
          </div>
          {exportSha && (
            <p className="small mono" style={{ marginTop: 10 }}>
              sha256: {exportSha.slice(0, 16)}…
            </p>
          )}
          {exportMd && <pre className="export-md">{exportMd}</pre>}
        </div>
      )}
    </div>
  );
}
