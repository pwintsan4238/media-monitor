"use client";

import { useEffect, useState } from "react";
import { api, SourceRow } from "@/lib/api";
import StatusPill from "@/components/StatusPill";

export default function SourceList() {
  const [rows, setRows] = useState<SourceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<SourceRow[]>("/api/sources").then(setRows).catch((e) => setError(e.message));
  }, []);

  if (error) return <p role="alert" className="text-bad">{error}</p>;
  if (!rows)
    return (
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading sources">
        {Array.from({ length: 6 }).map((_, i) => (
          <li key={i} className="card h-20 animate-pulse bg-surface" />
        ))}
      </ul>
    );
  if (rows.length === 0)
    return <p className="text-soft">No sources configured yet. Add them from the Admin page.</p>;

  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((s) => (
        <li key={s.id} className="card flex flex-col gap-2 p-4">
          <span className="font-medium">{s.name}</span>
          <div className="flex items-center justify-between gap-2">
            <StatusPill health={s.health} />
            <span className="text-sm tabular-nums text-soft">{s.article_count.toLocaleString()} articles</span>
          </div>
        </li>
      ))}
    </ul>
  );
}
