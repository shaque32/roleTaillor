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
      <PageHeader title="New tailoring" description="Tell us the job. We'll tailor your resume and show you every change." />
      <Card>
        <CardBody className="p-6 sm:p-8">
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
