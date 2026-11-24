"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Archive, FilePlus2, FileText, History, Pencil, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import type { ResumeListItem } from "@/lib/types";
import { Alert, Badge, Button, ButtonLink, Dialog, EmptyState, Input, PageHeader, SkeletonRows, useToast } from "@/components/ui";
import { ResumeUpload } from "@/components/ResumeUpload";
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
            <ButtonLink href="/resumes/new" variant="secondary">
              <FilePlus2 className="h-4 w-4" aria-hidden /> Build from scratch
            </ButtonLink>
            <Button onClick={() => setUploadOpen(true)}>
              <Upload className="h-4 w-4" aria-hidden /> Upload
            </Button>
          </>
        }
      />
      {loading && <SkeletonRows />}
      {error && <Alert tone="error">{error.message}</Alert>}
      {data && data.length === 0 && (
        <EmptyState
          icon={FileText}
          title="No resumes yet"
          description="Upload a DOCX or PDF, or build one with our guided editor."
          action={<Button onClick={() => setUploadOpen(true)}>Upload a resume</Button>}
        />
      )}
      {data && data.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
          {data.map((r) => (
            <li key={r.id} className="px-5 py-4">
              <div className="flex flex-wrap items-center gap-4">
                <div className="min-w-0 flex-1">
                  <Link href={`/resumes/${r.id}`} className="font-medium hover:underline">
                    {r.name}
                  </Link>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
                    <Badge>{r.origin === "upload" ? "Uploaded" : "Built here"}</Badge>
                    {r.latest_version && <span>v{r.latest_version.version_number}</span>}
                    <span>Added {formatDate(r.created_at)}</span>
                  </p>
                </div>
                <div className="flex flex-wrap gap-1">
                  <ButtonLink href={`/tailor/new?version=${r.latest_version?.id ?? ""}`} size="sm" variant="secondary">
                    Tailor
                  </ButtonLink>
                  <Button size="sm" variant="ghost" onClick={() => setVersionsFor((v) => (v === r.id ? null : r.id))} aria-expanded={versionsFor === r.id}>
                    <History className="h-4 w-4" aria-hidden /> Versions
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setRenaming(r)} aria-label={`Rename ${r.name}`}>
                    <Pencil className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setArchiving(r)} aria-label={`Archive ${r.name}`}>
                    <Archive className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              </div>
              {versionsFor === r.id && (
                <div className="mt-4">
                  <VersionList resumeId={r.id} onRestored={() => void reload()} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <Dialog open={uploadOpen} onClose={() => setUploadOpen(false)} title="Upload a resume">
        <ResumeUpload
          onUploaded={({ resume }) => {
            setUploadOpen(false);
            toast.success("Resume uploaded. Check what we extracted.");
            router.push(`/resumes/${resume.id}`);
          }}
        />
      </Dialog>

      <Dialog open={Boolean(renaming)} onClose={() => setRenaming(null)} title="Rename resume">
        <form onSubmit={rename} className="space-y-4">
          <Input name="name" label="Name" defaultValue={renaming?.name} required autoFocus />
          <div className="flex justify-end gap-2">
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
        title="Archive this resume?"
        description={`“${archiving?.name ?? ""}” will be hidden from your list. Tailored resumes made from it stay available.`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setArchiving(null)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={archive} loading={busy}>
            Archive
          </Button>
        </div>
      </Dialog>
    </>
  );
}
