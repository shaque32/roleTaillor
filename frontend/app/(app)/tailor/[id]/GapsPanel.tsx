import { ShieldCheck } from "lucide-react";
import type { Gap } from "@/lib/types";
import { gapTerm } from "@/lib/format";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui";

export function GapsPanel({ gaps }: { gaps: Gap[] }) {
  return (
    <Card as="section">
      <CardHeader
        title="Keyword gaps"
        description="The job asks for these, but your resume doesn't show evidence of them. We deliberately did not add them."
      />
      <CardBody>
        {gaps.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-emerald-700">
            <ShieldCheck className="h-4 w-4" aria-hidden /> No gaps: your resume evidences every key requirement we found.
          </p>
        ) : (
          <>
            <ul className="flex flex-wrap gap-2">
              {gaps.map((g) => {
                const imp = typeof g === "string" ? undefined : g.importance;
                return (
                  <li key={gapTerm(g)}>
                    <Badge tone={imp === "must" ? "red" : "amber"}>
                      {gapTerm(g)}
                      {imp === "must" && <span className="ml-1 opacity-75">· required</span>}
                    </Badge>
                  </li>
                );
              })}
            </ul>
            <p className="mt-4 text-sm text-ink-muted">
              If you genuinely have this experience, add it to your source resume and start a new tailoring so it can be evidenced.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
