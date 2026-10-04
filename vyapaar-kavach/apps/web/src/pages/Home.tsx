import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, type CaseOut, type PaymentSummary } from "../api";
import { Badge } from "../components/Badge";
import { formatPaise, formatTime, humanize } from "../format";

export default function Home() {
  const [query, setQuery] = useState("");
  const [payments, setPayments] = useState<PaymentSummary[]>([]);
  const [searched, setSearched] = useState(false);
  const [paymentsError, setPaymentsError] = useState<string | null>(null);
  const [cases, setCases] = useState<CaseOut[]>([]);
  const [casesError, setCasesError] = useState<string | null>(null);
  const navigate = useNavigate();

  const loadCases = useCallback(async () => {
    try {
      setCases(await api.cases("OPEN"));
      setCasesError(null);
    } catch (err) {
      setCasesError(err instanceof ApiError ? err.message : "Failed to load claims");
    }
  }, []);

  useEffect(() => {
    void loadCases();
  }, [loadCases]);

  async function search(e?: FormEvent) {
    if (e) e.preventDefault();
    try {
      setPayments(await api.payments(query.trim()));
      setSearched(true);
      setPaymentsError(null);
    } catch (err) {
      setPaymentsError(err instanceof ApiError ? err.message : "Search failed");
    }
  }

  return (
    <div className="page">
      <h1>Payments &amp; claims</h1>
      <div className="grid-2col">
        <div>
          <div className="card">
            <h2>Search payments</h2>
            <form className="searchbar" onSubmit={search}>
              <input
                placeholder="Search by order ref, txn id, customer…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button className="btn btn-primary" type="submit">
                Search
              </button>
            </form>
            {paymentsError && <div className="alert alert-error">{paymentsError}</div>}
            {searched && payments.length === 0 && (
              <p className="muted small">No payments found.</p>
            )}
            {payments.length > 0 && (
              <table className="data">
                <thead>
                  <tr>
                    <th>Order ref</th>
                    <th>Txn ID</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Verification</th>
                    <th>Last checked</th>
                    <th>Customer</th>
                  </tr>
                </thead>
                <tbody>
                  {payments.map((p) => (
                    <tr
                      key={p.id}
                      className="clickable"
                      onClick={() =>
                        navigate(`/claims/new?reference=${encodeURIComponent(p.order_ref)}`)
                      }
                    >
                      <td>{p.order_ref}</td>
                      <td className="mono small">{p.provider_txn_id}</td>
                      <td>{formatPaise(p.amount_paise)}</td>
                      <td>
                        <Badge kind="status" value={p.status} />
                      </td>
                      <td>
                        <Badge kind="verification" value={p.verification} />
                      </td>
                      <td className="small">{formatTime(p.last_checked_at)}</td>
                      <td className="small">{p.customer_hint ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="muted small" style={{ marginTop: 10 }}>
              Tip: click a row to start a claim for that order reference.
            </p>
          </div>
        </div>
        <div>
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2>Open claims</h2>
              <Link className="btn btn-teal" to="/claims/new">
                + New claim
              </Link>
            </div>
            {casesError && <div className="alert alert-error">{casesError}</div>}
            {cases.length === 0 && !casesError && (
              <p className="muted small">No open claims right now.</p>
            )}
            {cases.map((c) => (
              <div key={c.id} style={{ borderTop: "1px solid var(--border)", padding: "10px 0" }}>
                <Link to={`/cases/${c.id}`} style={{ fontWeight: 600, color: "var(--indigo)" }}>
                  {humanize(c.claim_type)}
                </Link>
                <div className="small" style={{ marginTop: 3 }}>
                  <Badge kind="match" value={c.match_status} />{" "}
                  <span className="muted">
                    {formatPaise(c.claimed_amount_paise)} · {formatTime(c.created_at)}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="card">
            <h2>About this data</h2>
            <p className="small muted">
              Payment statuses are verified against the mock provider at login and on manual
              refresh. If a status was last checked a while ago it is marked{" "}
              <Badge kind="verification" value="STALE" /> and you should re-verify from the case
              screen before acting.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
