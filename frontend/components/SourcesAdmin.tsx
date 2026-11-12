"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, Loader2, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import StatusPill from "@/components/StatusPill";

type Source = {
  id: number;
  name: string;
  description: string;
  base_url: string;
  rss_url: string | null;
  sitemap_url: string | null;
  method: "rss" | "sitemap";
  language: string;
  enabled: boolean;
  crawl_interval_minutes: number;
  scrape_config: Record<string, unknown>;
  robots_status: string;
  health: string;
  health_note: string | null;
  consecutive_failures: number;
  last_success_at: string | null;
  last_error: string | null;
  article_count: number;
};

type TestResult = {
  robots_status: string;
  method: string | null;
  total: number;
  with_title: number;
  with_date: number;
  with_content: number;
  errors: string[];
  sample: { url: string; title: string | null; published_at: string | null; has_content: boolean }[];
};

type CrawlRun = {
  id: number;
  status: "running" | "success" | "partial" | "failed";
  discovered: number;
  new: number;
  updated: number;
  errors: number;
  stats: Record<string, number | string | null>;
  log: string;
};

type Form = {
  name: string; description: string; base_url: string; rss_url: string; sitemap_url: string;
  method: "rss" | "sitemap"; language: string; enabled: boolean; crawl_interval_minutes: number | string;
  scrape_config: string;
};

const blank: Form = {
  name: "", description: "", base_url: "", rss_url: "", sitemap_url: "", method: "rss",
  language: "my", enabled: true, crawl_interval_minutes: 60, scrape_config: "{}",
};

const hasBurmese = (s: string) => /[က-႟]/.test(s);
const when = (d: string | null) => (d ? new Date(d).toLocaleString() : "Never");

