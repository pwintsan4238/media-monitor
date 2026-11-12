"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Wordmark } from "@/components/AppShell";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid flex-1 lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-ink p-12 text-paper lg:flex">
        <span className="font-display text-xl font-semibold">Media Monitor</span>
        <div>
          <p className="font-display text-4xl font-medium">
            One search across the news sources you trust.
          </p>
          <p className="mt-4 max-w-md text-paper/70">
            Every result links to its original article. Press briefs cite only what has been indexed.
          </p>
        </div>
        <p className="text-sm text-paper/50">Burmese and English</p>
      </aside>

      <main id="main" className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <Wordmark className="lg:hidden" />
          <h1 className="mt-6 text-3xl font-semibold lg:mt-0">Sign in</h1>
          <p className="mt-1 text-soft">Access is limited to authorised users.</p>

          <form onSubmit={submit} className="mt-8 space-y-5" noValidate>
            <div>
              <label htmlFor="username" className="label">Username</label>
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
                aria-describedby={error ? "login-error" : undefined}
                className="field"
              />
            </div>
            <div>
              <label htmlFor="password" className="label">Password</label>
              <div className="relative">
                <input
                  id="password"
                  type={show ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  aria-describedby={error ? "login-error" : undefined}
                  className="field pr-12"
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? "Hide password" : "Show password"}
                  aria-pressed={show}
                  className="absolute right-1 top-1.5 grid size-10 cursor-pointer place-items-center rounded-md text-soft hover:text-ink"
                >
                  {show ? <EyeOff aria-hidden="true" className="size-4.5" /> : <Eye aria-hidden="true" className="size-4.5" />}
                </button>
              </div>
            </div>
            {error && (
              <p id="login-error" role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-sm text-bad">
                {error}
              </p>
            )}
            <button disabled={busy} className="btn btn-primary min-h-11 w-full">
              {busy && <Loader2 aria-hidden="true" className="size-4 animate-spin" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
