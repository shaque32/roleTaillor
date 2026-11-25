"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import type { ChangeDecision, ResumeChange } from "@/lib/types";
import { Badge, Button, Card, DiffView, SegmentedControl, Section, Textarea, useToast } from "@/components/ui";

type Filter = "all" | ChangeDecision;

export function ChangeReview({
  workflowId,
  generatedId,
  changes,
  busy,
  onChange,
  onIterationStarted,
}: {
  workflowId: string;
  generatedId: string;
  changes: ResumeChange[];
  busy: boolean;
  onChange: (update: (changes: ResumeChange[]) => ResumeChange[]) => void;
  onIterationStarted: () => void;
}) {
  const toast = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<Filter>("all");
  const [saving, setSaving] = useState<string | null>(null);
  const [bulk, setBulk] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [regenBusy, setRegenBusy] = useState(false);

  // Latest props for the bulk loop, which outlives the render it started in.
  const changesRef = useRef(changes);
  const mounted = useRef(true);
  useEffect(() => {
    changesRef.current = changes;
  }, [changes]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const counts = {
    all: changes.length,
    pending: changes.filter((c) => c.decision === "pending").length,
    accepted: changes.filter((c) => c.decision === "accepted").length,
    rejected: changes.filter((c) => c.decision === "rejected").length,
  };
  const reviewed = counts.accepted + counts.rejected;
  const visible = filter === "all" ? changes : changes.filter((c) => c.decision === filter);

  /** Sends exactly `decision`. Returns true when saved (or already in that state). */
  async function decide(c: ResumeChange, decision: ChangeDecision, opts: { quiet?: boolean } = {}): Promise<boolean> {
    if (c.decision === decision) return true;
    const previous = c.decision;
    const setDecision = (d: ChangeDecision, extra?: Partial<ResumeChange>) =>
      onChange((cs) => cs.map((x) => (x.id === c.id ? { ...x, ...extra, decision: d } : x)));
    setDecision(decision);
    setSaving(c.id);
    try {
      const updated = await api.decideChange(generatedId, c.id, decision);
      setDecision(updated?.decision ?? decision, updated ?? undefined);
      return true;
    } catch (e) {
      setDecision(previous);
      if (!opts.quiet) toast.error(e);
      return false;
    } finally {
      setSaving(null);
    }
  }

  async function acceptRemaining() {
    const todo = changes.filter((c) => c.decision === "pending").map((c) => c.id);
    setBulk(true);
    let done = 0;
    let skipped = 0;
    let failed = false;
    try {
      for (const id of todo) {
        if (!mounted.current) return;
        // Re-read the current decision: the user may have changed it since the loop started.
        const current = changesRef.current.find((x) => x.id === id);
        if (!current || current.decision !== "pending") {
          skipped++;
          continue;
        }
        if (await decide(current, "accepted", { quiet: true })) done++;
        else {
          failed = true;
          break;
        }
      }
    } finally {
      if (mounted.current) setBulk(false);
    }
    if (!mounted.current) return;
    if (!failed) toast.success(`Accepted ${done} rewrite${done === 1 ? "" : "s"}.`);
    else toast.error(new Error(`Accepted ${done} of ${todo.length - skipped} rewrites. Something went wrong, please try again.`));
  }

  function toggleSelect(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  async function regenerate() {
    const focus = changes.filter((c) => selected.has(c.id)).map((c) => c.block_path);
    setRegenBusy(true);
    try {
      await api.iterate(workflowId, {
        focus_block_ids: focus.length ? focus : undefined,
        instructions: instructions.trim() || undefined,
      });
      setSelected(new Set());
      setInstructions("");
      toast.info("Rewriting. Re-runs on this job are free.");
      onIterationStarted();
    } catch (e) {
      toast.error(e);
    } finally {
      setRegenBusy(false);
    }
  }

  const locked = busy || bulk;
  const stateBadge = (c: ResumeChange) =>
    selected.has(c.id) ? (
      <Badge tone="brand">Will be rewritten</Badge>
    ) : c.decision === "accepted" ? (
      <Badge tone="green">Using rewrite</Badge>
    ) : c.decision === "rejected" ? (
      <Badge tone="neutral">Keeping original</Badge>
    ) : (
      <Badge tone="neutral">To review</Badge>
    );

  return (
    <Section
      title="Review changes"
      description="Each one is a rewrite of your own words. Every rewrite is included in your download unless you choose Keep original."
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-[10rem]" aria-live="polite">
          <p className="text-sm text-ink-muted">
            {reviewed} of {counts.all} reviewed
          </p>
          <div className="mt-1.5 h-1.5 w-40 max-w-full rounded-full bg-surface-sunken" aria-hidden>
            <div
              className="h-1.5 rounded-full bg-brand-500 transition-[width] duration-300"
              style={{
                width: counts.all ? `${(reviewed / counts.all) * 100}%` : "0%",
              }}
            />
          </div>
        </div>
        <SegmentedControl
          variant="chips"
          size="sm"
          aria-label="Filter changes"
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          options={[
            { value: "all", label: "All", count: counts.all },
            { value: "pending", label: "To review", count: counts.pending },
            {
              value: "accepted",
              label: "Using rewrite",
              count: counts.accepted,
            },
            {
              value: "rejected",
              label: "Keeping original",
              count: counts.rejected,
            },
          ]}
        />
        {counts.pending > 0 && (
          <Button variant="soft" size="sm" className="sm:ml-auto" onClick={acceptRemaining} loading={bulk} disabled={busy}>
            Use all remaining rewrites
          </Button>
        )}
      </div>

      {visible.length === 0 && <p className="py-6 text-center text-sm text-ink-muted">Nothing here. Switch the filter to see other changes.</p>}
      <ul className="space-y-4">
        {visible.map((c) => {
          const n = changes.indexOf(c) + 1;
          const disabled = saving === c.id || locked;
          const pressed = selected.has(c.id);
          return (
            <li key={c.id}>
              <Card variant="flat" className="p-5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-medium">Change {n}</h3>
                  {stateBadge(c)}
                </div>
                <div className={cx(c.decision === "rejected" && "opacity-60")}>
                  <DiffView before={c.prior_text ?? ""} after={c.proposed_text ?? ""} />
                  {(c.reason || c.prioritized_keywords.length > 0) && (
                    <div className="mt-4 space-y-2 text-sm">
                      {c.reason && (
                        <p className="flex items-start gap-2 text-ink-muted">
                          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" aria-hidden />
                          <span>
                            <span className="sr-only">Why: </span>
                            {c.reason}
                          </span>
                        </p>
                      )}
                      {c.prioritized_keywords.length > 0 && (
                        <p className="flex flex-wrap items-center gap-1.5">
                          <span className="sr-only">Prioritised keywords:</span>
                          {c.prioritized_keywords.map((k) => (
                            <Badge key={k} tone="brand">
                              {k}
                            </Badge>
                          ))}
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4">
                  <SegmentedControl
                    size="sm"
                    aria-label={`Decision for change ${n}`}
                    value={c.decision === "pending" ? null : c.decision}
                    onChange={(d) => void decide(c, d)}
                    options={[
                      { value: "accepted", label: "Use rewrite", disabled },
                      { value: "rejected", label: "Keep original", disabled },
                    ]}
                  />
                  {c.decision !== "pending" && (
                    <Button variant="ghost" size="sm" onClick={() => void decide(c, "pending")} disabled={disabled}>
                      Undo
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" className="sm:ml-auto" aria-pressed={pressed} onClick={() => toggleSelect(c.id)}>
                    <RefreshCw className="h-4 w-4" aria-hidden /> {pressed ? "Selected for rewrite" : "Ask for another version"}
                  </Button>
                </div>
              </Card>
            </li>
          );
        })}
      </ul>

      <div id="iterate" className="mt-6 scroll-mt-24">
        <Card variant="sunken" className="p-5">
          <h3 className="text-base font-semibold">Not quite right?</h3>
          <p className="mt-1 text-sm text-ink-muted">
            {selected.size > 0
              ? `We'll rewrite the ${selected.size} change${selected.size === 1 ? "" : "s"} you selected.`
              : "We'll rewrite everything. Or pick specific changes above with “Ask for another version”."}{" "}
            Re-runs on this job are free.
          </p>
          <Textarea
            className="mt-4"
            autoGrow
            rows={2}
            label="Tell us what to change"
            optional
            placeholder="e.g. Shorter. Emphasise stakeholder management."
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
          <Button className="mt-4" variant="secondary" onClick={regenerate} loading={regenBusy} disabled={busy}>
            <RefreshCw className="h-4 w-4" aria-hidden /> {selected.size > 0 ? "Rewrite selected" : "Rewrite everything"}
          </Button>
        </Card>
      </div>

      {selected.size > 0 && (
        <div className="sticky bottom-20 z-30 mt-4 flex items-center gap-2 rounded-xl bg-ink px-4 py-3 text-white shadow-pop md:bottom-4">
          <p className="mr-auto min-w-0 flex-1 truncate text-sm" aria-live="polite">
            {selected.size} selected
            <span className="max-sm:sr-only"> for rewrite</span>
          </p>
          <Button size="sm" variant="secondary" onClick={regenerate} loading={regenBusy} disabled={busy}>
            Rewrite selected
          </Button>
          <Button size="sm" variant="ghost" className="!text-white/80 hover:!bg-white/10 hover:!text-white" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}
    </Section>
  );
}
