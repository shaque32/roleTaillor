/**
 * Local re-implementation in the style of Aceternity UI's "Grid and Dot Backgrounds", dot variant
 * (https://ui.aceternity.com/components/grid-and-dot-backgrounds). Not a copy: the Aceternity site was unreachable
 * from the build environment, so this was written from scratch (see ./LICENSES.md).
 * Written: 2026-11-25. A decorative absolute layer (no wrapper, no children), light colours, optional radial fade
 * mask, classes joined with cx(). The parent must be `relative` and its content `relative`.
 */
import { cx } from "@/lib/format";

export function DotBackground({ fade, className }: { fade?: boolean; className?: string }) {
  return (
    <div
      aria-hidden
      className={cx(
        "pointer-events-none absolute inset-0 [background-size:20px_20px] [background-image:radial-gradient(#d4d9e3_1px,transparent_1px)]",
        fade && "[mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]",
        className,
      )}
    />
  );
}
