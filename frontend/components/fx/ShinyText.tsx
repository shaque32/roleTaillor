"use client";

/**
 * Source: https://reactbits.dev/text-animations/shiny-text
 *         https://github.com/DavidHDev/react-bits/blob/main/src/ts-tailwind/TextAnimations/ShinyText/ShinyText.tsx
 * React Bits © David Haz, MIT + Commons Clause (see ./LICENSES.md)
 * Vendored: 2026-11-25. Local changes:
 *  - Named export `ShinyText` (upstream: default export); `cx()` replaces template-string class joining.
 *  - Light theme defaults: `color` = ink #0f172a, `shineColor` = brand-500 #3b63d9 (5.3:1 on white), so every
 *    frame of the sweep is AA on a white surface (the gamma blend only mixes between those two colours).
 *  - `speed` default 3 (seconds per sweep, as the previous local version); `trigger` removed (always loops).
 *  - Reduced motion: no sweep and no rAF loop is ever started (upstream still ran one sweep); also reacts to
 *    the media query changing at runtime.
 *  - The loop also stops while the element is off-screen and on unmount (as upstream), and restarts on re-entry.
 *  - Stripped options we do not use, to cut bundle size: bands, glow (and its duplicate layer), yoyo, followPointer,
 *    pauseOnHover, trigger (hover/view), the snappy easing.
 */
