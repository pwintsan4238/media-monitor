import { CheckCircle2, CircleDashed, ShieldAlert, TriangleAlert, XCircle } from "lucide-react";

const MAP = {
  ok: { label: "Monitored", cls: "bg-ok-soft text-ok", Icon: CheckCircle2 },
  degraded: { label: "Degraded", cls: "bg-warn-soft text-warn", Icon: TriangleAlert },
  failing: { label: "Failing", cls: "bg-bad-soft text-bad", Icon: XCircle },
  limited: { label: "Limited", cls: "bg-warn-soft text-warn", Icon: ShieldAlert },
  unknown: { label: "Not checked", cls: "bg-surface text-soft", Icon: CircleDashed },
} as const;

// Status is always icon + text, never colour alone.
export default function StatusPill({ health, label }: { health: string; label?: string }) {
  const m = MAP[health as keyof typeof MAP] ?? MAP.unknown;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${m.cls}`}>
      <m.Icon aria-hidden="true" className="size-3.5" />
      {label ?? m.label}
    </span>
  );
}
