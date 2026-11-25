"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CheckCircle2, Lock } from "lucide-react";
import { api } from "@/lib/api";
import { useResource, useResumeProcessing } from "@/lib/hooks";
import { processingMessage } from "@/lib/processing";
import { cx, formatDate } from "@/lib/format";
import type { ExtractionFinding, ResumeDetail } from "@/lib/types";
import { Alert, Badge, Button, ButtonLink, Card, CardBody, CardHeader, PageHeader, Select, Skeleton, SkeletonRows } from "@/components/ui";
import { ReadingScan, UnreadableScan } from "@/components/ScanStatus";
import { VersionList } from "../VersionList";

function findingTone(f: ExtractionFinding): "info" | "warning" | "error" {
  if (f.severity === "error") return "error";
  if (f.severity === "info") return "info";
  return "warning";
}

/** A resume that is still being read from a scanned PDF, or could not be read. Replaces the page body until it is ready. */
function ScanDetail({ resume, onReady }: { resume: ResumeDetail & { processing: NonNullable<ResumeDetail["processing"]> }; onReady: (d: ResumeDetail) => void }) {
  const router = useRouter();
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const { processing, startedAt, retrying, retry, problem, gone } = useResumeProcessing(resume.id, resume.processing, onReady);

  async function remove() {
    setRemoving(true);
    setRemoveError(null);
    try {
      await api.archiveResume(resume.id);
      router.push("/resumes");
    } catch (e) {
      setRemoveError(e instanceof Error ? e.message : "Couldn't remove this resume.");
      setRemoving(false);
    }
  }

  return (
    <>
      <PageHeader back={{ href: "/resumes", label: "Resumes" }} title={resume.name} description="This PDF is a scan, so we read its text from the page images." />
      <div className="max-w-2xl">
        {gone ? (
          <Alert tone="warning">This resume was removed.</Alert>
        ) : processing.status === "processing" ? (
          <ReadingScan
            startedAt={startedAt}
            leaveHint="You can leave this page. We'll keep going and it will appear in your resumes when it's ready."
          />
        ) : (
          <UnreadableScan message={processingMessage(processing)} problem={problem ?? removeError} onRetry={() => void retry()} retrying={retrying}>
            <Button variant="secondary" onClick={() => void remove()} loading={removing}>
              Remove this resume
            </Button>
          </UnreadableScan>
        )}
      </div>
    </>
  );
}

export function ResumeDetailView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const resume = useResource(() => api.resume(id), [id]);
  const [versionId, setVersionId] = useState<string | null>(search.get("version"));

  const versions = resume.data ? [...resume.data.versions].sort((a, b) => b.version_number - a.version_number) : [];
  const latestId = versions[0]?.id;
  useEffect(() => {
    if (!versionId && latestId) setVersionId(latestId);
  }, [versionId, latestId]);

  const version = useResource(() => (versionId ? api.version(id, versionId) : Promise.resolve(undefined)), [id, versionId]);

  if (resume.loading) return <SkeletonRows rows={6} />;
  if (resume.error || !resume.data) return <Alert tone="error">{resume.error?.message ?? "Resume not found."}</Alert>;

  if (resume.data.processing) {
    return <ScanDetail resume={{ ...resume.data, processing: resume.data.processing }} onReady={(d) => resume.setData(d)} />;
  }

  const v = version.data;
  const textBlocks = v?.blocks.filter((b) => b.text.trim()) ?? [];

  return (
    <>
      <PageHeader
        back={{ href: "/resumes", label: "Resumes" }}
        title={resume.data.name}
        description="This is what we read from your file. Tailoring only ever uses this text."
        actions={versionId ? <ButtonLink href={`/tailor/new?version=${versionId}`}>Tailor this version</ButtonLink> : undefined}
      />
      <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
        <Card as="section">
          <CardHeader
            title="Extracted content"
            description={v ? `${textBlocks.length} text blocks` : undefined}
            action={
              versions.length > 1 ? (
                <Select
                  size="sm"
                  aria-label="Version"
                  value={versionId ?? ""}
                  onChange={(vid) => {
                    setVersionId(vid);
                    router.replace(`/resumes/${id}?version=${vid}`);
                  }}
                  options={versions.map((x) => ({ value: x.id, label: `v${x.version_number} · ${formatDate(x.created_at)}` }))}
                  className="w-44"
                />
              ) : undefined
            }
          />
          <CardBody>
            {version.loading && (
              <div className="space-y-2">
                {Array.from({ length: 8 }, (_, i) => (
                  <Skeleton key={i} className="h-5 w-full" />
                ))}
              </div>
            )}
            {version.error && <Alert tone="error">{version.error.message}</Alert>}
            {v && (
              <ol>
                {textBlocks.map((b) => (
                  <li
                    key={b.id}
                    title={`Block ${b.id}`}
                    className={cx(
                      "flex gap-3 py-1",
                      b.is_heading ? "mt-5 text-base font-semibold text-ink first:mt-0" : "text-base leading-relaxed text-ink",
                      b.is_list_item && "pl-5",
                    )}
                  >
                    <span className="sr-only">Block {b.id}: </span>
                    <span className="min-w-0 flex-1 break-words">
                      {b.is_list_item && <span aria-hidden>• </span>}
                      {b.text}
                    </span>
                    {b.editable === false && (
                      <span title="Contains links or special formatting; kept exactly as is." className="mt-1 text-ink-faint">
                        <Lock className="h-3.5 w-3.5" aria-label="Locked block" />
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </CardBody>
        </Card>

        <div className="order-first space-y-6 lg:order-none">
          <Card as="section">
            <CardHeader title="Things to check" />
            <CardBody className="space-y-3">
              {v && v.findings.length === 0 && (
                <p className="flex items-center gap-2 text-sm text-emerald-700">
                  <CheckCircle2 className="h-4 w-4" aria-hidden /> Everything looks readable.
                </p>
              )}
              {v?.findings.map((f, i) => {
                const near = f.block_id ? v.blocks.find((x) => x.id === f.block_id)?.text : undefined;
                const title = f.code.replace(/_/g, " ");
                return (
                  <Alert key={i} tone={findingTone(f)} title={title.charAt(0).toUpperCase() + title.slice(1)}>
                    {f.detail}
                    {near && <span className="mt-1 block text-xs opacity-80">Near: “{near.slice(0, 40)}{near.length > 40 ? "…" : ""}”</span>}
                  </Alert>
                );
              })}
              {v && (
                <p className="text-xs text-ink-muted">
                  If something is missing or wrong, fix it in your original file and upload it again, or rebuild it with the{" "}
                  <Link href="/resumes/new" className="underline">
                    guided editor
                  </Link>
                  .
                </p>
              )}
            </CardBody>
          </Card>
          <Card as="section">
            <CardHeader title="Versions" />
            <CardBody>
              <VersionList resumeId={id} onRestored={() => void resume.reload()} />
            </CardBody>
          </Card>
          {resume.data.origin && (
            <p className="text-xs text-ink-muted">
              <Badge>{v?.source_format === "text" ? "Pasted" : resume.data.origin === "upload" ? "Uploaded" : "Built here"}</Badge> Added {formatDate(resume.data.created_at)}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
