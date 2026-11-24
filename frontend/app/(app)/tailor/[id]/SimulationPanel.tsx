import { FlaskConical } from "lucide-react";
import type { HiringManagerFeedback } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { Badge, Card, CardBody, CardHeader, ScoreBar } from "@/components/ui";

const LIKELIHOOD_TONE = { low: "amber", moderate: "blue", high: "green" } as const;

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-ink-muted">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

export function SimulationPanel({ feedback, score }: { feedback: HiringManagerFeedback | null; score: number | null }) {
  return (
    <Card as="section" className="border-dashed">
      <CardHeader
        title="Hiring-manager simulation"
        description={
          <span className="inline-flex items-center gap-1.5 font-medium text-amber-800">
            <FlaskConical className="h-3.5 w-3.5" aria-hidden />
            AI simulation, not a prediction of hiring outcomes
          </span>
        }
        action={
          <span className="text-2xl font-semibold tabular-nums" aria-label={`Simulation score ${formatScore(feedback?.overall ?? score)}`}>
            {formatScore(feedback?.overall ?? score)}
          </span>
        }
      />
      <CardBody className="space-y-5">
        {!feedback ? (
          <p className="text-sm text-ink-muted">No simulated feedback for this iteration.</p>
        ) : (
          <>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-ink-muted">Simulated interview likelihood:</span>
              <Badge tone={LIKELIHOOD_TONE[feedback.interview_likelihood] ?? "neutral"}>{feedback.interview_likelihood}</Badge>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <ScoreBar label="Technical alignment" value={feedback.technical_alignment} />
              <ScoreBar label="Leadership" value={feedback.leadership} />
              <ScoreBar label="Domain alignment" value={feedback.domain_alignment} />
              <ScoreBar label="Communication" value={feedback.communication} />
            </div>
            <details className="group" open>
              <summary className="cursor-pointer text-sm font-medium text-brand-600">Strengths, weaknesses and suggestions</summary>
              <div className="mt-4 space-y-4">
                <List title="Strengths" items={feedback.strengths} />
                <List title="Weaknesses" items={feedback.weaknesses} />
                <List title="Suggestions" items={feedback.suggested_improvements} />
                {feedback.competitive_positioning && <p className="text-sm text-ink-muted">{feedback.competitive_positioning}</p>}
              </div>
            </details>
          </>
        )}
      </CardBody>
    </Card>
  );
}
