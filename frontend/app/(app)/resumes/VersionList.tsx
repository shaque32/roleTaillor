"use client";

import Link from "next/link";
import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import { Button, Skeleton, useToast } from "@/components/ui";

export function VersionList({ resumeId, onRestored }: { resumeId: string; onRestored?: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useResource(() => api.resume(resumeId), [resumeId]);
  const [busy, setBusy] = useState<string | null>(null);

  async function restore(vid: string) {
    setBusy(vid);
    try {
      const v = await api.restoreVersion(resumeId, vid);
      toast.success(`Restored as v${v.version_number}.`);
      await reload();
      onRestored?.();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Skeleton className="h-16 w-full" />;
  if (error || !data) return <p className="text-sm text-red-700">{error?.message}</p>;
  const versions = [...data.versions].sort((a, b) => b.version_number - a.version_number);

  return (
    <ul className="divide-y divide-slate-100 rounded-md border border-slate-100 bg-slate-50/60 text-sm">
      {versions.map((v, i) => (
        <li key={v.id} className="flex items-center gap-3 px-4 py-2.5">
          <span className="w-10 font-medium tabular-nums">v{v.version_number}</span>
          <span className="flex-1 text-ink-muted">
            {formatDate(v.created_at, { dateStyle: "medium", timeStyle: "short" })}
            {i === 0 && " · current"}
          </span>
          <Link href={`/resumes/${resumeId}?version=${v.id}`} className="text-brand-600 hover:underline">
            View
          </Link>
          {i > 0 && (
            <Button size="sm" variant="ghost" onClick={() => restore(v.id)} loading={busy === v.id}>
              <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Restore
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
