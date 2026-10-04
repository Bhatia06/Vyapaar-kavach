import { humanize } from "../format";

type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

function toneFor(kind: "status" | "verification" | "source" | "match", value: string): Tone {
  const v = value.toUpperCase();
  if (kind === "status") {
    if (v === "SUCCEEDED" || v === "RESOLVED") return "ok";
    if (v === "PENDING" || v === "UNKNOWN") return "warn";
    if (v === "FAILED" || v === "NO_RECORD") return "bad";
    return "neutral";
  }
  if (kind === "verification") {
    if (v === "VERIFIED") return "ok";
    if (v === "STALE" || v === "CONFLICTED" || v === "UNVERIFIED") return "warn";
    return "neutral";
  }
  if (kind === "match") {
    if (v === "MATCHED") return "ok";
    if (v === "UNMATCHED") return "warn";
    return "neutral";
  }
  // source
  if (v === "PROVIDER_MOCK" || v === "MERCHANT_STATEMENT") return "info";
  if (v === "MODEL" || v === "SYNTHETIC") return "warn";
  return "neutral";
}

interface BadgeProps {
  value: string | null | undefined;
  kind?: "status" | "verification" | "source" | "match";
}

export function Badge({ value, kind = "status" }: BadgeProps) {
  if (!value) return <span className="badge badge-neutral">None</span>;
  const tone = toneFor(kind, value);
  return <span className={`badge badge-${tone}`}>{humanize(value)}</span>;
}
