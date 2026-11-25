"use client";

/**
 * Source: https://reactbits.dev/text-animations/count-up
 *         https://github.com/DavidHDev/react-bits/blob/main/src/ts-tailwind/TextAnimations/CountUp/CountUp.tsx
 * React Bits © David Haz, MIT + Commons Clause (see ./LICENSES.md)
 * Vendored: 2026-11-25. Local changes:
 *  - Named export `CountUp` (upstream: default export); `duration` default 1.2 s (upstream 2).
 *  - `decimals` defaults to 0 (output is rounded, as the previous local version); upstream infers it from from/to.
 *  - Reduced motion: shows the final value immediately, never starts an animation (upstream already did this).
 *    Also reads the media query at animation time, so there is no state flip after mount.
 *  - The animated text is aria-hidden and a sibling sr-only span announces the final value once. A hidden copy of
 *    the final text sits in the same grid cell, so the box already has its final width: no layout shift.
 *  - className/style go on the outer span, which always has `tabular-nums`.
 *  - Animation starts from the currently shown value if `to` changes later, and is stopped on unmount.
 *  - Stripped options we do not use, to cut bundle size: roll mode (columns, SVG blur filters, springs), compact
 *    number format, replayOnHover, the spring easing.
 */
import { animate, cubicBezier, useInView } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { cx } from "@/lib/format";

type Easing = "easeOut" | "linear" | "expo";

export interface CountUpProps {
  to: number;
  from?: number;
  /** "down" counts from `to` to `from`. */
  direction?: "up" | "down";
  /** Seconds before the count starts. */
  delay?: number;
  /** Seconds. Default 1.2. */
  duration?: number;
  className?: string;
  style?: CSSProperties;
  startWhen?: boolean;
  /** Thousands separator, e.g. ",". Default none. */
  separator?: string;
  prefix?: string;
  suffix?: string;
  easing?: Easing;
  /** Fraction digits. Default 0 (rounded). */
  decimals?: number;
  /** "view" (default) starts when scrolled into view; "load" starts at once. */
  trigger?: "view" | "load";
  onStart?: () => void;
  onEnd?: () => void;
}

const EASINGS: Record<Easing, (t: number) => number> = {
  linear: (t) => t,
  easeOut: cubicBezier(0.33, 1, 0.68, 1),
  expo: (t) => (t >= 1 ? 1 : (1 - Math.pow(2, -10 * t)) / (1 - Math.pow(2, -10))),
};

const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

const group = (int: string, separator: string) => (separator ? int.replace(/\B(?=(\d{3})+(?!\d))/g, separator) : int);

export function CountUp({
  to,
  from = 0,
  direction = "up",
  delay = 0,
  duration = 1.2,
  className,
  style,
  startWhen = true,
  separator = "",
  prefix = "",
  suffix = "",
  easing = "easeOut",
  decimals = 0,
  trigger = "view",
  onStart,
  onEnd,
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const startValue = direction === "down" ? to : from;
  const endValue = direction === "down" ? from : to;
  const valueRef = useRef(startValue);
  const startedRef = useRef(false);
  const callbacks = useRef({ onStart, onEnd });
  const isInView = useInView(ref, { once: true, margin: "0px" });
  const active = trigger === "load" || isInView;

  const formatValue = useCallback(
    (latest: number) => {
      const fixed = Math.abs(latest).toFixed(decimals);
      const [int = "0", frac] = fixed.split(".");
      const negative = latest < 0 && Number(fixed) !== 0;
      return `${prefix}${negative ? "-" : ""}${group(int, separator)}${frac ? `.${frac}` : ""}${suffix}`;
    },
    [decimals, separator, prefix, suffix],
  );

  const [initialText] = useState(() => formatValue(startValue));

  useIsoLayoutEffect(() => {
    callbacks.current = { onStart, onEnd };
  });

  // Keep the idle text in sync with props until the animation has started.
  useIsoLayoutEffect(() => {
    if (!startedRef.current) valueRef.current = startValue;
    if (textRef.current && !startedRef.current) textRef.current.textContent = formatValue(startValue);
  }, [startValue, formatValue]);

  useEffect(() => {
    if (!active || !startWhen) return undefined;
    const el = textRef.current;
    if (!el) return undefined;
    startedRef.current = true;
    callbacks.current.onStart?.();

    const finish = () => {
      valueRef.current = endValue;
      el.textContent = formatValue(endValue);
      callbacks.current.onEnd?.();
    };

    if (duration <= 0 || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      finish();
      return undefined;
    }

    const controls = animate(valueRef.current, endValue, {
      duration,
      delay,
      ease: EASINGS[easing] ?? EASINGS.easeOut,
      onUpdate: (v) => {
        valueRef.current = v;
        el.textContent = formatValue(v);
      },
      onComplete: finish,
    });
    return () => controls.stop();
  }, [active, startWhen, endValue, duration, delay, easing, formatValue]);

  const finalText = formatValue(endValue);

  return (
    <span ref={ref} className={cx("inline-grid tabular-nums", className)} style={style}>
      {/* Hidden copy of the final text reserves the final width. */}
      <span aria-hidden className="invisible col-start-1 row-start-1 whitespace-pre">
        {finalText}
      </span>
      <span ref={textRef} aria-hidden className="col-start-1 row-start-1 whitespace-pre">
        {initialText}
      </span>
      <span className="sr-only">{finalText}</span>
    </span>
  );
}