import { useEffect, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { cx } from "@/lib/format";

type Easing = "smooth" | "linear";

export interface ShinyTextProps {
  /** Text to render (ignored when `children` is given). */
  text?: string;
  children?: ReactNode;
  /** Base text colour. Default: ink. */
  color?: string;
  /** Colour of the moving highlight. Default: brand-500. */
  shineColor?: string;
  /** Seconds per sweep. Default 3. */
  speed?: number;
  /** Seconds to wait between sweeps. Default 0. */
  delay?: number;
  angle?: number;
  /** Width of the highlight band, % of the text box. */
  shineWidth?: number;
  softness?: number;
  direction?: "left" | "right";
  easing?: Easing;
  /** Static text, no animation. */
  disabled?: boolean;
  className?: string;
  style?: CSSProperties;
}

interface Settings {
  color: string;
  shineColor: string;
  speed: number;
  delay: number;
  angle: number;
  shineWidth: number;
  softness: number;
  sign: number;
  ease: (t: number) => number;
  disabled: boolean;
}

const EASINGS: Record<Easing, (t: number) => number> = {
  linear: (t) => t,
  smooth: (t) => 0.5 - Math.cos(Math.PI * t) / 2,
};
const FALLOFF = [0, 0.2, 0.4, 0.6, 0.8, 1];

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

type Rgba = [number, number, number, number];

let paint: CanvasRenderingContext2D | null = null;

const parseColor = (value: string): Rgba | null => {
  if (typeof document === "undefined") return null;
  if (!paint) paint = document.createElement("canvas").getContext("2d");
  if (!paint) return null;
  paint.fillStyle = "#000000";
  paint.fillStyle = value;
  const resolved = String(paint.fillStyle);
  if (resolved.startsWith("#")) {
    const ch = (i: number) => parseInt(resolved.slice(i, i + 2), 16);
    return [ch(1), ch(3), ch(5), 1];
  }
  const parts = resolved.match(/[\d.]+/g);
  if (!parts || parts.length < 3) return null;
  return [Number(parts[0]), Number(parts[1]), Number(parts[2]), parts.length > 3 ? Number(parts[3]) : 1];
};

const blend = (from: Rgba, to: Rgba, amount: number) => {
  const channel = (a: number, b: number) =>
    Math.round(Math.pow(Math.pow(a / 255, 2.2) * (1 - amount) + Math.pow(b / 255, 2.2) * amount, 1 / 2.2) * 255);
  const alpha = from[3] * (1 - amount) + to[3] * amount;
  if (alpha <= 0) return "rgba(0, 0, 0, 0)";
  const weigh = (a: number, b: number) => (a * from[3] * (1 - amount) + b * to[3] * amount) / alpha;
  const r = from[3] === to[3] ? channel(from[0], to[0]) : Math.round(weigh(from[0], to[0]));
  const g = from[3] === to[3] ? channel(from[1], to[1]) : Math.round(weigh(from[1], to[1]));
  const b = from[3] === to[3] ? channel(from[2], to[2]) : Math.round(weigh(from[2], to[2]));
  return `rgba(${r}, ${g}, ${b}, ${Math.round(alpha * 1000) / 1000})`;
};

export function ShinyText({
  text,
  children,
  color = "#0f172a",
  shineColor = "#3b63d9",
  speed = 3,
  delay = 0,
  angle = 120,
  shineWidth = 40,
  softness = 0.8,
  direction = "left",
  easing = "smooth",
  disabled = false,
  className,
  style,
}: ShinyTextProps) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const settingsRef = useRef<Settings | null>(null);
  const syncRef = useRef<(() => void) | null>(null);
  const content = children ?? text;

  settingsRef.current = {
    color,
    shineColor,
    speed: Math.max(0.1, speed),
    delay: Math.max(0, delay),
    angle,
    shineWidth: clamp(shineWidth, 2, 200),
    softness: clamp(softness, 0, 1),
    sign: direction === "right" ? 1 : -1,
    ease: EASINGS[easing] ?? EASINGS.smooth,
    disabled,
  };

  useEffect(() => {
    syncRef.current?.();
  });

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;

    const mql = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let reduce = mql?.matches ?? false;
    const state = {
      pos: null as number | null,
      phase: "idle" as "idle" | "sweep" | "wait",
      from: 0,
      to: 0,
      start: 0,
      duration: 1,
      resume: 0,
      visible: true,
      colors: "",
    };
    let base: Rgba | null = null;
    let shine: Rgba | null = null;
    let raf = 0;
    let timer = 0;
    let alive = true;

    const extent = () => settingsRef.current!.shineWidth / 2 + 2;
    const entry = () => (settingsRef.current!.sign > 0 ? -extent() : 100 + extent());
    const exit = () => (settingsRef.current!.sign > 0 ? 100 + extent() : -extent());

    const gradient = (pos: number, fill: Rgba) => {
      const s = settingsRef.current!;
      const half = s.shineWidth / 2;
      const core = half * (1 - s.softness);
      const fade = half - core;
      const stops: [number, number][] = [];
      for (const side of [-1, 1]) {
        for (const f of FALLOFF) {
          stops.push([pos + side * (core + fade * (1 - f)), f * f * (3 - 2 * f)]);
        }
      }
      stops.sort((a, b) => a[0] - b[0]);
      const list = stops.map(([at, amount]) => `${blend(fill, shine!, amount)} ${at.toFixed(2)}%`);
      return `linear-gradient(${s.angle}deg, ${blend(fill, shine!, 0)} 0%, ${list.join(", ")}, ${blend(fill, shine!, 0)} 100%)`;
    };

    const draw = () => {
      const s = settingsRef.current!;
      const key = `${s.color}|${s.shineColor}`;
      if (key !== state.colors) {
        state.colors = key;
        base = parseColor(s.color);
        shine = parseColor(s.shineColor);
      }
      if (!base || !shine || state.pos === null || s.disabled) {
        root.style.backgroundImage = `linear-gradient(${s.color}, ${s.color})`;
        return;
      }
      root.style.backgroundImage = gradient(state.pos, base);
    };

    const sweep = (now: number) => {
      const s = settingsRef.current!;
      state.phase = "sweep";
      state.from = entry();
      state.to = exit();
      state.start = now;
      state.duration = s.speed * 1000;
    };

    const stop = () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
      raf = 0;
      timer = 0;
    };

    const wake = () => {
      if (raf || !alive || reduce) return;
      window.clearTimeout(timer);
      timer = 0;
      raf = requestAnimationFrame(tick);
    };

    const tick = (now: number) => {
      raf = 0;
      if (!alive) return;
      const s = settingsRef.current!;
      if (s.disabled || reduce || !state.visible) {
        // Off-screen, disabled or reduced motion: static text and no loop.
        state.pos = null;
        state.phase = "idle";
        draw();
        return;
      }
      if (state.phase === "idle") sweep(now);
      if (state.phase === "sweep") {
        const t = clamp((now - state.start) / state.duration, 0, 1);
        state.pos = state.from + (state.to - state.from) * s.ease(t);
        draw();
        if (t < 1) {
          raf = requestAnimationFrame(tick);
          return;
        }
        state.phase = "wait";
        state.resume = now + s.delay * 1000;
      }
      if (now < state.resume) {
        timer = window.setTimeout(wake, state.resume - now);
        return;
      }
      sweep(now);
      raf = requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver((entries) => {
      state.visible = entries.some((item) => item.isIntersecting);
      if (state.visible) wake();
    });
    observer.observe(root);

    const onMotionChange = () => {
      reduce = mql?.matches ?? false;
      if (reduce) {
        stop();
        state.pos = null;
        state.phase = "idle";
        draw();
      } else {
        wake();
      }
    };
    mql?.addEventListener?.("change", onMotionChange);

    syncRef.current = () => {
      if (settingsRef.current!.disabled) {
        stop();
        state.pos = null;
        state.phase = "idle";
      }
      draw();
      wake();
    };
    draw();
    wake();

    return () => {
      alive = false;
      stop();
      observer.disconnect();
      mql?.removeEventListener?.("change", onMotionChange);
      syncRef.current = null;
    };
  }, []);

  return (
    <span
      ref={rootRef}
      className={cx(
        "relative inline-block bg-no-repeat [background-size:100%_100%] bg-clip-text [-webkit-background-clip:text] [-webkit-text-fill-color:transparent]",
        className,
      )}
      style={{ backgroundImage: `linear-gradient(${color}, ${color})`, ...style }}
    >
      {content}
    </span>
  );
}
