import type { Gap } from "@/lib/types";
import { gapTerm } from "@/lib/format";
import { Alert, Badge, ButtonLink, Section } from "@/components/ui";

export function GapsPanel({ gaps }: { gaps: Gap[] }) {
  return (
    <Section title="Missing keywords" description="The job asks for these, but your resume doesn't show them. We did not add them.">
      {gaps.length === 0 ? (
        <Alert tone="success">No gaps: your resume evidences every key requirement we found.</Alert>
      ) : (
        <div className="space-y-4">
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
          <Alert
            tone="info"
            action={
              <ButtonLink size="sm" variant="secondary" href="/resumes">
                Update my resume
              </ButtonLink>
            }
          >
            If you genuinely have this experience, add it to your source resume and start a new tailoring so it can be evidenced.
          </Alert>
        </div>
      )}
    </Section>
  );
}
