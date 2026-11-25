"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Archive, FilePlus2, FileText, History, Pencil, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { usePoll, useResource } from "@/lib/hooks";
import { isReading, isUnavailable, isUnreadable, processingMessage, startedAtMs } from "@/lib/processing";
import { cx, formatDate } from "@/lib/format";
import type { ResumeListItem } from "@/lib/types";
import { Alert, Badge, Button, ButtonLink, Card, Dialog, EmptyState, IconButton, Input, PageHeader, SkeletonRows, focusRing, useToast } from "@/components/ui";
import { ResumeUpload } from "@/components/ResumeUpload";
import { ReadingBadge, UnreadableBadge } from "@/components/ScanStatus";
import { VersionList } from "./VersionList";

export function Resumes() {
  const router = useRouter();
  const toast = useToast();
  const { data, error, loading, reload, setData } = useResource(() => api.resumes());
  const [uploadOpen, setUploadOpen] = useState(false);
  const [renaming, setRenaming] = useState<ResumeListItem | null>(null);
  const [archiving, setArchiving] = useState<ResumeListItem | null>(null);
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);

  // Rows being read from a scan flip to ready on their own. setData (not reload) so the list never flashes a skeleton.
  const reading = data?.filter(isReading) ?? [];
  const pollFrom = reading.reduce((t, r) => Math.min(t, startedAtMs(r.processing)), Date.now());
  usePoll(
    async () => {
      setData(await api.resumes());
      return true;
    },
    reading.length > 0,
    pollFrom,
  );

  async function retryScan(r: ResumeListItem) {
    setRetrying(r.id);
    try {
      const d = await api.retryResumeProcessing(r.id);
      setData((xs) => xs?.map((x) => (x.id === r.id ? { ...x, processing: d.processing } : x)));
    } catch (err) {
      toast.error(err);
      void reload();
    } finally {
      setRetrying(null);
    }
  }

  async function rename(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!renaming) return;
    const name = String(new FormData(e.currentTarget).get("name") ?? "").trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.renameResume(renaming.id, name);
      setData((xs) => xs?.map((r) => (r.id === renaming.id ? { ...r, name } : r)));
      setRenaming(null);
      toast.success("Resume renamed.");
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!archiving) return;
    setBusy(true);
    try {
      await api.archiveResume(archiving.id);
      setData((xs) => xs?.filter((r) => r.id !== archiving.id));
      setArchiving(null);
      toast.success("Resume archived.");
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Resumes"
        description="Your source resumes. Tailored versions are created from these."
        actions={
          <>
            <Button onClick={() => setUploadOpen(true)}>
              <Upload className="h-4 w-4" aria-hidden /> Upload
            </Button>
            <ButtonLink href="/resumes/new" variant="secondary">
              <FilePlus2 className="h-4 w-4" aria-hidden /> Build from scratch
            </ButtonLink>
          </>
        }
      />
      {loading && !data && <SkeletonRows rows={4} />}
      {error && <Alert tone="error">{error.message}</Alert>}
      {data && data.length === 0 && (
        <EmptyState
          icon={FileText}
          title="No resumes yet"
          description="Upload a DOCX or PDF, or build one with our guided editor."
          action={<Button onClick={() => setUploadOpen(true)}>Upload a resume</Button>}
          secondaryAction={
            <ButtonLink href="/resumes/new" variant="secondary">
              Build from scratch
            </ButtonLink>
          }
        />
      )}
      {data && data.length > 0 && (
        <ul className="space-y-3">
          {data.map((r) => (
            <li key={r.id}>
              <Card>
                <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:p-5">
                  <div className="flex min-w-0 flex-1 items-center gap-4">
                    <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600" aria-hidden>
                      <FileText className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <Link href={`/resumes/${r.id}`} className={cx("break-words rounded text-base font-medium hover:underline", focusRing)}>
                        {r.name}
                      </Link>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
                        <Badge>{r.origin === "upload" ? "Uploaded" : "Built here"}</Badge>
                        {isReading(r) && <ReadingBadge />}
                        {isUnreadable(r) && <UnreadableBadge />}
                        {r.latest_version && <span>v{r.latest_version.version_number}</span>}
                        <span>Added {formatDate(r.created_at)}</span>
                      </p>
                      {isReading(r) && <p className="mt-1.5 text-sm text-ink-muted">Scanned PDF. This usually takes under a minute, and you can leave this page.</p>}
                      {isUnreadable(r) && <p className="mt-1.5 text-sm text-red-700">{processingMessage(r.processing)}</p>}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {isUnreadable(r) && (
                      <Button size="sm" onClick={() => void retryScan(r)} loading={retrying === r.id}>
                        Try again
                      </Button>
                    )}
                    {!isUnavailable(r) && (
                      <>
                        <ButtonLink href={`/tailor/new?version=${r.latest_version?.id ?? ""}`} size="sm">
                          Tailor
                        </ButtonLink>
                        <Button size="sm" variant="ghost" onClick={() => setVersionsFor((v) => (v === r.id ? null : r.id))} aria-expanded={versionsFor === r.id}>
                          <History className="h-4 w-4" aria-hidden /> Versions
                        </Button>
                      </>
                    )}
                    <IconButton size="sm" label={`Rename ${r.name}`} onClick={() => setRenaming(r)}>
                      <Pencil className="h-4 w-4" aria-hidden />
                    </IconButton>
                    <IconButton size="sm" label={`Archive ${r.name}`} onClick={() => setArchiving(r)}>
                      <Archive className="h-4 w-4" aria-hidden />
                    </IconButton>
                  </div>
                </div>
                {versionsFor === r.id && !isUnavailable(r) && (
                  <div className="border-t border-line px-4 py-2 sm:px-5">
                    <VersionList resumeId={r.id} onRestored={() => void reload()} />
                  </div>
                )}
              </Card>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={uploadOpen} onClose={() => setUploadOpen(false)} title="Upload a resume" size="lg">
        <ResumeUpload
          onScanStarted={() => void reload()}
          onUploaded={({ resume }) => {
            setUploadOpen(false);
            toast.success("Resume uploaded. Check what we extracted.");
            router.push(`/resumes/${resume.id}`);
          }}
        />
      </Dialog>

      <Dialog open={Boolean(renaming)} onClose={() => setRenaming(null)} title="Rename resume" size="sm">
        <form onSubmit={rename} className="space-y-6">
          <Input name="name" label="Name" defaultValue={renaming?.name} required autoFocus />
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={Boolean(archiving)}
        onClose={() => setArchiving(null)}
        size="sm"
        title="Archive this resume?"
        description={`“${archiving?.name ?? ""}” will be hidden from your list. Tailored resumes made from it stay available.`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setArchiving(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={archive} loading={busy}>
              Archive
            </Button>
          </>
        }
      />
    </>
  );
}
