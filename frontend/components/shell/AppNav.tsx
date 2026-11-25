"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Briefcase, FileCheck2, FileText, LogOut, Plus, Settings, type LucideIcon } from "lucide-react";
import { auth } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, IconButton, buttonClass } from "@/components/ui/Button";
import { focusRing } from "@/components/ui/styles";
import { Logo } from "./Logo";

const LINKS = [
  { href: "/dashboard", label: "Tailored resumes" },
  { href: "/resumes", label: "Resumes" },
  { href: "/applications", label: "Applications" },
  { href: "/settings", label: "Settings" },
];

const TABS: { href: string; label: string; icon: LucideIcon; primary?: boolean }[] = [
  { href: "/dashboard", label: "Tailored", icon: FileCheck2 },
  { href: "/resumes", label: "Resumes", icon: FileText },
  { href: "/tailor/new", label: "New", icon: Plus, primary: true },
  { href: "/applications", label: "Tracker", icon: Briefcase },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    try {
      await auth.logout();
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center gap-6 px-4 sm:px-6">
          <Logo />
          <nav aria-label="Main" className="hidden md:block">
            <ul className="flex items-center gap-1">
              {LINKS.map((l) => (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    aria-current={isActive(l.href) ? "page" : undefined}
                    className={cx(
                      "rounded-lg px-3 py-2 text-sm transition-colors",
                      isActive(l.href) ? "bg-brand-50 font-medium text-brand-700" : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                      focusRing,
                    )}
                  >
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/tailor/new" className={cx(buttonClass("primary", "md"), "hidden md:inline-flex")}>
              <Plus className="h-4 w-4" aria-hidden />
              New tailoring
            </Link>
            <Button variant="ghost" onClick={logout} className="hidden lg:inline-flex">
              <LogOut className="h-4 w-4" aria-hidden />
              Sign out
            </Button>
            <IconButton label="Sign out" onClick={logout} className="lg:hidden">
              <LogOut className="h-5 w-5" aria-hidden />
            </IconButton>
          </div>
        </div>
      </header>

      <nav
        aria-label="Main, mobile"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        <ul className="grid grid-cols-5">
          {TABS.map((t) => {
            const active = isActive(t.href);
            return (
              <li key={t.href}>
                <Link
                  href={t.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "flex h-14 flex-col items-center justify-center gap-0.5 text-xs",
                    active ? "text-brand-700" : "text-ink-muted",
                    focusRing,
                    "focus-visible:ring-inset focus-visible:ring-offset-0",
                  )}
                >
                  {t.primary ? (
                    <span className="grid h-11 w-11 place-items-center rounded-full bg-brand-600 text-white shadow-card">
                      <t.icon className="h-5 w-5" aria-hidden />
                      <span className="sr-only">{t.label}</span>
                    </span>
                  ) : (
                    <>
                      <t.icon className="h-5 w-5" aria-hidden />
                      {t.label}
                    </>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}
