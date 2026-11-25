"use client";

/**
 * Source: https://reactbits.dev/components/spotlight-card
 *         https://github.com/DavidHDev/react-bits/blob/main/src/ts-tailwind/Components/SpotlightCard/SpotlightCard.tsx
 * React Bits © David Haz, MIT + Commons Clause (see ./LICENSES.md)
 * Vendored: 2026-11-25. Local changes:
 *  - Named export `SpotlightCard` (upstream: default export); `cx()` joins classes.
 *  - Light surface only (theme prop and dark palette removed): `bg-white ring-1 ring-line rounded-xl`, no default
 *    padding or shadow (className controls them, as in the previous local version).
 *  - No `overflow-hidden` on the card (upstream has it), so focus rings of buttons inside are never clipped. The
 *    glow layers are absolutely positioned behind the content and carry their own rounded-[inherit] radius.
 *  - `spotlightColor` keeps its meaning: the full colour of the spotlight centre including its alpha (default
 *    rgba(59, 99, 217, 0.12)); so `intensity` defaults to 1 and the light-theme 0.28 fill factor is dropped.
 *  - New optional `glowColor` (default brand-500) tints the thin edge highlight; `borderGlow` default 0.35.
 *    `spotlightSize` default 320. The static upstream border layer is replaced by the ring.
 *  - Reduced motion: no smoothing and no rAF loop; the highlight is painted synchronously on pointer/focus events.
 *    The loop also stops when the highlight has settled and while off-screen.
 *  - Stripped options we do not use, to cut bundle size: grain (noise layer), flare, ambient drift, beam shape, theme.
 */
import { useEffect, useRef } from "react";
import type { CSSProperties, HTMLAttributes } from "react";
import { cx } from "@/lib/format";

export type SpotlightCardProps = HTMLAttributes<HTMLDivElement> & {
  /** Colour of the spotlight centre, alpha included. */
  spotlightColor?: string;
  /** Colour of the edge highlight. */
  glowColor?: string;
  /** Opacity multiplier of the spotlight fill, 0 to 1. */
  intensity?: number;
  /** Radius in px. */
  spotlightSize?: number;
  softness?: number;
  /** Opacity of the edge highlight, 0 to 1. */
  borderGlow?: number;
  /** Distance in px outside the card at which the light starts to fade in. */
  proximity?: number;
  smoothing?: number;
};