export default function SourcesAdmin() {
  const [rows, setRows] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<
    { name: string; kind: "test"; data: TestResult } | { name: string; kind: "crawl"; run: CrawlRun } | null
  >(null);
  const [editing, setEditing] = useState<{ id: number | null; form: Form } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Source[]>("/api/admin/sources").then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setEditing(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing]);

  const toForm = (s: Source): Form => ({
    name: s.name, description: s.description, base_url: s.base_url, rss_url: s.rss_url ?? "",
    sitemap_url: s.sitemap_url ?? "", method: s.method, language: s.language, enabled: s.enabled,
    crawl_interval_minutes: s.crawl_interval_minutes, scrape_config: JSON.stringify(s.scrape_config, null, 2),
  });

  async function save(id: number | null, f: Form) {
    let cfg: unknown;
    try {
      cfg = JSON.parse(f.scrape_config || "{}");
    } catch {
      throw new Error("Advanced options must be valid JSON");
    }
    const body = JSON.stringify({
      ...f, rss_url: f.rss_url || null, sitemap_url: f.sitemap_url || null, scrape_config: cfg,
      crawl_interval_minutes: Number(f.crawl_interval_minutes),
    });
    await api(id ? `/api/admin/sources/${id}` : "/api/admin/sources", { method: id ? "PUT" : "POST", body });
    load();
  }

  async function run(s: Source, kind: "test" | "crawl") {
    setBusy(`${kind}-${s.id}`);
    setError(null);
    try {
      if (kind === "test") {
        const data = await api<TestResult>(`/api/admin/sources/${s.id}/test`, { method: "POST" });
        setResult({ name: s.name, kind: "test", data });
      } else {
        // Crawls run on the server in the background; poll until finished (up to ~20 min).
        const { run_id } = await api<{ run_id: number }>(`/api/admin/sources/${s.id}/crawl`, { method: "POST" });
        for (let i = 0; i < 600; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const run = await api<CrawlRun>(`/api/admin/crawl-runs/${run_id}`);
          if (run.status !== "running") {
            setResult({ name: s.name, kind: "crawl", run });
            break;
          }
          if (i % 5 === 4) load(); // refresh article counts while it works
        }
      }
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(null);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setFormError(null);
    try {
      await save(editing.id, editing.form);
      setEditing(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function remove(s: Source) {
    const extra = s.article_count ? ` and its ${s.article_count} indexed articles` : "";
    if (!confirm(`Permanently delete "${s.name}"${extra}? This cannot be undone.`)) return;
    try {
      await api(`/api/admin/sources/${s.id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const set = (k: keyof Form, v: string | number | boolean) =>
    setEditing((e) => (e ? { ...e, form: { ...e.form, [k]: v } } : e));

  return (
    <section aria-labelledby="sources-h">
      <div className="flex items-center gap-3">
        <h2 id="sources-h" className="text-2xl font-semibold">Sources</h2>
        <button
          onClick={() => { setFormError(null); setEditing({ id: null, form: { ...blank } }); }}
          className="btn btn-primary ml-auto"
        >
          <Plus aria-hidden="true" className="size-4" /> Add source
        </button>
      </div>

      {error && <p role="alert" className="mt-4 rounded-md bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
      {!rows && !error && (
        <ul className="mt-5 space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => <li key={i} className="card h-28 animate-pulse bg-surface" />)}
        </ul>
      )}
      {rows && rows.length === 0 && (
        <div className="card mt-5 p-8 text-center text-soft">
          No sources yet. Add one, or run <code>python -m app.seed</code>.
        </div>
      )}

      <ul className="mt-5 space-y-3">
        {rows?.map((s) => (
          <li key={s.id} className={`card p-4 ${s.enabled ? "" : "bg-surface"}`}>
            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
              <div className="min-w-0 flex-1 basis-64">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-sans text-base font-semibold">{s.name}</h3>
                  <StatusPill health={s.health} />
                  {!s.enabled && <span className="rounded-full bg-line px-2 py-0.5 text-xs text-soft">Disabled</span>}
                </div>
                <a href={s.base_url} target="_blank" rel="noreferrer" className="break-all text-sm text-accent underline-offset-2 hover:underline">
                  {s.base_url}
                </a>
                {s.health_note && <p className="mt-1 text-sm text-soft">{s.health_note}</p>}
              </div>

              <dl className="grid grid-cols-3 gap-x-6 text-sm">
                <div><dt className="text-xs text-soft">Method</dt><dd className="font-medium uppercase">{s.method}</dd></div>
                <div><dt className="text-xs text-soft">robots.txt</dt><dd className="font-medium">{s.robots_status.replace("_", " ")}</dd></div>
                <div><dt className="text-xs text-soft">Articles</dt><dd className="font-medium tabular-nums">{s.article_count.toLocaleString()}</dd></div>
              </dl>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
              <span className="mr-auto text-xs text-soft">Last success: {when(s.last_success_at)}</span>
              <button
                role="switch"
                aria-checked={s.enabled}
                aria-label={`${s.enabled ? "Disable" : "Enable"} ${s.name}`}
                onClick={() => save(s.id, { ...toForm(s), enabled: !s.enabled }).catch((e) => setError(e.message))}
                className={`relative h-6 w-11 cursor-pointer rounded-full transition-colors ${s.enabled ? "bg-accent" : "bg-line-strong"}`}
              >
                <span className={`absolute top-0.5 size-5 rounded-full bg-paper shadow transition-all ${s.enabled ? "left-5.5" : "left-0.5"}`} />
              </button>
              <button disabled={!!busy} onClick={() => run(s, "test")} className="btn btn-secondary">
                {busy === `test-${s.id}` ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <FlaskConical aria-hidden="true" className="size-4" />}
                Test
              </button>
              <button disabled={!!busy} onClick={() => run(s, "crawl")} className="btn btn-secondary">
                {busy === `crawl-${s.id}` ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="size-4" />}
                Crawl now
              </button>
              <button onClick={() => { setFormError(null); setEditing({ id: s.id, form: toForm(s) }); }} className="btn btn-ghost">
                <Pencil aria-hidden="true" className="size-4" /> Edit
              </button>
              <button onClick={() => remove(s)} className="btn btn-danger">
                <Trash2 aria-hidden="true" className="size-4" /> Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {result?.kind === "crawl" && (
        <section className="card mt-6 p-5" aria-live="polite" aria-label="Crawl result">
          <div className="flex items-start gap-3">
            <div>
              <p className="eyebrow">Crawl finished</p>
              <h3 className="mt-1 font-sans text-lg font-semibold">{result.name}</h3>
            </div>
            <button onClick={() => setResult(null)} className="btn btn-ghost ml-auto" aria-label="Close result">
              <X aria-hidden="true" className="size-4" />
            </button>
          </div>
          <p className={`mt-2 font-medium ${result.run.status === "failed" ? "text-bad" : ""}`}>
            {result.run.status === "failed"
              ? "Crawl failed: nothing could be collected."
              : `Stored ${result.run.new} new and ${result.run.updated} updated articles.`}
          </p>
          <p className="mt-1 text-sm text-soft">
            {result.run.discovered} found · {String(result.run.stats.unchanged ?? 0)} already up to date ·{" "}
            {String(result.run.stats.duplicates ?? 0)} duplicates skipped ·{" "}
            {String(result.run.stats.limited ?? 0)} headline-only
            {Number(result.run.stats.deferred) > 0 && ` · ${result.run.stats.deferred} more waiting for the next crawl`}
          </p>
          {result.run.log && (
            <ul className="mt-3 space-y-1">
              {result.run.log.split("\n").map((l, i) => (
                <li key={i} className="rounded-md bg-warn-soft px-3 py-1.5 text-sm text-warn">{l}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {result?.kind === "test" && (
        <section className="card mt-6 p-5" aria-live="polite" aria-label="Test result">
          <div className="flex items-start gap-3">
            <div>
              <p className="eyebrow">{result.kind === "test" ? "Dry run" : "Manual crawl"}</p>
              <h3 className="mt-1 font-sans text-lg font-semibold">{result.name}</h3>
            </div>
            <button onClick={() => setResult(null)} className="btn btn-ghost ml-auto" aria-label="Close result">
              <X aria-hidden="true" className="size-4" />
            </button>
          </div>

          {result.data.total > 0 ? (
            <p className="mt-2">
              Found <b>{result.data.total}</b> articles via <b className="uppercase">{result.data.method}</b>:{" "}
              {result.data.with_title} with titles, {result.data.with_date} with dates, {result.data.with_content} with full text in the feed.
            </p>
          ) : (
            <p className="mt-2 font-medium text-bad">No articles found.</p>
          )}
          <p className="mt-1 text-sm text-soft">
            {result.kind === "test"
              ? "Nothing was stored."
              : "Discovery only for now: article storage is not built yet, so nothing was indexed."}
          </p>
          {result.data.errors.map((e, i) => (
            <p key={i} className="mt-2 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">{e}</p>
          ))}

          {result.data.sample.length > 0 && (
            <ol className="mt-4 divide-y divide-line border-y border-line">
              {result.data.sample.map((a) => (
                <li key={a.url} className="py-3">
                  <a href={a.url} target="_blank" rel="noreferrer"
                     lang={a.title && hasBurmese(a.title) ? "my" : undefined}
                     className={`${a.title ? "mm-title" : "text-sm text-soft"} text-ink hover:text-accent`}>
                    {a.title ?? a.url}
                  </a>
                  <p className="text-xs text-soft">
                    {a.published_at ? new Date(a.published_at).toLocaleDateString() : "No date available"}
                    {!a.title && " · title will be extracted from the page"}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      {editing && (
        <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-ink/40 p-4"
             role="dialog" aria-modal="true" aria-labelledby="edit-h"
             onMouseDown={(e) => e.target === e.currentTarget && setEditing(null)}>
          <form onSubmit={submit} className="card my-8 w-full max-w-xl p-6 shadow-xl">
            <div className="flex items-center">
              <h3 id="edit-h" className="text-2xl font-semibold">{editing.id ? "Edit source" : "Add source"}</h3>
              <button type="button" onClick={() => setEditing(null)} className="btn btn-ghost ml-auto" aria-label="Cancel">
                <X aria-hidden="true" className="size-4" />
              </button>
            </div>

            <div className="mt-5 grid gap-4">
              <div>
                <label htmlFor="f-name" className="label">Name</label>
                <input id="f-name" required autoFocus className="field" value={editing.form.name} onChange={(e) => set("name", e.target.value)} />
              </div>
              <div>
                <label htmlFor="f-base" className="label">Website URL</label>
                <input id="f-base" required type="url" className="field" placeholder="https://example.org" value={editing.form.base_url} onChange={(e) => set("base_url", e.target.value)} />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="f-rss" className="label">RSS feed URL</label>
                  <input id="f-rss" type="url" className="field" value={editing.form.rss_url} onChange={(e) => set("rss_url", e.target.value)} />
                  <p className="hint">Optional. Preferred when available.</p>
                </div>
                <div>
                  <label htmlFor="f-sm" className="label">Sitemap URL</label>
                  <input id="f-sm" type="url" className="field" value={editing.form.sitemap_url} onChange={(e) => set("sitemap_url", e.target.value)} />
                  <p className="hint">Optional. Used if there is no feed.</p>
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="f-method" className="label">Preferred method</label>
                  <select id="f-method" className="field" value={editing.form.method} onChange={(e) => set("method", e.target.value)}>
                    <option value="rss">RSS feed</option>
                    <option value="sitemap">Sitemap</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="f-int" className="label">Crawl every (minutes)</label>
                  <input id="f-int" type="number" min={5} className="field" value={editing.form.crawl_interval_minutes} onChange={(e) => set("crawl_interval_minutes", e.target.value)} />
                </div>
              </div>
              <div>
                <label htmlFor="f-desc" className="label">Description</label>
                <textarea id="f-desc" rows={2} className="field py-2" value={editing.form.description} onChange={(e) => set("description", e.target.value)} />
              </div>
              <details className="rounded-md border border-line p-3">
                <summary className="cursor-pointer text-sm font-medium">Advanced options</summary>
                <label htmlFor="f-cfg" className="label mt-3">Sitemap tuning (JSON)</label>
                <textarea id="f-cfg" rows={5} className="field py-2 font-mono text-sm" value={editing.form.scrape_config} onChange={(e) => set("scrape_config", e.target.value)} />
                <p className="hint">Keys: url_include, child_order, sort, max_child_sitemaps</p>
              </details>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4" checked={editing.form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
                Enabled for crawling
              </label>
            </div>

            {formError && <p role="alert" className="mt-4 rounded-md bg-bad-soft px-3 py-2 text-sm text-bad">{formError}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" onClick={() => setEditing(null)} className="btn btn-secondary">Cancel</button>
              <button className="btn btn-primary">Save</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
