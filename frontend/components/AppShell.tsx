"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut, Newspaper } from "lucide-react";
import { api, ApiError } from "@/lib/api";

type State =
  | { status: "loading" }
  | { status: "anon" }
  | { status: "authed"; username: string }
  | { status: "error"; message: string };

const NAV = [
  { href: "/", label: "Search" },
  { href: "/admin", label: "Admin" },
];

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <span className="grid size-8 place-items-center rounded-md bg-ink text-paper">
        <Newspaper aria-hidden="true" className="size-4.5" />
      </span>
      <span className="font-display text-xl font-semibold">Media Monitor</span>
    </span>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [state, setState] = useState<State>({ status: "loading" });
  const isLogin = pathname === "/login";

  useEffect(() => {
    let cancelled = false;
    api<{ username: string }>("/api/auth/me")
      .then((u) => !cancelled && setState({ status: "authed", username: u.username }))
      .catch((e: ApiError) => {
        if (cancelled) return;
        if (e.status === 401) setState({ status: "anon" });
        else setState({ status: "error", message: e.message });
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  useEffect(() => {
    if (state.status === "anon" && !isLogin) router.replace("/login");
    if (state.status === "authed" && isLogin) router.replace("/");
  }, [state, isLogin, router]);

  if (isLogin) return <div id="main" className="flex flex-1 flex-col">{children}</div>;

  if (state.status === "error")
    return (
      <main id="main" className="m-auto max-w-md p-8 text-center">
        <h1 className="text-2xl font-semibold">Service unavailable</h1>
        <p className="mt-2 text-soft">{state.message}</p>
        <button onClick={() => location.reload()} className="btn btn-secondary mt-5">Retry</button>
      </main>
    );

  if (state.status !== "authed")
    return (
      <main id="main" className="m-auto text-soft" aria-busy="true">
        Loading…
      </main>
    );

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    setState({ status: "anon" });
    router.replace("/login");
  }

  return (
    <>
      <header className="no-print sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-2.5 sm:gap-8">
          <Link href="/" aria-label="Media Monitor home"><Wordmark /></Link>
          <nav aria-label="Main" className="flex gap-1">
            {NAV.map((n) => {
              const active = n.href === "/" ? pathname === "/" || pathname.startsWith("/search") : pathname.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                    active ? "bg-accent-soft text-accent" : "text-soft hover:bg-surface hover:text-ink"
                  }`}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-2 text-sm text-soft">
            <span className="hidden sm:inline">{state.username}</span>
            <button onClick={logout} className="btn btn-ghost" aria-label="Sign out">
              <LogOut aria-hidden="true" className="size-4" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:py-12">
        {children}
      </main>
    </>
  );
}
