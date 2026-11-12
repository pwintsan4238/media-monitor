import { Search } from "lucide-react";
import SourceList from "@/components/SourceList";

// Suggestions are search prompts only, not article content.
const TRY = ["Myanmar economy", "စီးပွားရေး", "\"fuel price\"", "ရွေးကောက်ပွဲ"];

export default function Home() {
  return (
    <div className="mx-auto max-w-3xl">
      <p className="eyebrow">Media intelligence</p>
      <h1 className="mt-3 text-4xl font-semibold sm:text-5xl">Search the monitored sources</h1>
      <p className="mt-4 max-w-2xl text-lg text-soft">
        Keyword search across a fixed set of Burmese-language news sites, with press briefs grounded
        in the indexed articles.
      </p>

      <form action="/search" role="search" className="mt-8">
        <label htmlFor="q" className="sr-only">Search keywords</label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search aria-hidden="true" className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-soft" />
            <input
              id="q"
              name="q"
              type="search"
              autoComplete="off"
              placeholder='Keywords, "exact phrase", AND / OR / NOT'
              className="field mt-0 min-h-14 pl-12 text-lg"
            />
          </div>
          <button className="btn btn-primary min-h-14 px-8 text-base">Search</button>
        </div>
      </form>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-soft">Try:</span>
        {TRY.map((t) => (
          <a
            key={t}
            href={`/search?q=${encodeURIComponent(t)}`}
            className="min-h-8 rounded-full border border-line-strong px-3 py-1 hover:bg-surface"
          >
            {t}
          </a>
        ))}
      </div>

      <h2 className="eyebrow mt-14 mb-4 font-sans">Sources</h2>
      <SourceList />
    </div>
  );
}
