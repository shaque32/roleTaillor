"use client";

import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { Card, CardBody, PageHeader, Skeleton } from "@/components/ui";
import { TailorForm } from "@/components/TailorForm";

export function NewTailoring() {
  const params = useSearchParams();
  const me = useResource(() => api.me());
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="New tailoring" description="Pick a resume, add the job, and we'll prepare a tailored version for your review." />
      <Card>
        <CardBody className="py-6">
          {me.loading ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <TailorForm initialVersionId={params.get("version") || undefined} defaultPageLimit={me.data?.preferred_page_limit ?? 2} />
          )}
        </CardBody>
      </Card>
    </div>
  );
}
