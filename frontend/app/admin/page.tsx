import SourcesAdmin from "@/components/SourcesAdmin";

export default function Admin() {
  return (
    <div>
      <p className="eyebrow">Administration</p>
      <h1 className="mt-2 text-4xl font-semibold">Source management</h1>
      <p className="mt-3 mb-8 max-w-2xl text-soft">
        Configure the monitored sources. <b className="font-medium text-ink">Test</b> checks what a source
        offers without storing anything.
      </p>
      <SourcesAdmin />
    </div>
  );
}
