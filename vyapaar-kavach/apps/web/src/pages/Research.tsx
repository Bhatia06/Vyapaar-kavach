import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type RunOut } from "../api";
import { useAuth } from "../auth";
import { Stat } from "../components/Stat";
import { formatTime } from "../format";

const SCENARIOS = [
  { id: "outage_on", label: "Outage ON" },
  { id: "outage_off", label: "Outage OFF" },
  { id: "refund_f1_succeeds", label: "Refund F1 succeeds" },
  { id: "delayed_pending_f1", label: "Delayed pending F1" },
];

function probClass(p: number): string {
  if (p < 0.33) return "prob prob-low";
  if (p < 0.66) return "prob prob-mid";
  return "prob prob-high";
}

export default function Research() {
  const { me } = useAuth();
  const canDemoControl = me?.role === "owner" || me?.role === "researcher";

  const [sampleSize, setSampleSize] = useState(64);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<RunOut | null>(null);
  const [runs, setRuns] = useState<RunOut[]>([]);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [controlMsg, setControlMsg] = useState<string | null>(null);
  const [controlError, setControlError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await api.researchRuns());
      setRunsError(null);
    } catch (err) {
      setRunsError(err instanceof ApiError ? err.message : "Failed to load runs");
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  async function runInference() {
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      const run = await api.runResearch("elliptic2_smurf_reproduction", sampleSize);
      // detail endpoint carries the summary
      const full = await api.researchRun(run.id);
      setResult(full);
      await loadRuns();
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : "Inference run failed");
    } finally {
      setRunning(false);
    }
  }

  async function demoControl(scenario: string) {
    setControlMsg(null);
    setControlError(null);
    try {
      const res = await api.demoControl(scenario);
      setControlMsg(res.effect ?? "OK");
    } catch (err) {
      setControlError(err instanceof ApiError ? err.message : "Demo control failed");
    }
  }

  const summary = result?.summary;

  return (
    <div className="page">
      <h1>Research</h1>

      <div className="card alert-info" style={{ borderLeft: "4px solid var(--indigo)" }}>
        <h2>Original-domain research engine</h2>
        <p className="small" style={{ marginBottom: 0 }}>
          GATv2 graph-attention model trained on Elliptic2 Bitcoin subgraphs. These scores are{" "}
          <strong>not</strong> merchant fraud verdicts — they reproduce a published research
          benchmark in a different domain. Merchant-case scoring abstains by design; case
          actions on this demo come from deterministic policy, not from this model.
        </p>
      </div>

      <div className="card">
        <h2>Run inference</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void runInference();
          }}
          style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="sampleSize">Sample size</label>
            <input
              id="sampleSize"
              type="number"
              min={1}
              max={2000}
              value={sampleSize}
              onChange={(e) => setSampleSize(Number(e.target.value))}
              style={{ width: 140 }}
              required
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={running}>
            Run inference
          </button>
        </form>
        {running && (
          <p style={{ marginTop: 12 }}>
            <span className="spinner" /> Running GATv2 inference on the mock dataset…
          </p>
        )}
        {runError && (
          <div className="alert alert-error" style={{ marginTop: 12 }}>
            {runError}
          </div>
        )}
      </div>

      {result && result.abstained && (
        <div className="card alert alert-warn" style={{ marginBottom: 18 }}>
          <h2>Abstained</h2>
          <p style={{ margin: 0 }}>
            {result.abstention_reason ?? "The engine abstained from this task."}
          </p>
        </div>
      )}

      {result && !result.abstained && summary && (
        <div className="card">
          <h2>Metrics</h2>
          <div className="stat-grid">
            <Stat label="Precision" value={summary.metrics.precision.toFixed(3)} />
            <Stat label="Recall" value={summary.metrics.recall.toFixed(3)} />
            <Stat label="F1" value={summary.metrics.f1.toFixed(3)} />
            <Stat label="Threshold" value={summary.threshold} />
            <Stat label="Device" value={summary.device} />
            <Stat label="Runtime" value={`${summary.runtime_ms} ms`} />
            <Stat label="Positives" value={`${summary.positives} / ${summary.sample_size}`} />
            <Stat label="Model" value={summary.model_version} />
          </div>
          <p className="small mono muted" style={{ marginTop: 10 }}>
            checkpoint sha256: {result.checkpoint_sha256.slice(0, 16)}… · dataset sha256:{" "}
            {result.dataset_sha256.slice(0, 16)}…
          </p>
          {summary.note && <p className="small muted">{summary.note}</p>}

          {summary.examples.length > 0 && (
            <>
              <h2 style={{ marginTop: 14 }}>Examples (first 10)</h2>
              <table className="data">
                <thead>
                  <tr>
                    <th>Graph index</th>
                    <th>P(suspicious)</th>
                    <th>True label</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.examples.slice(0, 10).map((ex) => (
                    <tr key={ex.graph_index}>
                      <td className="mono">{ex.graph_index}</td>
                      <td className={probClass(ex.prob_suspicious)}>
                        {ex.prob_suspicious.toFixed(3)}
                      </td>
                      <td>{ex.label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      <div className="card">
        <h2>Past runs</h2>
        {runsError && <div className="alert alert-error">{runsError}</div>}
        {runs.length === 0 && !runsError && <p className="muted small">No runs yet.</p>}
        {runs.length > 0 && (
          <table className="data">
            <thead>
              <tr>
                <th>Created</th>
                <th>Task</th>
                <th>Abstained</th>
                <th>Reason</th>
                <th>Runtime</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="small">{formatTime(r.created_at)}</td>
                  <td className="mono small">{r.task}</td>
                  <td>{r.abstained ? "Yes" : "No"}</td>
                  <td className="small">{r.abstention_reason ?? "—"}</td>
                  <td className="small">{r.runtime_ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {canDemoControl && (
        <div className="card">
          <h2>Demo controls</h2>
          <p className="small muted">
            Flip mock-provider scenarios used during the demo (owner / researcher only).
          </p>
          {controlMsg && <div className="alert alert-info">{controlMsg}</div>}
          {controlError && <div className="alert alert-error">{controlError}</div>}
          <div className="btn-row">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                className="btn btn-teal"
                onClick={() => void demoControl(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
