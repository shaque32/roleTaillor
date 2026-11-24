"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { LogOut, Menu, Plus, X } from "lucide-react";
import { auth } from "@/lib/api";
import { cx } from "@/lib/format";
import { buttonClass } from "@/components/ui/Button";
import { Logo } from "./Logo";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/resumes", label: "Resumes" },
  { href: "/applications", label: "Applications" },
  { href: "/settings", label: "Settings" },
];

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

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
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
      <nav className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6" aria-label="Main">
        <Logo />
        <ul className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <li key={l.href}>
              <Link
                href={l.href}
                aria-current={isActive(l.href) ? "page" : undefined}
                className={cx(
                  "rounded-md px-3 py-1.5 text-sm",
                  isActive(l.href) ? "bg-slate-100 font-medium text-ink" : "text-ink-muted hover:text-ink",
                )}
              >
                {l.label}
              </Link>
            </li>
          ))}
        </ul>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/tailor/new" className={buttonClass("primary", "sm")}>
            <Plus className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">New tailoring</span>
            <span className="sm:hidden">New</span>
          </Link>
          <button onClick={logout} className={cx(buttonClass("ghost", "sm"), "hidden md:inline-flex")} aria-label="Sign out">
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
          <button
            className={cx(buttonClass("ghost", "sm"), "md:hidden")}
            aria-expanded={open}
            aria-controls="mobile-nav"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </nav>
      {open && (
        <div id="mobile-nav" className="border-t border-slate-100 px-4 pb-3 md:hidden">
          <ul className="space-y-1 pt-2">
            {LINKS.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  onClick={() => setOpen(false)}
                  aria-current={isActive(l.href) ? "page" : undefined}
                  className={cx("block rounded-md px-3 py-2 text-sm", isActive(l.href) ? "bg-slate-100 font-medium" : "text-ink-muted")}
                >
                  {l.label}
                </Link>
              </li>
            ))}
            <li>
              <button onClick={logout} className="block w-full rounded-md px-3 py-2 text-left text-sm text-ink-muted">
                Sign out
              </button>
            </li>
          </ul>
        </div>
      )}
    </header>
  );
}
