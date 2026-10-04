import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";

const CLAIM_TYPES = [
  { value: "REFUND_NOT_RECEIVED", label: "Refund not received" },
  { value: "PAYMENT_NOT_REFLECTED", label: "Payment not reflected" },
  { value: "OVERPAYMENT", label: "Overpayment" },
  { value: "OTHER", label: "Other" },
];

export default function NewClaim() {
  const [params] = useSearchParams();
  const [claimType, setClaimType] = useState(CLAIM_TYPES[0].value);
  const [amountRupees, setAmountRupees] = useState("");
  const [reference, setReference] = useState(params.get("reference") ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const rupees = amountRupees.trim() === "" ? null : Number(amountRupees);
      if (rupees !== null && (Number.isNaN(rupees) || rupees < 0)) {
        setError("Claimed amount must be a non-negative number of rupees.");
        setBusy(false);
        return;
      }
      const created = await api.createCase({
        claim_type: claimType,
        claimed_amount_paise: rupees === null ? null : Math.round(rupees * 100),
        reference: reference.trim() || undefined,
        note: note.trim() || undefined,
      });
      navigate(`/cases/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create claim");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>New claim</h1>
      <div className="card" style={{ maxWidth: 560 }}>
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="claimType">Claim type</label>
            <select
              id="claimType"
              value={claimType}
              onChange={(e) => setClaimType(e.target.value)}
            >
              {CLAIM_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="amount">Claimed amount (₹, optional)</label>
            <input
              id="amount"
              type="number"
              min="0"
              step="0.01"
              placeholder="e.g. 500"
              value={amountRupees}
              onChange={(e) => setAmountRupees(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="reference">Reference (order ref / txn id, optional)</label>
            <input
              id="reference"
              type="text"
              placeholder="e.g. ORD-3000-RAM"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="note">Note (optional)</label>
            <textarea
              id="note"
              placeholder="Anything the customer told you…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create claim"}
          </button>
        </form>
      </div>
    </div>
  );
}
