"use client";

import { useState } from "react";
import { Check, RefreshCw, X } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import type { ChangeDecision, ResumeChange } from "@/lib/types";
import { Badge, Button, Card, CardBody, CardHeader, DiffView, Textarea, useToast } from "@/components/ui";

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
  const [instructions, setInstructions] = useState("");
  const [regenBusy, setRegenBusy] = useState(false);

  const counts = {
    all: changes.length,
    pending: changes.filter((c) => c.decision === "pending").length,
    accepted: changes.filter((c) => c.decision === "accepted").length,
    rejected: changes.filter((c) => c.decision === "rejected").length,
  };
  const visible = filter === "all" ? changes : changes.filter((c) => c.decision === filter);

  async function decide(c: ResumeChange, decision: ChangeDecision) {
    const next = c.decision === decision ? "pending" : decision;
    const previous = c.decision;
    const setDecision = (d: ChangeDecision, extra?: Partial<ResumeChange>) =>
      onChange((cs) => cs.map((x) => (x.id === c.id ? { ...x, ...extra, decision: d } : x)));
    setDecision(next);
    setSaving(c.id);
    try {
      const updated = await api.decideChange(generatedId, c.id, next);
      setDecision(updated?.decision ?? next, updated ?? undefined);
    } catch (e) {
      setDecision(previous);
      toast.error(e);
    } finally {
      setSaving(null);
    }
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
      await api.iterate(workflowId, { focus_block_ids: focus.length ? focus : undefined, instructions: instructions.trim() || undefined });
      setSelected(new Set());
      setInstructions("");
      toast.info("Regenerating. This iteration uses no credits.");
      onIterationStarted();
    } catch (e) {
      toast.error(e);
    } finally {
      setRegenBusy(false);
    }
  }

  return (
    <Card as="section">
      <CardHeader
        title="Review changes"
        description="Every change is a rewrite of your own text. Anything you don't reject is included in exports."
        action={
          <div role="group" aria-label="Filter changes" className="flex flex-wrap gap-1 text-sm">
            {(["all", "pending", "accepted", "rejected"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                aria-pressed={filter === f}
                className={cx("rounded-md px-2.5 py-1 capitalize", filter === f ? "bg-slate-100 font-medium text-ink" : "text-ink-muted hover:text-ink")}
              >
                {f} <span className="tabular-nums text-ink-faint">{counts[f]}</span>
              </button>
            ))}
          </div>
        }
      />
      <CardBody className="space-y-4">
        {visible.length === 0 && <p className="py-6 text-center text-sm text-ink-muted">No changes in this view.</p>}
        <ul className="space-y-4">
          {visible.map((c) => (
            <li
              key={c.id}
              className={cx(
                "rounded-lg border p-4",
                c.decision === "accepted" ? "border-emerald-200" : c.decision === "rejected" ? "border-slate-200 opacity-70" : "border-slate-200",
              )}
            >
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggleSelect(c.id)} className="h-4 w-4 rounded border-slate-300 text-brand-600" />
                  <span className="sr-only">Select for regeneration</span>
                  <span className="font-mono text-xs text-ink-faint">{c.block_path}</span>
                </label>
                {c.decision !== "pending" && <Badge tone={c.decision === "accepted" ? "green" : "neutral"}>{c.decision}</Badge>}
                <div className="ml-auto flex gap-1" role="group" aria-label="Decision">
                  <Button
                    size="sm"
                    variant={c.decision === "accepted" ? "primary" : "secondary"}
                    aria-pressed={c.decision === "accepted"}
                    disabled={saving === c.id}
                    onClick={() => decide(c, "accepted")}
                  >
                    <Check className="h-4 w-4" aria-hidden /> Accept
                  </Button>
                  <Button
                    size="sm"
                    variant={c.decision === "rejected" ? "danger" : "secondary"}
                    aria-pressed={c.decision === "rejected"}
                    disabled={saving === c.id}
                    onClick={() => decide(c, "rejected")}
                  >
                    <X className="h-4 w-4" aria-hidden /> Reject
                  </Button>
                </div>
              </div>
              <DiffView before={c.prior_text ?? ""} after={c.proposed_text ?? ""} />
              {(c.reason || c.prioritized_keywords.length > 0) && (
                <div className="mt-3 space-y-2 text-sm">
                  {c.reason && (
                    <p className="text-ink-muted">
                      <span className="font-medium text-ink">Why: </span>
                      {c.reason}
                    </p>
                  )}
                  {c.prioritized_keywords.length > 0 && (
                    <p className="flex flex-wrap items-center gap-1.5">
                      <span className="text-xs text-ink-muted">Prioritized keywords:</span>
                      {c.prioritized_keywords.map((k) => (
                        <Badge key={k} tone="blue">
                          {k}
                        </Badge>
                      ))}
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>

        <div id="iterate" className="scroll-mt-20 rounded-lg bg-slate-50 p-4">
          <h3 className="text-sm font-semibold">Regenerate</h3>
          <p className="mt-0.5 text-sm text-ink-muted">
            {selected.size > 0
              ? `Regenerate ${selected.size} selected change${selected.size === 1 ? "" : "s"}.`
              : "Select changes above to focus on them, or regenerate everything."}{" "}
            Iterations on this job use no credits.
          </p>
          <Textarea
            className="mt-3"
            rows={2}
            label="Instructions (optional)"
            placeholder="e.g. Keep it more concise, emphasise stakeholder management."
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
          <Button className="mt-3" variant="secondary" onClick={regenerate} loading={regenBusy} disabled={busy}>
            <RefreshCw className="h-4 w-4" aria-hidden /> {selected.size > 0 ? "Regenerate selected" : "Regenerate all"}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
