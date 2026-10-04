import type { ReactNode } from "react";

interface StatProps {
  label: string;
  value: ReactNode;
}

export function Stat({ label, value }: StatProps) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}