type Settings = {
  fill: string;
  edge: string;
  size: number;
  intensity: number;
  borderGlow: number;
  proximity: number;
  smoothing: number;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const falloff = (color: string, softness: number) => {
  const soft = clamp(softness, 0, 1);
  const core = (1 - soft) ** 1.5 * 0.85;
  const stop = (alpha: number, at: number) =>
    `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(2)}%, transparent) ${(at * 100).toFixed(2)}%`;
  const list = [stop(1, 0)];
  for (let i = 0; i <= 14; i++) {
    const t = core + ((1 - core) * i) / 14;
    const g = (t - core) / (1 - core);
    const smooth = 1 - g * g * (3 - 2 * g);
    const glow = Math.exp(-4.6 * g * g) * (1 - g ** 6);
    list.push(stop(smooth + (glow - smooth) * soft, t));
  }
  return list.join(", ");
};

const RING_MASK =
  "[-webkit-mask:linear-gradient(#000_0_0)_content-box,linear-gradient(#000_0_0)] [-webkit-mask-composite:xor] [mask:linear-gradient(#000_0_0)_content-box_exclude,linear-gradient(#000_0_0)]";

export function SpotlightCard({
  children,
  className,
  style,
  spotlightColor = "rgba(59, 99, 217, 0.12)",
  glowColor = "#3b63d9",
  intensity = 1,
  spotlightSize = 320,
  softness = 0.7,
  borderGlow = 0.35,
  proximity = 80,
  smoothing = 0.3,
  ...rest
}: SpotlightCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const lightRef = useRef<HTMLSpanElement>(null);
  const edgeRef = useRef<HTMLSpanElement>(null);
  const wakeRef = useRef<(() => void) | null>(null);
  const settings: Settings = {
    fill: falloff(spotlightColor, softness),
    edge: falloff(glowColor, 1),
    size: Math.max(20, spotlightSize),
    intensity: clamp(intensity, 0, 1),
    borderGlow: clamp(borderGlow, 0, 1),
    proximity: Math.max(0, proximity),
    smoothing: clamp(smoothing, 0, 1),
  };
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    wakeRef.current?.();
  });

  useEffect(() => {
    const root = rootRef.current;
    const light = lightRef.current;
    const edge = edgeRef.current;
    if (!root || !light || !edge) return undefined;

    const mql = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let reduce = mql?.matches ?? false;
    const state = { x: 0, y: 0, presence: 0, visible: true };
    const pointer = { x: 0, y: 0, active: false };
    const drawn = { light: "", edge: "" };
    let focus: Element | null = null;
    let raf = 0;
    let last = 0;
    let alive = true;

    const gradient = (size: number, x: number, y: number, stops: string) =>
      `radial-gradient(circle ${size.toFixed(1)}px at ${x.toFixed(1)}px ${y.toFixed(1)}px, ${stops})`;

    const paint = (s: Settings) => {
      const fill = gradient(s.size, state.x, state.y, s.fill);
      const rim = gradient(s.size * 0.6, state.x, state.y, s.edge);
      if (fill !== drawn.light) {
        drawn.light = fill;
        light.style.background = fill;
      }
      if (rim !== drawn.edge) {
        drawn.edge = rim;
        edge.style.background = rim;
      }
      light.style.opacity = String(Math.min(1, state.presence * s.intensity));
      edge.style.opacity = String(Math.min(1, state.presence * s.borderGlow));
    };

    const tick = (now: number) => {
      raf = 0;
      if (!alive) return;
      const s = settingsRef.current;
      const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000));
      last = now;
      const rect = root.getBoundingClientRect();
      let tx = state.x;
      let ty = state.y;
      let target = 0;
      if (focus && root.contains(focus)) {
        const box = focus.getBoundingClientRect();
        tx = box.left + box.width / 2 - rect.left;
        ty = box.top + box.height / 2 - rect.top;
        target = 1;
      } else if (pointer.active) {
        tx = pointer.x - rect.left;
        ty = pointer.y - rect.top;
        const gap = Math.hypot(Math.max(0, -tx, tx - rect.width), Math.max(0, -ty, ty - rect.height));
        if (gap === 0) target = 1;
        else if (s.proximity > 0) target = Math.max(0, 1 - gap / s.proximity) ** 2;
      }
      if (state.presence < 0.02 && target > 0) {
        state.x = tx;
        state.y = ty;
      }
      const follow = reduce || s.smoothing === 0 ? 1 : 1 - Math.exp(-dt / (0.015 + s.smoothing * 0.22));
      state.x += (tx - state.x) * follow;
      state.y += (ty - state.y) * follow;
      const fade = reduce ? 1 : 1 - Math.exp(-dt / (target > state.presence ? 0.1 : 0.32));
      state.presence += (target - state.presence) * fade;
      if (Math.abs(target - state.presence) < 0.002) state.presence = target;
      paint(s);
      const moving = Math.abs(tx - state.x) > 0.1 || Math.abs(ty - state.y) > 0.1;
      const settled = !moving && state.presence === target;
      if (!settled && !reduce && state.visible) raf = requestAnimationFrame(tick);
    };

    const wake = () => {
      if (!alive) return;
      if (reduce) {
        // No loop under reduced motion: paint once, synchronously.
        tick(performance.now());
        return;
      }
      if (raf) return;
      last = performance.now();
      raf = requestAnimationFrame(tick);
    };
    wakeRef.current = wake;

    const onMove = (event: PointerEvent) => {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.active = true;
      if (state.presence > 0 || settingsRef.current.proximity > 0 || root.contains(event.target as Node | null)) wake();
    };
    const onOut = (event: PointerEvent) => {
      if (event.relatedTarget) return;
      pointer.active = false;
      wake();
    };
    const onDown = (event: PointerEvent) => {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.active = true;
      wake();
    };
    const onUp = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") {
        pointer.active = false;
        wake();
      }
    };
    const onFocusIn = (event: FocusEvent) => {
      if (!(event.target instanceof Element) || !event.target.matches(":focus-visible")) return;
      focus = event.target;
      wake();
    };
    const onFocusOut = (event: FocusEvent) => {
      if (root.contains(event.relatedTarget as Node | null)) return;
      focus = null;
      wake();
    };
    const onScroll = () => {
      if (pointer.active || state.presence > 0) wake();
    };
    const onMotionChange = () => {
      reduce = mql?.matches ?? false;
      if (reduce) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
      wake();
    };

    const observer = new IntersectionObserver((entries) => {
      state.visible = entries.some((entry) => entry.isIntersecting);
      if (state.visible) wake();
    });
    observer.observe(root);
    mql?.addEventListener?.("change", onMotionChange);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    window.addEventListener("scroll", onScroll, { capture: true, passive: true });
    document.addEventListener("pointerout", onOut);
    root.addEventListener("pointerdown", onDown);
    root.addEventListener("focusin", onFocusIn);
    root.addEventListener("focusout", onFocusOut);

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      observer.disconnect();
      mql?.removeEventListener?.("change", onMotionChange);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      window.removeEventListener("scroll", onScroll, { capture: true });
      document.removeEventListener("pointerout", onOut);
      root.removeEventListener("pointerdown", onDown);
      root.removeEventListener("focusin", onFocusIn);
      root.removeEventListener("focusout", onFocusOut);
      wakeRef.current = null;
    };
  }, []);

  return (
    <div
      ref={rootRef}
      className={cx("relative isolate rounded-xl bg-white ring-1 ring-line", className)}
      style={style as CSSProperties | undefined}
      {...rest}
    >
      <span
        ref={lightRef}
        className="pointer-events-none absolute inset-0 -z-10 rounded-[inherit] opacity-0"
        aria-hidden="true"
      />
      {children}
      <span
        ref={edgeRef}
        className={cx("pointer-events-none absolute inset-0 z-[1] rounded-[inherit] p-px opacity-0", RING_MASK)}
        aria-hidden="true"
      />
    </div>
  );
}
