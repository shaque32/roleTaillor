import type { GeneratedResume, Scores } from "@/lib/types";
import { Card, CardBody, CardHeader, ScoreBar, ScoreRing } from "@/components/ui";

export function ScoresPanel({ before, latest }: { before: Scores | null; latest: GeneratedResume }) {
  return (
    <Card as="section">
      <CardHeader title="Resume scores" description={before ? "Before → after tailoring. The tick marks your original score." : undefined} />
      <CardBody className="space-y-5">
        <div className="flex justify-center gap-8">
          {before && <ScoreRing value={before.ats} label="ATS before" size={76} />}
          <ScoreRing value={latest.ats_score} label="ATS after" />
        </div>
        <ScoreBar label="ATS compatibility" value={latest.ats_score} before={before?.ats} />
        <ScoreBar label="Job alignment" value={latest.job_alignment_score} before={before?.job_alignment} />
        <ScoreBar label="Keyword relevance" value={latest.keyword_relevance_score} before={before?.keyword_relevance} />
        <ScoreBar label="Formatting" value={latest.formatting_score} before={before?.formatting} />
      </CardBody>
    </Card>
  );
}
