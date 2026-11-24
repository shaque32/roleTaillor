"use client";

import { useState } from "react";
import { CheckCircle2, Download, Link2 } from "lucide-react";
import { api, exportAndOpen } from "@/lib/api";
import type { ExportKind, GeneratedResume } from "@/lib/types";
import { Button, Card, CardBody, Dialog, Input, useToast } from "@/components/ui";

const EXPORTS: { kind: ExportKind; label: string }[] = [
  { kind: "docx", label: "DOCX" },
  { kind: "pdf", label: "PDF" },
  { kind: "ats_report", label: "ATS report" },
];

export function ExportBar({ generated, onApproved }: { generated: GeneratedResume; onApproved: (g: GeneratedResume) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  async function approve() {
    setBusy("approve");
    try {
      onApproved(await api.approve(generated.id));
      toast.success("Approved. Your final version is ready to export.");
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
      setShareUrl(url);
      try {
        await navigator.clipboard.writeText(url);
        toast.success("Share link copied. It expires in 3 days.");
      } catch {
        /* clipboard may be blocked; link is shown in the dialog */
      }
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardBody className="flex flex-wrap items-center gap-3">
        {generated.approved_at ? (
          <span className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-700">
            <CheckCircle2 className="h-4 w-4" aria-hidden /> Approved
          </span>
        ) : (
          <Button onClick={approve} loading={busy === "approve"}>
            Approve
          </Button>
        )}
        <span className="hidden h-6 w-px bg-slate-200 sm:block" aria-hidden />
        {EXPORTS.map((e) => (
          <Button key={e.kind} size="sm" variant="secondary" onClick={() => download(e.kind)} loading={busy === e.kind}>
            <Download className="h-4 w-4" aria-hidden /> {e.label}
          </Button>
        ))}
        <Button size="sm" variant="ghost" onClick={share} loading={busy === "share"}>
          <Link2 className="h-4 w-4" aria-hidden /> Share link
        </Button>
        <p className="w-full text-xs text-ink-muted sm:ml-auto sm:w-auto">Exports include every change you haven&apos;t rejected.</p>
      </CardBody>
      <Dialog open={Boolean(shareUrl)} onClose={() => setShareUrl(null)} title="Share link" description="Anyone with this link can view the PDF for 3 days.">
        <Input readOnly value={shareUrl ?? ""} aria-label="Share URL" onFocus={(e) => e.currentTarget.select()} />
        <div className="mt-4 flex justify-end">
          <Button variant="secondary" onClick={() => setShareUrl(null)}>
            Done
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}
