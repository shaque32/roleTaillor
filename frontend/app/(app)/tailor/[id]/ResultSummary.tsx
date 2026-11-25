"use client";

import { useState } from "react";
import { ArrowRight, Check, CheckCircle2, Link2 } from "lucide-react";
import { api, exportAndOpen } from "@/lib/api";
import { formatScore } from "@/lib/format";
import type { ExportKind, GeneratedResume, Scores } from "@/lib/types";
import { Badge, Button, Card, CardBody, Dialog, Disclosure, Input, ScoreBar, useToast } from "@/components/ui";
import { CountUp } from "@/components/fx/CountUp";

const EXPORTS: { kind: ExportKind; label: string; primary?: boolean }[] = [
  { kind: "docx", label: "Word (.docx)", primary: true },
  { kind: "pdf", label: "PDF" },
  { kind: "ats_report", label: "ATS report" },
];

function Delta({ label, before, after }: { label: string; before?: number | null; after: number | null }) {
  if (after === null || after === undefined) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-sunken px-2.5 py-1 text-xs text-ink-muted">
      {label}
      <span className="font-semibold tabular-nums text-ink">
        {before !== null && before !== undefined && <span className="font-normal text-ink-muted">{formatScore(before)} → </span>}
        {formatScore(after)}
      </span>
    </span>
  );
}

export function ResultSummary({
  generated,
  before,
  onApproved,
}: {
  generated: GeneratedResume;
  before: Scores | null;
  onApproved: (g: GeneratedResume) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function approve() {
    setBusy("approve");
    try {
      onApproved(await api.approve(generated.id));
      toast.success("Marked as final. Your final version is ready to export.");
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  async function download(kind: ExportKind) {
    setBusy(kind);
    try {
      await exportAndOpen(generated.id, kind);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  async function share() {
    setBusy("share");
    try {
      const exp = await api.createExport(generated.id, "pdf");
      const { url } = await api.share(exp.export_id, 72);
      setCopied(false);
      setShareUrl(url);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  async function copy() {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(new Error("Couldn't copy automatically. Select the link and copy it."));
    }
  }

  const ats = generated.ats_score;
  const beforeAts = before?.ats ?? null;
  const delta = ats !== null && beforeAts !== null ? Math.round(ats) - Math.round(beforeAts) : null;

  return (
    <Card>
      <CardBody className="grid items-start gap-6 md:grid-cols-[1fr_auto] md:gap-10">
        <div className="min-w-0">
          <p className="text-sm text-ink-muted">ATS match</p>
          <div
            className="mt-1 flex flex-wrap items-center gap-3"
            role="img"
            aria-label={`ATS match: ${beforeAts !== null ? `before ${formatScore(beforeAts)}, after ` : ""}${formatScore(ats)}`}
          >
            {ats === null ? (
              <span className="text-5xl font-semibold text-ink-muted">—</span>
            ) : (
              <>
                {beforeAts !== null && (
                  <>
                    <span className="text-2xl tabular-nums text-ink-muted" aria-hidden>
                      {Math.round(beforeAts)}
                    </span>
                    <ArrowRight className="h-5 w-5 text-ink-muted" aria-hidden />
                  </>
                )}
                <span aria-hidden>
                  <CountUp from={beforeAts ?? 0} to={Math.round(ats)} className="text-5xl font-semibold" />
                </span>
                {delta !== null && delta > 0 && <Badge tone="green">+{delta}</Badge>}
              </>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Delta label="Job alignment" before={before?.job_alignment} after={generated.job_alignment_score} />
            <Delta label="Keywords" before={before?.keyword_relevance} after={generated.keyword_relevance_score} />
            <Delta label="Formatting" before={before?.formatting} after={generated.formatting_score} />
          </div>
          <Disclosure summary="See score breakdown" className="mt-4">
            <div className="space-y-5">
              <ScoreBar label="ATS compatibility" value={generated.ats_score} before={before?.ats} />
              <ScoreBar label="Job alignment" value={generated.job_alignment_score} before={before?.job_alignment} />
              <ScoreBar label="Keyword relevance" value={generated.keyword_relevance_score} before={before?.keyword_relevance} />
              <ScoreBar label="Formatting" value={generated.formatting_score} before={before?.formatting} />
            </div>
          </Disclosure>
          <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2">
            {generated.approved_at ? (
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-700">
                <CheckCircle2 className="h-4 w-4" aria-hidden /> Marked as final
              </span>
            ) : (
              <>
                <Button variant="soft" size="sm" onClick={approve} loading={busy === "approve"}>
                  Mark as final
                </Button>
                <span className="text-sm text-ink-muted">Locks this version as the one you sent.</span>
              </>
            )}
          </div>
        </div>

        <div className="md:w-52">
          <h2 className="mb-2 text-sm font-medium">Download</h2>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-1">
            {EXPORTS.map((e) => (
              <Button
                key={e.kind}
                variant={e.primary ? "primary" : "secondary"}
                onClick={() => download(e.kind)}
                loading={busy === e.kind}
                className={e.primary ? "col-span-2 md:col-span-1" : undefined}
              >
                {e.label}
              </Button>
            ))}
            <Button variant="ghost" onClick={share} loading={busy === "share"} className="col-span-2 md:col-span-1">
              <Link2 className="h-4 w-4" aria-hidden /> Share link
            </Button>
          </div>
          <p className="mt-2 text-xs text-ink-muted">Includes every rewrite you haven&apos;t turned off.</p>
        </div>
      </CardBody>
      <Dialog
        open={Boolean(shareUrl)}
        onClose={() => setShareUrl(null)}
        title="Share link"
        description="Anyone with this link can view the PDF for 3 days."
        footer={
          <Button variant="secondary" onClick={() => setShareUrl(null)}>
            Done
          </Button>
        }
      >
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input readOnly value={shareUrl ?? ""} aria-label="Share URL" className="min-w-0 flex-1" onFocus={(e) => e.currentTarget.select()} />
          <Button size="lg" onClick={copy} className="shrink-0">
            {copied ? <Check className="h-4 w-4" aria-hidden /> : null}
            {copied ? "Copied" : "Copy link"}
          </Button>
        </div>
        <p className="sr-only" aria-live="polite">
          {copied ? "Link copied" : ""}
        </p>
      </Dialog>
    </Card>
  );
}
