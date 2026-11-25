import { ArrowRight, Check } from "lucide-react";
import { AuroraBackground } from "@/components/fx/AuroraBackground";
import { SpotlightCard } from "@/components/fx/SpotlightCard";
import { Logo } from "@/components/shell/Logo";
import { ScoreRing } from "@/components/ui/Score";

const POINTS = ["Only rephrases what you wrote, nothing invented", "See and approve every change", "10 tailored resumes free, no card"];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuroraBackground className="min-h-screen">
      <main id="main" className="mx-auto grid min-h-screen max-w-5xl items-center gap-12 px-4 py-12 sm:px-6 lg:grid-cols-2">
        <div className="hidden lg:block">
          <Logo href="/login" />
          <p className="mt-10 text-3xl font-semibold tracking-tight text-ink">Tailor your resume to every role. Honestly.</p>
          <ul className="mt-6 space-y-3">
            {POINTS.map((p) => (
              <li key={p} className="flex items-center gap-3 text-base text-ink-muted">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-100 text-brand-700">
                  <Check className="h-3.5 w-3.5" strokeWidth={3} aria-hidden />
                </span>
                {p}
              </li>
            ))}
          </ul>
          <div className="mt-10 max-w-sm" aria-hidden>
            <SpotlightCard className="p-5 shadow-card">
              <p className="text-sm font-medium text-ink-muted">ATS match</p>
              <div className="mt-2 flex items-center justify-between gap-4">
                <ScoreRing value={64} label="Before" size={96} />
                <ArrowRight className="h-5 w-5 text-ink-muted" />
                <ScoreRing value={91} label="After" size={96} />
              </div>
            </SpotlightCard>
          </div>
        </div>
        <div className="flex flex-col items-center lg:items-end">
          <div className="mb-6 lg:hidden">
            <Logo href="/login" />
          </div>
          <div className="w-full max-w-md rounded-2xl bg-white/95 p-7 shadow-pop ring-1 ring-slate-900/5 sm:p-8">{children}</div>
        </div>
      </main>
    </AuroraBackground>
  );
}
