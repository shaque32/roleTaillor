# RoleTailor redesign: implementation spec

Audience: the engineers (or models) implementing the redesign. Owner-facing summary: `/mnt/project-files/redesign/ux-audit.md`. "Before" screenshots: `/mnt/project-files/redesign/before/`.

Goal: easier, friendlier, fewer boxes. Replace native selects, soften inputs, fix five flow bugs, add a small amount of motion where it does not slow work down.

## 0. Ground rules

1. Frontend only. Do not edit `lib/api.ts`, `lib/types.ts`, `app/api/**`, `middleware.ts`, or any route path.
2. Do not edit `components/ResumeUpload.tsx` at all. In `app/(app)/settings/Settings.tsx`, do not edit the `BillingCard` function or the existing import statements (PR #3 touches them). Both restyle automatically through tokens and primitives. Exact allowed edits to `Settings.tsx` are listed in section 4.3.7.
3. New dependency: `motion` (`npm i motion@^12`, import from `"motion/react"`). Nothing else. No `clsx`, `tailwind-merge`, `gsap`, `three`, `ogl`, `react-dropzone`, Radix, Headless UI.
4. `motion` may be imported only inside `components/fx/`. Everything in `components/ui/` is CSS/Tailwind only.
5. Decoration (anything from `components/fx/`) is allowed only on: auth pages, onboarding, `EmptyState`, the tailoring progress card, the review result summary numbers, and the payment dialog plan cards. Never on dashboard rows, change review, applications, settings, the builder.
6. Every interactive element: reachable by Tab, operable by keyboard, visible focus ring (`focusRing` class, section 1.3), accessible name. Touch targets at least 36px high, 44px for primary actions on mobile.
7. Class merging: this repo has `cx()` in `lib/format.ts` (joins, does not de-duplicate). Vendored code that calls `cn(...)` must be changed to `cx(...)`. Do not pass a `className` that conflicts with a primitive's own classes for the same property.
8. No dark mode. Strip every `dark:` class from vendored code.
9. Test hooks used by `dev/screenshots.mjs` must keep working:
   - `input[name="email"]`, `input[name="password"]`, one `button[type="submit"]` on `/login`.
   - Dashboard: each row has a `button[aria-expanded]` inside a `ul > li`, with accessible name matching `/details for {target role}/i`.
   - Resumes: a button whose name matches `/version/i`; a button whose name starts with "Upload".
   - Review: a heading matching `/review changes/i`; an element with `id="iterate"`; a button named "Share link".
   - Applications: a button named "Add application".

## 1. Design tokens (WP1)

### 1.1 `tailwind.config.ts` (replace `theme.extend`)

```ts
extend: {
  colors: {
    // ink.faint darkened from #94a3b8 (2.6:1, fails AA) to #5b6779 (5.6:1 on white)
    ink: { DEFAULT: "#0f172a", muted: "#475569", faint: "#5b6779" },
    brand: {
      50: "#eef4ff", 100: "#dbe6fe", 200: "#bfd0fd", 300: "#93adf8", 400: "#5f84ea",
      500: "#3b63d9", 600: "#2f50b8", 700: "#263f91", 800: "#1e3272",
    },
    surface: { DEFAULT: "#ffffff", page: "#f6f7fb", sunken: "#f1f4f9" },
    line: { DEFAULT: "#e5e9f0", field: "#8590a2" }, // field = 3.2:1 on white (WCAG 1.4.11)
  },
  fontFamily: { sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
  // Global softening. Files we may not edit (ResumeUpload, BillingCard) pick this up for free.
  borderRadius: { md: "0.625rem", lg: "0.875rem", xl: "1.125rem", "2xl": "1.5rem" },
  boxShadow: {
    card: "0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px -4px rgb(15 23 42 / 0.08)",
    pop: "0 2px 6px rgb(15 23 42 / 0.06), 0 12px 32px -8px rgb(15 23 42 / 0.18)",
  },
  keyframes: {
    aurora: { from: { backgroundPosition: "50% 50%, 50% 50%" }, to: { backgroundPosition: "350% 50%, 350% 50%" } },
    shine: { "0%": { backgroundPosition: "100% 0" }, "100%": { backgroundPosition: "-100% 0" } },
    "pop-in": { from: { opacity: "0", transform: "translateY(4px) scale(0.98)" }, to: { opacity: "1", transform: "none" } },
    "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
    shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
  },
  animation: {
    aurora: "aurora 60s linear infinite",
    shine: "shine 3s linear infinite",
    "pop-in": "pop-in 140ms ease-out",   // no fill-mode: must not leave a transform behind
    "fade-in": "fade-in 200ms ease-out",
    shimmer: "shimmer 1.6s linear infinite",
  },
},
```

`content` globs already cover `components/**`; no change there.

### 1.2 `app/globals.css`

- `body { @apply bg-surface-page text-ink antialiased; }`
- Keep the existing `prefers-reduced-motion` block unchanged (it neutralises every animation and transition, including vendored ones).
- Add:

```css
@layer base {
  ::selection { background: #dbe6fe; }
  input[type="date"] { min-height: 3rem; }
}
```

- `app/layout.tsx`: `themeColor` stays `#ffffff`. Skip link gets `focusRing` classes.

### 1.3 Shared class constants

Create `components/ui/styles.ts` (plain strings, no JSX):

```ts
export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2";
export const fieldControl =
  "block w-full rounded-lg border border-line-field bg-white px-3.5 text-base text-ink placeholder:text-ink-faint " +
  "transition-shadow hover:border-ink-faint focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100 " +
  "disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted " +
  "aria-[invalid=true]:border-red-600 aria-[invalid=true]:focus:ring-red-100";
```

### 1.4 Type scale (use these utilities, nothing in between)

| Role | Classes |
|---|---|
| Auth/onboarding headline | `text-3xl font-semibold tracking-tight` |
| Page title (h1) | `text-2xl sm:text-[1.75rem] font-semibold tracking-tight` |
| Section title (h2) | `text-lg font-semibold` |
| Sub-heading (h3), row title | `text-base font-semibold` (row title: `font-medium`) |
| Body, inputs | `text-base` (16px; prevents iOS zoom) |
| Secondary text, buttons, labels | `text-sm` (labels: `font-medium`) |
| Captions, badges | `text-xs` (never smaller; remove `text-[11px]`) |

Text colours: `text-ink` primary, `text-ink-muted` secondary, `text-ink-faint` only for captions/placeholders on white or `surface-page` (not on `surface-sunken`).

### 1.5 Spacing and layout

- Page gutter `px-4 sm:px-6`; page top `py-8 sm:py-10`; app shell `max-w-5xl` (was 6xl); form pages `max-w-2xl`; settings and builder `max-w-3xl`.
- Between page sections `space-y-8`; inside a card `p-5 sm:p-6`; between form fields `space-y-5`; grid gaps `gap-4`.
- Box rule: one elevated surface per region. Inside a `Card`, never put another bordered box. To group inside a card use (a) a `divide-y divide-line` list, (b) `bg-surface-sunken rounded-lg` with no border, or (c) a left rule `border-l-2 border-line pl-4`.

## 2. Primitives (WP1) — `components/ui/`

Existing prop names keep working unless stated. All new files are exported from `components/ui/index.ts`. WP2/WP3 code against the signatures below; if WP1 has not landed, stub the import locally and delete the stub at merge.

### 2.1 Changes to existing files

**`Button.tsx`**
- Variants: `primary | secondary | soft | ghost | danger`. New `soft`: `bg-brand-50 text-brand-700 hover:bg-brand-100`. `secondary`: `border border-line bg-white text-ink shadow-sm hover:bg-surface-sunken`.
- Sizes: `sm` = `h-9 px-3 text-sm`, `md` = `h-11 px-4 text-sm`, new `lg` = `h-12 px-6 text-base`.
- Base: `rounded-lg`, replace the outline classes with `focusRing`, add `active:translate-y-px`.
- `ButtonLink` accepts the same `variant`/`size` values. `buttonClass` signature unchanged.
- New export `IconButton`: `({ label, variant = "ghost", size = "md", className, children, ...buttonProps }: { label: string } & ButtonProps)`. Renders a square button (`sm` 36px, `md` 44px), sets `aria-label={label}` and `title={label}`.

**`Field.tsx`**
- `control` becomes `fieldControl` from `styles.ts` plus `h-12` for `Input`; `Textarea` gets `py-3 leading-relaxed` and no fixed height.
- Label: `text-sm font-medium text-ink`, gap `space-y-2`. Hint `text-sm text-ink-muted`. Error `text-sm text-red-700` prefixed by a 14px `AlertCircle` icon (`aria-hidden`).
- When `required` is passed and a label exists, nothing visual changes (no asterisk); when a field is optional pass the new prop `optional` to render `<span class="font-normal text-ink-muted"> (optional)</span>` after the label.
- `Input` new props: `leading?: React.ReactNode` (16px icon inside the left edge; input gets `pl-10`), `optional?: boolean`.
- `Textarea` new props: `autoGrow?: boolean` (on input set `style.height = "auto"` then `scrollHeight + "px"`, capped at `maxRows`, default 16 rows), `optional?: boolean`.
- New export `PasswordInput`: same props as `Input` minus `type`. Renders an `Input` with a trailing `IconButton` (`Eye`/`EyeOff`, label "Show password"/"Hide password", `aria-pressed`) that toggles `type` between `password` and `text`.
- New exports `FieldShell` (the current `Shell`, made public; props `{ id, label?, hint?, error?, optional?, className?, labelId?, children }`) and `describedBy`.
- **Remove the native `Select` export** from this file. It is replaced by `Select.tsx` below (same export name, different API). Every call site is rewritten by its owning WP (list in section 2.3).

**`Card.tsx`**
- `Card`: new prop `variant?: "raised" | "flat" | "sunken"` (default `raised`). `raised` = `rounded-xl bg-white shadow-card ring-1 ring-slate-900/5` (no `border`). `flat` = `rounded-xl bg-white ring-1 ring-line`. `sunken` = `rounded-xl bg-surface-sunken`.
- `CardHeader`: remove `border-b`; padding `px-5 pt-5 sm:px-6 sm:pt-6 pb-0`; title `text-lg font-semibold`; description `text-sm text-ink-muted mt-1`. `title` type widens to `React.ReactNode`.
- `CardBody`: `px-5 py-5 sm:px-6 sm:py-6`.
- New export `Section`: `({ title, description, action, id, className, children }: { title: React.ReactNode; description?: React.ReactNode; action?: React.ReactNode; id?: string; className?: string; children: React.ReactNode })`. An unboxed `<section aria-labelledby>`: header row (h2 `text-lg font-semibold`, description, action right) then children with `mt-4`. Use this instead of a Card when the content is already a list or when nested in a Card.

**`Badge.tsx`**
- Tones unchanged plus `brand` (alias of `blue`). Padding `px-2.5 py-1`. New prop `dot?: boolean` renders a 6px circle in `currentColor` before the text.
- `StatusBadge`: pass `dot`; for `queued`/`running` the dot has `animate-pulse`.

**`Alert.tsx`**
- Remove the border. Styles: info `bg-brand-50 text-brand-800`, warning `bg-amber-50 text-amber-900`, error `bg-red-50 text-red-800`, new tone `success` `bg-emerald-50 text-emerald-800` (icon `CheckCircle2`). `rounded-lg px-4 py-3.5`.
- New prop `action?: React.ReactNode` rendered on the right (wraps below on mobile).

**`Dialog.tsx`**
- New props: `size?: "sm" | "md" | "lg"` (`max-w-md | max-w-lg | max-w-2xl`, default `md`), `footer?: React.ReactNode` (rendered in a `mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end` row).
- Replace the hard-coded `id="dialog-title"` with `useId()` (two dialogs can be mounted at once today).
- Style: `rounded-2xl border-0 shadow-pop backdrop:bg-slate-900/50`, inner padding `p-6 sm:p-7`, `open:animate-pop-in`. Below `sm`: bottom sheet (`mb-0 mt-auto w-full max-w-none rounded-b-none`, `max-h-[90dvh] overflow-y-auto`).
- Close button becomes `IconButton label="Close"`.
- Click on the backdrop closes: `onClick={(e) => e.target === e.currentTarget && onClose()}` on the `<dialog>`.
- Do not add a persistent `transform`, `filter` or `backdrop-filter` to the dialog (it would break `Select` positioning, section 2.2).

**`DiffView.tsx`** — fixes "word-level diff is noisy".
- Add to `lib/diff.ts` (WP1 owns; keep existing exports and tests):

```ts
/** Phrase-level view of diffWords. ratio = changed characters / total characters across both sides (0..1). */
export function diffPhrases(before: string, after: string): { segments: DiffSegment[]; ratio: number }
```
  Algorithm: (1) `segs = diffWords(before, after)`. (2) Absorb bridges: for each `equal` segment that has a non-equal segment on both sides and whose `text.trim().length <= 3` (whitespace, "a", "to", "and"), replace it with two segments, `delete` and `insert`, each carrying its text. (3) Normalise: within each run of consecutive non-equal segments, concatenate all deletes into one `delete` and all inserts into one `insert`, emitted in that order. (4) `ratio` = sum of lengths of non-equal segments / (before.length + after.length), 0 if both empty. `applySide` must still round-trip; add tests for: identical text (ratio 0), the "Data engineer … end to end" example (highlights are phrases, no single-character segments), a reordered skills list (ratio > 0.6), empty sides.
- `DiffView` props: `{ before: string; after: string; layout?: "auto" | "stacked" }`. `auto` = two columns from `md`, stacked below. In stacked layout **After comes first**.
- Rendering: column labels "Suggested rewrite" (after) and "Your original" (before), `text-xs font-medium text-ink-muted`, sentence case, not uppercase. No grey boxes: after text is `text-base text-ink leading-relaxed`; before text is `text-sm text-ink-muted leading-relaxed border-l-2 border-line pl-4` (stacked) or plain in its column.
- If `ratio > 0.6`: render both sides with **no** highlighting and a caption under the labels: "Mostly rewritten or reordered".
- Otherwise: inserts as `<ins class="rounded bg-emerald-100 px-0.5 text-emerald-900 no-underline">`; deletes as `<del class="text-ink-muted decoration-red-400">` (strike-through only, no red background).
- Keep `(empty)` / `(removed)` placeholders.

**`EmptyState.tsx`**
- Props add `secondaryAction?: React.ReactNode`. Remove the dashed border. Container `relative overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-slate-900/5 px-6 py-16`, with `<DotBackground fade />` (section 3) absolutely positioned behind. Icon in a 56px `rounded-2xl bg-brand-50 text-brand-600` tile. Title `text-xl font-semibold`. Actions in a wrapping row.

**`PageHeader.tsx`**
- New props `back?: { href: string; label: string }` (renders the `ArrowLeft` back link above the title; replaces the hand-written links in Review and ResumeDetailView) and `meta?: React.ReactNode` (row under the title for badges). Title uses the page-title scale. `mb-8`.

**`Score.tsx`**
- `ScoreBar`: track `h-2.5 bg-surface-sunken`; "before" tick `h-4 w-0.5 bg-ink` with `title="Before: {b}"`; delta as a `Badge` (`green` when positive, `red` when negative). Colours: `>=75` `bg-emerald-500`, `>=50` `bg-brand-500`, else `bg-amber-500` (unchanged thresholds).
- `ScoreRing`: stroke 10, track `#e5e9f0`; unchanged API.
- `ScorePill`: unchanged API.
- New export `ScoreChip`: `({ label, value, title }: { label: string; value: number | null | undefined; title?: string })`. Renders `<span class="inline-flex items-center gap-1.5 rounded-full bg-surface-sunken px-2.5 py-1 text-xs text-ink-muted">{label} <ScorePill/></span>`; renders nothing when `value` is null/undefined.

**`Skeleton.tsx`**: replace `animate-pulse bg-slate-200/70` with `animate-shimmer rounded-lg bg-[linear-gradient(90deg,#eef1f6_25%,#f8f9fc_50%,#eef1f6_75%)] bg-[length:200%_100%]`. `SkeletonRows` rows `h-16`.

**`Toast.tsx`**: container `bottom-20 md:bottom-4` (clears the mobile tab bar); toast `rounded-xl shadow-pop border-0 ring-1 ring-slate-900/5 animate-pop-in`; dismiss is an `IconButton size="sm"`. Errors: wrap message in `role="alert"`.

**`Spinner.tsx`**: unchanged.

### 2.2 New primitives

**`Select.tsx`** (`"use client"`) — replaces every native `<select>`.

```ts
export interface SelectOption<V extends string = string> {
  value: V;
  label: string;
  description?: string;      // second line in the list, text-xs text-ink-muted
  tone?: "neutral" | "blue" | "green" | "amber" | "red";  // coloured dot before the label
  disabled?: boolean;
}
export interface SelectProps<V extends string = string> {
  options: SelectOption<V>[];
  value?: V;                 // controlled
  defaultValue?: V;          // uncontrolled
  onChange?: (value: V) => void;
  name?: string;             // renders <input type="hidden" name={name} value={current}> so FormData keeps working
  label?: string;
  "aria-label"?: string;     // required when label is omitted
  hint?: string;
  error?: string;
  placeholder?: string;      // shown when current value matches no option; default "Select…"
  disabled?: boolean;
  size?: "sm" | "md";        // trigger h-9 text-sm / h-12 text-base
  variant?: "field" | "pill";// pill = rounded-full, tinted by the selected option's tone, no visible border (status pickers)
  className?: string;
  id?: string;
}
export function Select<V extends string = string>(props: SelectProps<V>): JSX.Element;
```

Behaviour (WAI-ARIA APG "select-only combobox"):
- Trigger: `<button type="button" role="combobox" aria-haspopup="listbox" aria-expanded aria-controls={listId} aria-activedescendant={open ? activeOptionId : undefined} aria-labelledby="{labelId} {valueId}">` showing the selected label and a `ChevronDown`. Styled with `fieldControl`; text left, chevron right.
- Popup: `<ul role="listbox" id={listId} tabIndex={-1}>`; each option `<li role="option" id aria-selected aria-disabled>`, min height 44px, selected option shows a `Check` icon, active option `bg-brand-50`. Popup classes `z-50 max-h-72 overflow-auto rounded-xl bg-white p-1 shadow-pop ring-1 ring-slate-900/10 animate-fade-in`.
- Positioning: the popup is rendered **inline, right after the trigger (no portal)** with `position: fixed` and `top/left/width` computed from `trigger.getBoundingClientRect()` when opening; open upward if less than 300px below and more above. Close on window `resize` and on any `scroll` event (capture phase) whose target is not inside the popup. Reason: native `<dialog>` is in the top layer, so a body portal would render underneath it; `fixed` escapes the dialog's overflow.
- Keyboard, closed: `Enter`, `Space`, `ArrowDown`, `ArrowUp` open with the selected option active (first enabled if none); `Home`/`End` open on first/last; printable characters open and jump (typeahead).
- Keyboard, open: `ArrowDown`/`ArrowUp` move active (skip disabled, no wrap); `Home`/`End`; `Enter` or `Space` select and close; `Tab` selects the active option and closes without preventing default; `Escape` closes without changing (and `stopPropagation` so a parent dialog stays open; also call `preventDefault`). Typeahead: 500ms buffer, match on `label` prefix, case-insensitive.
- Mouse/touch: click toggles; `pointerdown` outside closes; hovering an option makes it active; click selects. Focus never leaves the trigger. Active option is kept visible with `scrollIntoView({ block: "nearest" })`.
- Label click focuses the trigger. `hint`/`error` wired with `aria-describedby`; `error` sets `aria-invalid`.

**`SegmentedControl.tsx`** — 2 to 5 short, mutually exclusive options; also filter chips.

```ts
export interface SegmentOption<V extends string = string> { value: V; label: string; count?: number; disabled?: boolean }
export interface SegmentedControlProps<V extends string = string> {
  options: SegmentOption<V>[];
  value?: V | null;              // controlled when the prop is present (not undefined). null = controlled with nothing selected
  defaultValue?: V;              // uncontrolled initial value
  onChange?: (value: V) => void;
  name?: string;                 // radio group name; defaults to useId()
  label?: string; "aria-label"?: string;
  variant?: "track" | "chips";   // track = one sunken rounded-lg bar with a white selected thumb; chips = separate rounded-full pills that wrap
  size?: "sm" | "md";            // 36px / 44px
  fullWidth?: boolean;           // track only: options share the width equally
  className?: string;
}
```
Implementation: `<div role="radiogroup" aria-label|aria-labelledby>`; each option is a `<label>` wrapping `<input type="radio" class="sr-only peer" name value>` and a styled `<span>`. Native radios give arrow-key navigation, a single tab stop and FormData for free. Selected: track `bg-white shadow-sm font-medium text-ink`; chips `bg-brand-600 text-white`. Unselected chips `bg-white ring-1 ring-line text-ink-muted hover:text-ink`. Focus: `peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500 peer-focus-visible:ring-offset-2`. `count` renders as `tabular-nums opacity-70` after the label. Clicking the selected option does nothing.

**`ChoiceCards.tsx`** — 2 to 4 options that deserve a sentence of explanation.

```ts
export interface ChoiceOption<V extends string = string> {
  value: V; label: string; description?: string;
  icon?: React.ReactNode;       // 20px lucide icon
  badge?: string;               // e.g. "Recommended"
  disabled?: boolean;
}
export interface ChoiceCardsProps<V extends string = string> {
  options: ChoiceOption<V>[];
  value?: V; defaultValue?: V; onChange?: (value: V) => void;
  name?: string;
  label?: string; "aria-label"?: string; hint?: string;
  columns?: 1 | 2 | 3 | 4;      // at sm and up; always 1 column below sm
  className?: string;
}
```
Same native-radio technique. Card: `relative flex cursor-pointer gap-3 rounded-xl bg-white p-4 ring-1 ring-line transition hover:ring-ink-faint`; selected `ring-2 ring-brand-500 bg-brand-50/60` plus a filled check circle top-right (unselected: empty circle `ring-1 ring-line-field`). Label `text-sm font-semibold`, description `text-sm text-ink-muted`, badge is a `Badge tone="brand"`. Group label rendered like a field label; `hint` below.

**`Tabs.tsx`** (`"use client"`)

```ts
export interface TabItem { id: string; label: string; count?: number }
export function Tabs(props: { tabs: TabItem[]; value: string; onChange: (id: string) => void; "aria-label": string; className?: string }): JSX.Element;
export function TabPanel(props: { id: string; active: boolean; children: React.ReactNode; className?: string }): JSX.Element | null;
```
APG tabs, automatic activation: `role="tablist"`; each `<button role="tab" id="tab-{id}" aria-selected aria-controls="panel-{id}" tabIndex={selected ? 0 : -1}>`; `ArrowLeft`/`ArrowRight` move and activate (wrap), `Home`/`End`. `TabPanel` renders `<div role="tabpanel" id="panel-{id}" aria-labelledby="tab-{id}" tabIndex={0}>` only when `active`. Visual: underline tabs on a `border-b border-line` rail, selected `border-b-2 border-brand-600 text-ink font-medium`, others `text-ink-muted`; rail scrolls horizontally on mobile (`overflow-x-auto`), counts as small `Badge`.

**`Stepper.tsx`**

```ts
export interface StepItem { id: string; label: string; description?: string }
export function Stepper(props: {
  steps: StepItem[];
  current: number;                       // index of the active step; steps.length = all complete
  orientation?: "horizontal" | "vertical";
  "aria-label": string;
  showLabelsOnMobile?: boolean;          // horizontal only; default false → mobile shows "Step 2 of 3 · Label" text instead of per-step labels
  activeLabel?: React.ReactNode;         // optional replacement node for the active step's label (used to pass <ShinyText/>)
  className?: string;
}): JSX.Element;
```
`<ol aria-label>`; each `<li aria-current={active ? "step" : undefined}>`. Marker 28px circle: complete `bg-brand-600 text-white` with `Check`; active `bg-white ring-2 ring-brand-600 text-brand-700` with the number (vertical + active: a small `Spinner` instead of the number); upcoming `bg-surface-sunken text-ink-faint`. Connector `bg-line`, completed part `bg-brand-600`. Each `li` includes `<span class="sr-only">Completed: </span>` / `Current: ` / `Not started: ` before the label.

**`Checkbox.tsx`**

```ts
export const Checkbox: React.ForwardRefExoticComponent<
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & { label: React.ReactNode; description?: React.ReactNode } & React.RefAttributes<HTMLInputElement>
>;
```
Whole row is the `<label>` (`flex items-start gap-3 rounded-lg p-3 -m-3 cursor-pointer hover:bg-surface-sunken`). Native input styled `h-5 w-5 rounded-md border-line-field accent-brand-600` with `focusRing`.

**`Disclosure.tsx`**: `({ summary, defaultOpen, children, className }: { summary: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode; className?: string })`. Native `<details>`/`<summary>`; hide the default marker (`list-none [&::-webkit-details-marker]:hidden`), show `ChevronRight` that rotates 90° via `group-open:rotate-90`; summary `text-sm font-medium text-brand-700` with `focusRing rounded-md`.

### 2.3 Call sites of the removed native `Select` (must all be migrated)

| File | Owner | Replacement |
|---|---|---|
| `components/TailorForm.tsx` (resume, version) | WP2 | section 4.2.1 |
| `app/(app)/resumes/[id]/ResumeDetailView.tsx` (version) | WP3 | `Select size="sm"` |
| `app/(app)/resumes/new/GuidedBuilder.tsx` (add section) | WP3 | chip buttons |
| `app/(app)/applications/Applications.tsx` (filter, row status, dialog status, dialog resume) | WP3 | `SegmentedControl variant="chips"`, `Select variant="pill"`, `Select`, `Select` |
| `app/(app)/settings/Settings.tsx` `PreferencesCard` (4) | WP3 | `ChoiceCards` ×3, `SegmentedControl` ×1 |

## 3. Vendored effects — `components/fx/` (WP1)

Five components. Copy the **TypeScript + Tailwind** variant from the source site, then adapt as listed. Each file starts with this header (fill in):

```ts
/**
 * Source: <exact URL>
 * Origin: Aceternity UI (free component; not redistributable as a template/kit) | React Bits (MIT + Commons Clause)
 * Vendored: <date>. Local changes: <list>.
 */
```

If a source version imports anything other than `react` or `motion/react` (for example `gsap`), do not use it; implement the fallback described.

| File | Source | Used in | Why |
|---|---|---|---|
| `AuroraBackground.tsx` | Aceternity "Aurora Background" — `https://ui.aceternity.com/components/aurora-background` | Auth layout only (WP1) | First impression. CSS-only gradient drift; zero JS cost. |
| `DotBackground.tsx` | Aceternity "Grid and Dot Backgrounds" (dot variant) — `https://ui.aceternity.com/components/grid-and-dot-backgrounds` | Onboarding layout, `EmptyState`, progress card | Gives empty areas texture without a box. Static CSS. |
| `ShinyText.tsx` | React Bits "Shiny Text" — `https://reactbits.dev/text-animations/shiny-text` | Active step label on the progress screen (WP2) | Signals "working" without a second spinner. CSS-only. |
| `CountUp.tsx` | React Bits "Count Up" — `https://reactbits.dev/text-animations/count-up` | Review summary score numbers (WP2) | Makes the before → after improvement land. Only consumer of `motion`. |
| `SpotlightCard.tsx` | React Bits "Spotlight Card" — `https://reactbits.dev/components/spotlight-card` | Payment dialog plan cards (WP2), auth value panel (WP1) | Pointer-follow highlight on the two pricing choices. No dependency. |

APIs (fixed; WP2 codes against these):

```ts
// AuroraBackground.tsx — "use client" not required
export function AuroraBackground(props: { children: React.ReactNode; className?: string; showRadialGradient?: boolean }): JSX.Element;
// DotBackground.tsx — purely decorative layer: absolute inset-0, aria-hidden, pointer-events-none
export function DotBackground(props: { fade?: boolean; className?: string }): JSX.Element;
// ShinyText.tsx
export function ShinyText(props: { text: string; disabled?: boolean; speed?: number /* seconds, default 3 */; className?: string }): JSX.Element;
// CountUp.tsx — "use client"
export function CountUp(props: { to: number; from?: number; duration?: number /* seconds, default 1.2 */; className?: string }): JSX.Element;
// SpotlightCard.tsx — "use client"
export function SpotlightCard(props: { children: React.ReactNode; className?: string; spotlightColor?: string }): JSX.Element;
```

Adaptations:
- **AuroraBackground**: light mode only. Replace the colour stops with brand colours (`#3b63d9`, `#93adf8`, `#bfd0fd`, `#c4b5fd`, `#5f84ea`). Remove the `h-[100vh]` and flex centring from the root so the layout controls size; root is `relative overflow-hidden bg-surface-page`. Uses the `animate-aurora` keyframe from section 1.1. Opacity of the aurora layer at most `opacity-40`.
- **DotBackground**: `<div aria-hidden className={cx("pointer-events-none absolute inset-0 [background-size:20px_20px] [background-image:radial-gradient(#d4d9e3_1px,transparent_1px)]", fade && "[mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]", className)} />`. The parent must be `relative` and its content `relative`.
- **ShinyText** fallback (use as-is if the source needs more than CSS): `<span className={cx("bg-clip-text text-transparent bg-[linear-gradient(110deg,#0f172a_40%,#5f84ea_50%,#0f172a_60%)] bg-[length:200%_100%]", !disabled && "animate-shine", className)} style={{ animationDuration: `${speed}s` }}>{text}</span>`. The gradient's darkest stop is `ink`, lightest `brand-400` only in a narrow band, so text stays readable; under reduced motion the global rule stops it.
- **CountUp**: keep `useInView` (`once: true`), `useMotionValue`, `useSpring`. Add: if `window.matchMedia("(prefers-reduced-motion: reduce)").matches`, render `to` immediately. Render `Math.round` values with `tabular-nums`. Add `aria-hidden` on the animated span and a sibling `<span className="sr-only">{to}</span>` so screen readers get the final number once.
- **SpotlightCard**: default `spotlightColor="rgba(59, 99, 217, 0.12)"`; light surface (`bg-white ring-1 ring-line rounded-xl`); the highlight layer is `pointer-events-none`; no effect on touch devices is fine.

Performance guard: none of these may be imported by `dashboard`, `applications`, `settings`, `resumes/**`. `CountUp` (and therefore `motion`) is imported only from `app/(app)/tailor/[id]/`.

## 4. Screens and flows

### File ownership (no file appears in two packages)

| WP1: foundation, shell, auth, onboarding | WP2: tailoring | WP3: library and account |
|---|---|---|
| `package.json`, `package-lock.json`, `tailwind.config.ts`, `app/globals.css`, `app/layout.tsx` | `components/TailorForm.tsx` | `app/(app)/dashboard/*` |
| `components/ui/*` (all, incl. new files and `index.ts`) | `components/PaymentDialog.tsx` | `components/BillingMeter.tsx` |
| `components/fx/*` | `app/(app)/tailor/new/*` | `app/(app)/resumes/*` (incl. `VersionList`, `[id]/*`, `new/*`) |
| `lib/diff.ts`, `lib/diff.test.ts`, new `lib/consent.ts` | `app/(app)/tailor/[id]/*` (Review, Progress, ChangeReview, ExportBar, ScoresPanel, SimulationPanel, GapsPanel, plus new files in that folder) | `app/(app)/applications/*` |
| new `components/ConsentDialog.tsx` | | `app/(app)/settings/*` |
| `components/shell/*`, `app/(app)/layout.tsx` | | `components/ResumeUpload.tsx` (owner of record; **no edits**) |
| `app/(auth)/*`, `components/AuthForm.tsx` | | |
| `app/(focus)/*` (layout + Onboarding), `app/not-found.tsx` | | |

Order: WP1 lands first if possible. WP2 and WP3 can start immediately against sections 2 and 3. `lib/format.ts`, `lib/hooks.ts`: no changes by anyone.

### 4.1 WP1

#### 4.1.1 `lib/consent.ts` (new) — device-local hint, because the API has no "read consent" endpoint

```ts
export type ConsentHint = "granted" | "declined" | null;
export function getConsentHint(): ConsentHint;          // reads localStorage "rt_ai_consent"; null on server or when unset; never throws
export function setConsentHint(v: Exclude<ConsentHint, null>): void;
```
It is only a hint for UI copy. The server's 428 remains the source of truth.

#### 4.1.2 `components/ConsentDialog.tsx` (new) — fixes the 428 dead end

```ts
/** The three explanatory points, shared by onboarding and the dialog. */
export function ConsentPoints(props: { compact?: boolean }): JSX.Element;
/** Asks for AI-processing consent in place. Calls api.grantConsent(true), setConsentHint("granted"), then onGranted(). */
export function ConsentDialog(props: { open: boolean; onClose: () => void; onGranted: () => void | Promise<void>; confirmLabel?: string }): JSX.Element;
```
- `ConsentPoints`: three rows, each a 40px `rounded-lg bg-brand-50 text-brand-600` icon tile + title + one or two sentences. No surrounding Card. Copy:
  1. `Send` icon, "Your text goes to AI providers" — "To tailor your resume, its text and the job description are sent to Anthropic (Claude) and OpenAI-compatible model APIs. Only the text needed for each step is sent. Your original files stay with RoleTailor."
  2. `ShieldCheck`, "Nothing is invented" — "We only rephrase and reorder what you wrote. Skills the job asks for that you don't show are listed as gaps, never added."
  3. `Gift`, "Fair credits" — "Your first 10 tailored resumes are free. Re-runs on the same job are free. Failed runs never count."
  With `compact`, only titles and the first sentence of each.
- `ConsentDialog`: `Dialog size="md"` title "One thing before we start", description "We need your OK to process your resume with AI. You can withdraw it any time in Settings." Body: `<ConsentPoints compact />`, then `Checkbox` "I agree to my resume and job descriptions being processed by these AI providers." Footer: `Button variant="secondary"` "Not now" (closes), `Button` `{confirmLabel ?? "Agree and continue"}` disabled until checked, `loading` while saving. Errors in an `Alert tone="error"` inside the dialog. On success call `onGranted()` then `onClose()`.

#### 4.1.3 Shell: `components/shell/AppNav.tsx`, `Logo.tsx`, `app/(app)/layout.tsx`

- Top bar: `h-16`, `bg-white/90 backdrop-blur border-b border-line`, container `max-w-5xl`. Desktop links: `px-3 py-2 rounded-lg text-sm`; active `bg-brand-50 text-brand-700 font-medium`. Rename nav label "Dashboard" → "Tailored resumes" (route stays `/dashboard`).
- Right side: "New tailoring" `buttonClass("primary","md")` (desktop); sign out becomes a visible `ghost` button with icon **and text** "Sign out" at `lg`, icon-only `IconButton label="Sign out"` below `lg`.
- Mobile (`< md`): remove the hamburger and the dropdown panel. Add a fixed bottom tab bar: `<nav aria-label="Main" class="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white pb-[env(safe-area-inset-bottom)] md:hidden">` with five equal items, each icon over a `text-xs` label, 56px tall: Tailored (`FileCheck2`, `/dashboard`), Resumes (`FileText`), **New** (centre; `Plus` in a 44px `bg-brand-600 text-white rounded-full` circle, `/tailor/new`), Tracker (`Briefcase`, `/applications`), Settings (`Settings`). Active item `text-brand-700` with `aria-current="page"`. The mobile top bar keeps Logo + sign-out `IconButton`. The desktop `<nav>` gets `aria-label="Main"`; give the mobile one `aria-label="Main, mobile"` to avoid duplicate landmark names.
- `app/(app)/layout.tsx`: `<main id="main" className="mx-auto max-w-5xl px-4 pb-28 pt-8 sm:px-6 md:pb-16 md:pt-10">`.
- `Logo`: mark `h-8 w-8 rounded-lg bg-brand-600`; text `text-base font-semibold`.

#### 4.1.4 Auth: `app/(auth)/layout.tsx`, `components/AuthForm.tsx`

- Layout: `<AuroraBackground>` wraps the page (`min-h-screen`). Inside, a centred `max-w-5xl` grid: one column on mobile, `lg:grid-cols-2 gap-12 items-center`.
  - Left (hidden below `lg`): Logo, headline "Tailor your resume to every role. Honestly." (`text-3xl`), three checkmark lines: "Only rephrases what you wrote, nothing invented", "See and approve every change", "10 tailored resumes free, no card". Below, one `SpotlightCard` showing a static mini "64 → 91 ATS match" illustration built from `ScoreRing` (purely decorative, `aria-hidden`).
  - Right: the form card `w-full max-w-md rounded-2xl bg-white/95 p-7 sm:p-8 shadow-pop ring-1 ring-slate-900/5`. On mobile the Logo sits above the card.
- `AuthForm`:
  - Headings: login "Welcome back" / sub "Sign in to pick up where you left off."; register "Create your account" / sub "10 free tailored resumes. No card required."
  - Fields: `Input` with `leading` icons (`User`, `Mail`); password uses `PasswordInput` (keep `name="password"`). Keep `name="email"`, `name="full_name"`, `noValidate`, and all validation and submit logic unchanged.
  - Submit: `Button size="lg" className="w-full"`; keep `type="submit"`. Loading text "Signing in…" / "Creating your account…".
  - On validation failure, focus the first invalid field.
  - Footer link text unchanged; link gets `focusRing rounded`.

#### 4.1.5 Onboarding: `app/(focus)/layout.tsx`, `Onboarding.tsx`

- Layout: header without border (`bg-transparent`), `<DotBackground fade />` behind the top 320px of the page (wrapper `relative`), main `max-w-xl`.
- Replace the hand-built `<ol>` with `<Stepper aria-label="Getting started" steps=[{id:"consent",label:"Privacy"},{id:"resume",label:"Your resume"},{id:"job",label:"First job"}] current={idx} />`.
- Each step's content sits in one `Card` (`p-6 sm:p-8`), entering with `animate-fade-in`. Move focus to the step's `h1` (`tabIndex={-1}`, `ref.focus()`) when `step` changes.
- **Consent step**: remove the `ShieldCheck` hero icon and the inner Card. Title "Before we start: how we use AI". Sub "Takes 20 seconds. You can change your mind any time in Settings." Then `<ConsentPoints />`, a `border-t border-line` divider, the `Checkbox` (same label text as today), error `Alert`, and buttons: `Button size="lg"` "Agree and continue" (disabled until checked) and `Button variant="ghost"` **"Decide later"**.
  - "Agree": existing `consent()` plus `setConsentHint("granted")`.
  - **Flow fix**: "Decide later" no longer links to `/dashboard`. It calls `setConsentHint("declined")` and `setStep("resume")`. Under the buttons: `text-sm text-ink-muted` "If you skip this, we'll ask again right before your first tailoring." Uploading a resume does not need consent; the tailoring form now handles the 428 (section 4.2.1).
- **Resume step**: title "Add your resume", sub "Upload what you have. You'll see exactly what we read." `<ResumeUpload>` unchanged props. Below, replace the bordered row with a `Card variant="sunken"` row: `FilePlus2` icon, "No resume handy?" + "Build one step by step.", `ButtonLink variant="secondary" size="sm"` "Build from scratch" (same href).
- **Job step**: title "Which job are you going for?", sub "Paste the link or the description. We'll do the rest." `<TailorForm initialVersionId={versionId} />` unchanged props. "Skip for now" becomes `Button variant="ghost"`.
- `app/not-found.tsx`: use `EmptyState` with `ButtonLink` back to `/dashboard`.

### 4.2 WP2

#### 4.2.1 `components/TailorForm.tsx` and `app/(app)/tailor/new/NewTailoring.tsx`

Public props unchanged: `{ initialVersionId?: string; defaultPageLimit?: number }`.

`NewTailoring`: keep `max-w-2xl`, title "New tailoring", description "Tell us the job. We'll tailor your resume and show you every change." Keep the single `Card`; body padding `p-6 sm:p-8`.

Form layout: three `Section`-style blocks separated by `space-y-8`, **no numbered legends**. Use `<fieldset>` + visually styled `<legend class="text-base font-semibold">`.

1. **"The job"** (first, it is the user's actual input)
   - Replace the role="tab" toggle and the two inputs with **one** field: `Textarea autoGrow rows={3} label="Job link or description" placeholder="Paste a link (https://…) or the full job description"`.
   - State: replace `jobMode`, `jobUrl`, `jobText` with `jobInput: string`. Derive `const trimmed = jobInput.trim(); const isUrl = /^https?:\/\/\S+$/i.test(trimmed);`.
   - Live helper under the field (`aria-live="polite"`, `text-sm`): empty → "Either works. A pasted description is the most reliable."; `isUrl` → `Link2` icon + "Link detected. We'll read the posting for you."; otherwise → "Description · {trimmed.length.toLocaleString()} characters" and, if `< 80`, " · keep going, we need a few sentences".
   - `ensureJob` body: `isUrl ? { source_url: trimmed, title, company } : { description: trimmed, title, company }` (same optional handling as today).
   - Validation in `start`: empty → "Paste the job link or description."; not URL and `< 80` chars → existing message.
   - On `job_url_unreadable`: keep the warning text, set `jobInput("")`, focus the textarea. Message: "We couldn't read that page (some sites block us). Paste the job description text here instead."
   - Optional title/company: `Disclosure summary="Add role title and company (optional)"` with the two `Input`s.
2. **"Your resume"**
   - Keep the existing effects that pick the default resume and load versions.
   - **Collapsed summary** when `resumes.data.length === 1` or `initialVersionId` is set, and the user has not clicked Change: a `surface-sunken rounded-lg px-4 py-3` row: `FileText` icon, resume name (`font-medium`), `text-sm text-ink-muted` "Latest version (v{n} · {date})" or "Version v{n} · {date}", and a `Button variant="ghost" size="sm"` "Change".
   - **Expanded** (more than one resume, or after Change): resume picker = `ChoiceCards columns={2}` when there are 2 to 4 resumes (label = name, description = "v{latest} · added {date}"); `Select label="Resume"` when more than 4 (description = same). Version: a single line "Using the latest version (v{n})." with a `ghost` "Pick an older version" button that reveals `Select label="Version"` (`options` = "v{n} · {date}", first one description "Latest"). While `versions === null` show `Skeleton className="h-12"`.
3. **"Length"**: `ChoiceCards columns={3} name="page_limit"` with the existing `PAGE_OPTIONS`; values are strings `"1" | "2" | "3"` converted with `Number()`; `badge: "Recommended"` on 2 pages and shorten its hint to "Right for most roles".

Footer: error `Alert`; then `Button type="submit" size="lg"` "Start tailoring" with an `ArrowRight` icon, and the reassurance line as `text-sm text-ink-muted` with a `ShieldCheck` icon.

**Flow fix (428 consent)**: add `const [consentOpen, setConsentOpen] = useState(false)`. In the `createWorkflow` catch, replace the 428 branch with `setConsentOpen(true); return;` (remove the link to `/onboarding`). Render `<ConsentDialog open={consentOpen} onClose={() => setConsentOpen(false)} onGranted={() => start(false)} confirmLabel="Agree and start tailoring" />`. `jobCache` already prevents creating the job twice. The form state is untouched, so nothing the user typed is lost.

No-resume state: replace the `Alert` with a compact `EmptyState`-like block inside the card: title "Add a resume first", buttons "Upload a resume" (`/resumes`) and "Build one" (`/resumes/new`).

#### 4.2.2 `components/PaymentDialog.tsx`

Logic unchanged. Visual: `Dialog size="lg"`, title "You've used your free tailorings". Plan options are two `SpotlightCard`s (still `<button>`s with the same handlers): icon tile, title, price (`text-2xl font-semibold`), body, and a `soft` pill "Secure checkout ↗"; the subscription card gets `Badge tone="brand"` "Best value". Selected/started state `ring-2 ring-brand-500`. After checkout starts, the info `Alert` reads "Checkout opened in a new tab. Finish there, then come back and press the button below." Footer buttons unchanged in behaviour; primary label "I've paid, start tailoring" / "Use paid credit and start".

#### 4.2.3 `app/(app)/tailor/[id]/Review.tsx` (page frame)

- Use `PageHeader back={{ href: "/dashboard", label: "Tailored resumes" }} meta={…}`; title unchanged. `meta`: `StatusBadge`, "Version {latest.iteration}" (rename "Iteration" → "Version" in UI copy only), approved badge `Badge tone="green"` "Approved".
- Pause/Cancel/Resume buttons move out of the header: while active they are rendered inside the Progress card (pass `onPause`, `onCancel` to `Progress`). The paused state shows an `Alert tone="warning" title="Paused"` with `action={<Button size="sm">Resume</Button>}`.
- Cancel asks for confirmation (`Dialog size="sm"`, "Stop this tailoring?", "Nothing is charged for a cancelled run.", buttons "Keep going" / "Stop").
- Failed and cancelled alerts: same logic and copy; use the new `Alert action` slot for the buttons.
- Loading: `SkeletonRows rows={4}`.
- When `latest` exists, render in this order: `<ResultSummary>` (new, 4.2.5), then `Tabs` with panels (4.2.6). Remove the `lg:grid-cols-2` scores/simulation grid and the stacked panels.
- When an iteration is running over an existing result (`isActive && hasResult`), show the Progress card in compact form above the summary and disable decision controls (`busy` prop, as today).

#### 4.2.4 `Progress.tsx`

Props: existing plus `onPause?: () => void; onCancel?: () => void; compact?: boolean`.
- Card `relative overflow-hidden` with `<DotBackground fade />`; content `relative mx-auto max-w-md py-10 text-center` (compact: `py-5`, left-aligned, steps hidden, only title + bar).
- Title (`h2`, `aria-live="polite"`): same three strings as today. Sub: "Usually under a minute. You can leave this page; we'll keep going."
- A thin progress bar `h-1.5 rounded-full bg-surface-sunken` with a `bg-brand-500` fill at `((current + 1) / STEPS.length) * 100%`, `transition-[width] duration-700`, `role="progressbar" aria-valuemin={0} aria-valuemax={6} aria-valuenow={current + 1} aria-label="Tailoring progress"`.
- Steps: `<Stepper orientation="vertical" aria-label="Tailoring steps" steps={STEPS.map(s => ({ id: s.key, label: s.label }))} current={current} activeLabel={<ShinyText text={STEPS[current].label} />} />`, left-aligned inside the centred column. Remove the standalone header spinner.
- Shorten the last label to "Scoring the result".
- Footer row: `ghost` `sm` buttons "Pause" and "Cancel" (if handlers given) and a link "Back to tailored resumes".

#### 4.2.5 `ResultSummary.tsx` (new, in `tailor/[id]/`) — merges `ExportBar` + headline of `ScoresPanel`

Props: `{ generated: GeneratedResume; before: Scores | null; onApproved: (g: GeneratedResume) => void }`. Move all `ExportBar` logic here and delete `ExportBar.tsx` (or keep the file exporting `ResultSummary`; one of the two, no dead code).

One `Card`, two zones (`grid gap-6 md:grid-cols-[1fr_auto] items-center`):
- Left: eyebrow `text-sm text-ink-muted` "ATS match". Big number row: if `before`, `<span class="text-2xl text-ink-muted tabular-nums">{before.ats}</span> <ArrowRight/> <CountUp from={before.ats} to={latest.ats_score} className="text-5xl font-semibold" />` and a `Badge tone="green"` "+{delta}"; without `before` or score, just the number (or "—"). Wrap in an element with `aria-label="ATS match: before {x}, after {y}"`. Under it, three `ScoreChip`-style deltas in a wrapping row: "Job alignment 58 → 86", "Keywords 49 → 89", "Formatting 90 → 94". Then `Disclosure summary="See score breakdown"` containing the four `ScoreBar`s (content of today's `ScoresPanel`; delete the two rings and delete `ScoresPanel.tsx` or reduce it to the bars).
- Right (full width on mobile): heading `text-sm font-medium` "Download"; buttons stacked on desktop, 2-column grid on mobile: `Button` primary "Word (.docx)", `secondary` "PDF", `secondary` "ATS report"; then `ghost` **"Share link"** (keep this exact accessible name). Below: `text-xs text-ink-muted` "Includes every rewrite you haven't turned off."
- Approve: under the left zone a quiet row: not approved → `Button variant="soft" size="sm"` "Mark as final" with helper "Locks this version as the one you sent."; approved → `CheckCircle2` + "Marked as final". Same `api.approve` call and toast.
- Share dialog: `Input readOnly` plus a `Button` "Copy link" that writes to the clipboard and switches to "Copied" with a `Check` icon for 2s; `footer` "Done".

#### 4.2.6 Tabs in `Review.tsx`

`const [tab, setTab] = useState("changes")`. Tabs: `{ id: "changes", label: "Changes", count: changes.length }`, `{ id: "gaps", label: "Missing keywords", count: gaps.length }`, `{ id: "feedback", label: "Hiring-manager view" }`. `aria-label="Result details"`. On mount, if `location.hash === "#iterate"` keep `changes` selected and scroll `#iterate` into view after first render with data (the dashboard links there).

- **Changes panel** = `ChangeReview` (4.2.7).
- **Missing keywords panel** = `GapsPanel`: drop the Card wrapper (use `Section title="Missing keywords" description="The job asks for these, but your resume doesn't show them. We did not add them."`); badges as today (`Badge` with "required" suffix); the advice paragraph becomes an `Alert tone="info"` with `action={<ButtonLink size="sm" variant="secondary" href="/resumes">Update my resume</ButtonLink>}`. Empty state text unchanged, as `Alert tone="success"`.
- **Hiring-manager view panel** = `SimulationPanel`: drop the dashed Card; `Section title="Hiring-manager view"`; first element is `Alert tone="warning"` "This is an AI simulation, not a prediction of hiring outcomes." Then a row: big score (`text-4xl font-semibold tabular-nums`) + "Simulated interview likelihood" `Badge` (capitalised). Then the four `ScoreBar`s in `sm:grid-cols-2`. Then three columns from `md` (stacked on mobile) "Strengths" (`ThumbsUp`), "Weaknesses" (`AlertTriangle`), "Suggestions" (`Lightbulb`): plain lists with `divide-y divide-line`, no nested `<details>`. `competitive_positioning` as a closing paragraph.

#### 4.2.7 `ChangeReview.tsx`

Remove the outer `Card` + `CardHeader`. Structure:

1. Header (`Section`): `<h2>` **"Review changes"** (keep this text). Description: "Each one is a rewrite of your own words. Every rewrite is included in your download unless you choose Keep original."
2. Toolbar row (wraps): left, a progress text `aria-live="polite"`: "{accepted + rejected} of {all} reviewed" with a thin bar; middle, filter `SegmentedControl variant="chips" size="sm" aria-label="Filter changes"` with options All / To review / Using rewrite / Keeping original (values `all | pending | accepted | rejected`, with counts); right, `Button variant="soft" size="sm"` "Use all remaining rewrites" (hidden when `counts.pending === 0`; runs `decide(c, "accepted")` sequentially for each pending change, shows `loading`, one toast "Accepted {n} rewrites." at the end).
3. List: `<ul class="space-y-4">`; each change is one `Card variant="flat"` (`p-5`), no coloured border. Rejected items: content at `opacity-60` except the controls.
   - Top line: `text-sm font-medium` "Change {index + 1}" (index in the full `changes` array; **do not show `block_path`**), then state `Badge`: pending → `neutral` "To review"; accepted → `green` "Using rewrite"; rejected → `neutral` "Keeping original"; if selected for regeneration → `brand` "Will be rewritten".
   - `DiffView before after`.
   - "Why" line: `text-sm text-ink-muted` with `Sparkles` icon; keywords as `Badge tone="brand"` after a `sr-only` "Prioritised keywords:".
   - Controls row (`flex flex-wrap items-center gap-3`, `border-t border-line pt-4 mt-4`):
     - `SegmentedControl size="sm" aria-label="Decision for change {n}"` options `{ value: "accepted", label: "Use rewrite" }`, `{ value: "rejected", label: "Keep original" }`; `value={c.decision === "pending" ? null : c.decision}` (null = controlled, nothing selected); `onChange={(d) => decide(c, d)}`; every option `disabled` while `saving === c.id || busy`.
     - When `c.decision !== "pending"`: `Button variant="ghost" size="sm"` "Undo" → `decide(c, "pending")`.
     - Right-aligned: `Button variant="ghost" size="sm" aria-pressed={selected.has(c.id)}` with `RefreshCw` icon, label "Ask for another version" (pressed: "Selected for rewrite"). Replaces the checkbox.
   - **Flow fix (silent toggle)**: change `decide` to `async function decide(c, decision: ChangeDecision)` that sends exactly `decision` (delete the `c.decision === decision ? "pending" : decision` line) and returns early if `c.decision === decision`. Optimistic update and rollback logic stay.
   - Empty filter result: "Nothing here. Switch the filter to see other changes."
4. Regenerate block: keep `id="iterate"` and `scroll-mt-24`. `Card variant="sunken"` (`p-5`): `h3` "Not quite right?"; text: selected > 0 → "We'll rewrite the {n} change(s) you selected."; else "We'll rewrite everything. Or pick specific changes above with “Ask for another version”." plus "Re-runs on this job are free."; `Textarea autoGrow rows={2} label="Tell us what to change" optional placeholder="e.g. Shorter. Emphasise stakeholder management."`; `Button variant="secondary"` "Rewrite selected" / "Rewrite everything". Same `regenerate()` logic.
5. When `selected.size > 0`, show a sticky bar at the bottom of the viewport (`sticky bottom-20 md:bottom-4 z-30`, `rounded-xl bg-ink text-white shadow-pop px-4 py-3 flex items-center gap-3`): "{n} selected for rewrite", `Button size="sm" variant="secondary"` "Rewrite selected" (calls `regenerate`), `ghost` "Clear".

### 4.3 WP3

#### 4.3.1 `app/(app)/dashboard/Dashboard.tsx`

- `PageHeader title="Tailored resumes" description="One for each job you've gone for. Newest first." actions={<BillingMeter />}`.
- **Consent nudge**: if `getConsentHint() === "declined"` (read in `useEffect` to avoid hydration mismatch), show above the list `Alert tone="info" title="One step left before you can tailor"` "We need your OK to process your resume with AI." with `action={<Button size="sm" onClick={open ConsentDialog}>Review</Button>}`; render `<ConsentDialog>`; on granted hide the alert.
- **Delete the desktop `<table>` and the separate mobile list.** One responsive list for all widths: `<ul class="space-y-3">`, each `<li>` a `Card variant="raised"` containing:
  - Main row `flex items-start gap-4 p-4 sm:p-5`:
    - Text block `min-w-0 flex-1`, wrapped in `<Link href={/tailor/{id}}>` (`focusRing rounded-lg`, group hover underlines the title): title `text-base font-medium` = `target_role ?? "Untitled role"`, `line-clamp-2` (**not** `truncate`); second line `text-sm text-ink-muted` = `{company ?? "Company not set"} · {resume_name ?? "Resume"}`, `line-clamp-2 break-words`; third line (wraps): `ScoreChip label="ATS match"`, `ScoreChip label="Manager sim" title="Hiring-manager simulation (AI)"`, date `text-xs text-ink-muted`.
    - Right: `StatusBadge`; then `IconButton` with `ChevronDown` (rotates when open), `aria-expanded`, `aria-controls="detail-{id}"`, `label={`${open ? "Hide" : "Show"} details for ${target_role ?? "workflow"}`}`.
  - Detail region `id="detail-{id}"` `border-t border-line p-4 sm:p-5` with `<RowDetail>` when open.
- **Live refresh**: while any row `isActive(status)`, poll every 5000ms with `api.workflows().then(setData)` (use `setData` from `useResource`, **not** `reload()`, which would flash the skeleton). Pause when `document.visibilityState !== "visible"`. Clear the interval on unmount.
- Empty state: title "Tailor your first resume", description "Add a job, and get a role-specific version with scores and a change-by-change review.", action "New tailoring", `secondaryAction` `ButtonLink variant="secondary" href="/resumes"` "Add a resume first".
- Loading: `SkeletonRows rows={4}` only when `loading && !data`.

#### 4.3.2 `RowDetail.tsx` — fixes "0 changes proposed" and dead buttons on running rows

Branch on `row.status` **before** rendering anything about changes or exports:
- `queued`/`running` and no `latest`: one line with a small `Spinner`: "Tailoring in progress. Usually under a minute." and `ButtonLink size="sm"` "View progress". Nothing else (no change count, no export buttons). Do not even wait for the detail request: render this immediately.
- `failed`: `text-sm` "This one didn't finish. Nothing was charged." + `ButtonLink size="sm" variant="secondary"` "See what happened".
- `cancelled`/`draft`/`paused` without `latest`: "No result yet." + "Open".
- With `latest`: two `ScoreBar`s; line "{n} rewrites, {pending} still to review" (omit the second part when 0; append " · Marked as final" when approved); gaps as today under the label "Missing keywords:"; actions row (wraps, not a fixed-width column): `ButtonLink size="sm"` "Open review", `Button size="sm" variant="secondary"` "Word", "PDF", and for `completed` `ButtonLink size="sm" variant="ghost"` "Ask for changes" (`#iterate`). Export buttons are only rendered when `latest` exists (never rendered disabled).

#### 4.3.3 `components/BillingMeter.tsx`

Compact pill: `inline-flex items-center gap-3 rounded-full bg-white px-4 py-2 shadow-card ring-1 ring-slate-900/5 text-sm`: "{free_limit - free_used} free left" (when 0: "Free tailorings used", amber bar), a 64px bar, and " · {n} paid" when credits > 0 (fixes "credit(s)" wording: "1 paid credit" / "2 paid credits" in the `aria-label`). Still a link to `/settings#billing` with `focusRing`. Subscription active → `Badge tone="green"` "Subscribed".

#### 4.3.4 `app/(app)/resumes/Resumes.tsx`, `VersionList.tsx`

- Header actions: `Button` "Upload" (keep the name starting with "Upload") and `ButtonLink variant="secondary"` "Build from scratch".
- List: `<ul class="space-y-3">` of `Card`s. Each row **stacks on mobile** (fixes the collapsed text column): `flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:p-5`.
  - Left: 44px `rounded-lg bg-brand-50 text-brand-600` tile with `FileText`; name link (`text-base font-medium break-words`); meta line `Badge` (Uploaded / Built here), "v{n}", "Added {date}".
  - Actions (`flex flex-wrap items-center gap-2`): `ButtonLink size="sm"` (primary) "Tailor"; `Button size="sm" variant="ghost"` "Versions" with `aria-expanded`; `IconButton label="Rename {name}"`; `IconButton label="Archive {name}"`.
- Versions panel (inside the same card, `border-t border-line`): `VersionList`.
- `VersionList`: remove the bordered/tinted box; plain `divide-y divide-line` list. Each row `flex flex-wrap items-center gap-x-3 gap-y-1 py-3 text-sm` (wraps instead of squeezing the date, fixes the narrow sidebar on the detail page): "v{n}" `font-medium`, date, `Badge tone="green"` "Current" on the first, link "View", `Button size="sm" variant="ghost"` "Restore".
- Dialogs: use the `footer` prop for button rows. Upload dialog `size="lg"`, `<ResumeUpload>` untouched.
- Empty state: add `secondaryAction` "Build from scratch".

#### 4.3.5 `resumes/[id]/ResumeDetailView.tsx`

- `PageHeader back={{ href: "/resumes", label: "Resumes" }}`; description "This is what we read from your file. Tailoring only ever uses this text."; action "Tailor this version".
- Version picker: `Select size="sm" aria-label="Version" value={versionId ?? ""} onChange={(v) => { setVersionId(v); router.replace(...) }} options={versions.map(x => ({ value: x.id, label: `v${x.version_number} · ${formatDate(x.created_at)}` }))}`.
- Extracted content card: remove the visible block ids (`b1`…): keep them as `sr-only` text and `title` on the row. Headings `text-base font-semibold mt-5`; body `text-base text-ink leading-relaxed` (it is the user's resume: make it read like a document, not a log). Locked blocks keep the `Lock` icon with `title`.
- Sidebar: findings use `Alert` (auto-restyled); humanise the title: `code.replace(/_/g, " ")` with first letter upper-cased. Section title "Things to check" (was "Extraction findings"). Remove the `(b2)` suffix; instead `text-xs` "Near: “{first 40 chars of that block's text}…”" when `block_id` resolves.
- Below `lg`, the sidebar comes **before** the extracted content (`order-first lg:order-none`) so findings are seen first.

#### 4.3.6 `resumes/new/GuidedBuilder.tsx`

Data handling, `clean`, `submit` unchanged. Layout changes only:
- "Resume name" and "Contact" merge into one `Card` titled "About you" (resume name last, with hint "Only you see this name.").
- Each section `Card`: header row = editable title shown as an `h2` with `IconButton label="Rename section"` that swaps it for the `Input` (label `sr-only`); to the right a compact group of `IconButton`s: "Move section up", "Move section down", "Delete {title} section".
- Entries: **no nested bordered boxes**. Entries are separated by `border-t border-line pt-5 mt-5`; each entry has a small caption "Entry {n}" with its move/remove `IconButton`s on the same line.
- Bullets: each bullet row = `Textarea autoGrow rows={1}` + `IconButton`s (up, delete). "Add bullet" is `Button variant="soft" size="sm"`.
- **Add a section**: delete the `Select` and the `addKind` state. Render a `Section title="Add a section"` with one `Button variant="secondary" size="sm"` per kind (`Plus` icon + `KIND_LABEL[k]`), each calling `setSections((xs) => [...xs, section(k)])` and then moving focus to the new section's heading.
- Sticky action bar at the bottom of the viewport (`sticky bottom-20 md:bottom-4`, white, `shadow-pop rounded-xl p-3 flex gap-3`): "Create resume" (primary, `type="submit"`), "Cancel" (ghost), and the error `Alert` above it.

#### 4.3.7 `applications/Applications.tsx`

- Filter: `SegmentedControl variant="chips" size="sm" aria-label="Filter by status"`, options "All" (value `"all"`, mapped to `""`) plus `STATUSES`, each with a `count`. Only show statuses that have at least one application, plus "All".
- Rows: `<ul class="space-y-3">` of `Card`s, **stacked on mobile**: `flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:p-5`.
  - Text: title `{role_title}` `text-base font-medium`; company on its own line `text-sm text-ink-muted`; meta row (wraps) with `Calendar` "Applied {date}", `FileText` "{resume label}", `Bell` reminder (due = `Badge tone="amber"` "Follow up due {date}"); notes `line-clamp-2`.
  - Actions: **remove the separate status `Badge`**; the status is the picker: `Select variant="pill" size="sm" aria-label={`Status for ${a.role_title}`} value={a.status} onChange={(s) => quickStatus(a, s)} options={STATUSES.map(s => ({ value: s.value, label: s.label, tone: s.tone }))}`; then `IconButton label="Edit {role}"`, `IconButton label="Delete {role}"`.
- Add/Edit dialog (`size="lg"`, button row via `footer` is not possible because buttons must be inside the `<form>`; keep them inside the form, styled as a footer row):
  - Company, Role: `Input required`.
  - Status: `Select name="status" label="Status" defaultValue={current?.status ?? "applied"}` (uncontrolled; FormData unchanged).
  - Resume: `Select name="resume_version_id" label="Resume sent" defaultValue={current?.resume_version_id ?? ""}` with first option `{ value: "", label: "Not set" }`.
  - Dates: native `type="date"` inputs kept (best mobile and screen-reader behaviour), restyled by `Input`; labels "Date applied", "Remind me to follow up" (`optional`).
  - Notes: `Textarea autoGrow optional`.
  - Validation: instead of a toast, set `error` on the Company/Role inputs ("Add the company." / "Add the role.") and focus the first.
- Keep the header button name "Add application".

#### 4.3.8 `settings/Settings.tsx`

Allowed edits, and nothing else in this file:
1. Add **one new import statement on the line directly after `"use client";`** for the new primitives (`ChoiceCards`, `SegmentedControl`, `Disclosure`, `Badge`) and one for `getConsentHint`/`setConsentHint`. Do not modify the existing import lines (the now-unused `Select` name in the existing `@/components/ui` import still resolves to the new component; leave it. Only if `npm run lint` reports it as an error rather than a warning, delete the token `Select, ` from that line and say so in the PR description, since PR #3 may touch the same line).
2. `Settings()`: no change needed.
3. `ProfileCard`: no change needed (restyles via primitives).
4. `PreferencesCard` body (all uncontrolled, same `name`s, so the submit handler is unchanged):
   - `ChoiceCards name="preferred_page_limit" label="Resume length" columns={3} defaultValue={String(user.preferred_page_limit ?? 2)}` options "1 page / Early career or concise", "2 pages / Right for most roles" (`badge: "Recommended"`), "3+ pages / Senior, academic or federal" (values `"1" "2" "3"`).
   - `ChoiceCards name="resume_tone" label="Tone" columns={2}` options: professional "Polished and neutral", confident "Leads with impact", concise "Short and direct", warm "Personable and human".
   - `ChoiceCards name="ats_preference" label="Who should it read best for?" columns={3}` options: balanced "Balanced" / "Good for both" (`badge: "Recommended"`), ats_first "Screening software" / "Simple structure, exact keywords", human_first "Human readers" / "Natural flow and voice".
   - `SegmentedControl name="technical_depth" label="Technical detail" fullWidth` options Light / Moderate / Deep; hint line "Light uses plain language. Deep keeps technical specifics."
   - `Input name="industry_focus"` unchanged, `optional`.
   - Replace `<details>` with `Disclosure summary="Advanced"` containing the Template ID input (unchanged name and hint).
5. `BillingCard`: **no edits.**
6. `DataCard`: consent row shows state from `getConsentHint()` (read in `useEffect`): `Badge tone="green"` "Given on this device" / `Badge tone="amber"` "Not given" / nothing when unknown. Buttons: hint `granted` → only "Withdraw consent" (`secondary`); `declined` → only "Give consent" (primary); unknown → both, labelled "Give consent" and "Withdraw consent". Withdraw opens a confirm `Dialog size="sm"`: "Withdraw AI consent?" / "You won't be able to tailor resumes until you give it again. Existing results stay available." / "Keep consent" + "Withdraw". After each successful call, `setConsentHint(...)`. Rows separated by `border-t border-line` (already the case). Delete-account dialog: unchanged logic; use `Dialog` `footer` for the buttons.

## 5. Copy glossary (use consistently)

| Old | New |
|---|---|
| Dashboard (nav and title) | Tailored resumes |
| HM sim. | Manager sim (list chips) / Hiring-manager view (tab) |
| ATS | ATS match |
| Iteration N | Version N |
| Iterate | Ask for changes |
| Regenerate | Rewrite |
| Accept / Reject | Use rewrite / Keep original |
| pending / accepted / rejected | To review / Using rewrite / Keeping original |
| Keyword gaps | Missing keywords |
| Approve | Mark as final |
| Extraction findings | Things to check |
| Free generations 3/10 | 7 free left |
| Not now (consent) | Decide later |

## 6. Acceptance checklist

Build and regressions
- [ ] `npm run typecheck`, `npm run lint`, `npm test`, `npm run build` pass. New `diffPhrases` tests exist.
- [ ] `git diff --stat` shows no changes to `lib/api.ts`, `lib/types.ts`, `app/api/**`, `middleware.ts`, `components/ResumeUpload.tsx`; in `Settings.tsx` the `BillingCard` function and pre-existing import lines are byte-identical.
- [ ] `package.json` gains exactly one dependency: `motion`.
- [ ] `grep -rn "<select" app components` returns nothing. `grep -rn "motion/react" app components` matches only `components/fx/`.
- [ ] `node dev/screenshots.mjs <out>` completes with 0 console/page problems and produces all 44 files (every optional step in the script still finds its control).
- [ ] `next build` First Load JS: no route grows by more than 15 kB except `/tailor/[id]` (may grow up to 45 kB for `motion`).

Flows (against the mock; start it with `MOCK_NEW_USER=1` for the first two: it returns 428 `consent_required` on workflow creation until consent is posted)
- [ ] New user picks "Decide later" → uploads a resume → pastes a job → Start → consent dialog appears → agree → lands on `/tailor/{id}` with no retyping.
- [ ] No link anywhere sends a consent-less user from the tailoring form to `/onboarding`.
- [ ] Dashboard: a running row's details show only "in progress" and "View progress"; no "0 changes", no disabled buttons. When the run completes the row updates without a reload and without a skeleton flash.
- [ ] Review: selecting the already-selected decision does nothing; "Undo" returns to "To review"; "Use all remaining rewrites" decides every pending change.
- [ ] Diff: the Lumen Bank demo changes show phrase-level highlights; the reordered skills list shows no highlights and the "Mostly rewritten or reordered" caption.
- [ ] Tailor form: pasting a URL shows "Link detected"; pasting text shows the character count; an unreadable URL clears the field, shows the warning, and focuses the field.
- [ ] `/tailor/{id}#iterate` from the dashboard scrolls to the rewrite block.
- [ ] Applications add/edit still saves status and resume version (hidden inputs present in FormData).
- [ ] Settings preferences save the same field values as before.

Accessibility
- [ ] Every screen is fully operable with keyboard only; focus ring always visible; no focus trap outside dialogs.
- [ ] `Select`: all keys in section 2.2 work; works inside a `Dialog` (popup not clipped, `Escape` closes only the popup); announced as combobox with its label and value (check with a screen reader or the accessibility tree).
- [ ] Segmented controls and choice cards are radio groups with a group name; arrow keys move selection.
- [ ] Text contrast at least 4.5:1 (3:1 for 24px+ and for input borders/icons). No `text-ink-faint` on `surface-sunken`. axe (or Lighthouse accessibility) reports 0 serious/critical issues on each of the 12 screens.
- [ ] With `prefers-reduced-motion: reduce`: aurora static, no shine, numbers show final values immediately, dialogs/toasts appear without movement.
- [ ] Dialog titles have unique ids when two dialogs are mounted.

Layout
- [ ] At 390px: no horizontal scroll on any screen; Resumes and Applications rows are stacked with readable text (no one-word-per-line columns); dashboard titles wrap to two lines; bottom tab bar does not cover page actions or toasts.
- [ ] At 1440px: no Card contains another bordered box (search the DOM for nested `ring-1`/`border` containers inside cards: only inputs, badges and buttons allowed).
- [ ] No `components/fx/*` import in dashboard, resumes, applications or settings files.

Licence
- [ ] Each file in `components/fx/` has the source/origin header. The repo is a product, not a template/kit, so Aceternity's and React Bits' terms are met; do not publish `components/fx/` as a standalone package.
