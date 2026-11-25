/**
 * Local re-implementation in the style of Aceternity UI's "Aurora Background"
 * (https://ui.aceternity.com/components/aurora-background). Not a copy: the Aceternity site was unreachable from the
 * build environment, so this was written from scratch (see ./LICENSES.md).
 * Written: 2026-11-25. Technique: repeating-linear-gradient layers drifting via background-position, following the
 * redesign spec. Light mode only, brand colour stops, no fixed 100vh or flex centring (layout controls size), aurora
 * layer capped at opacity-40, classes joined with cx().
 */
import { cx } from "@/lib/format";

export function AuroraBackground({
  children,
  className,
  showRadialGradient = true,
}: {
  children: React.ReactNode;
  className?: string;
  showRadialGradient?: boolean;
}) {
  const white = "repeating-linear-gradient(100deg,#fff 0%,#fff 7%,transparent 10%,transparent 12%,#fff 16%)";
  const aurora = "repeating-linear-gradient(100deg,#3b63d9 10%,#93adf8 15%,#bfd0fd 20%,#c4b5fd 25%,#5f84ea 30%)";
  return (
    <div className={cx("relative overflow-hidden bg-surface-page", className)}>
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        <div
          className={cx(
            "absolute -inset-[10px] opacity-40 blur-[10px] will-change-transform animate-aurora",
            "[background-size:300%,_200%] [background-position:50%_50%,50%_50%]",
            showRadialGradient && "[mask-image:radial-gradient(ellipse_at_100%_0%,black_10%,transparent_70%)]",
          )}
          style={{ backgroundImage: `${white}, ${aurora}` }}
        />
      </div>
      <div className="relative">{children}</div>
    </div>
  );
}
