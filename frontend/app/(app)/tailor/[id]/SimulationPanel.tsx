import { AlertTriangle, Lightbulb, ThumbsUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { HiringManagerFeedback } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { Alert, Badge, ScoreBar, Section } from "@/components/ui";

const LIKELIHOOD_TONE = {
  low: "amber",
  moderate: "blue",
  high: "green",
} as const;

function Column({ title, icon: Icon, items }: { title: string; icon: LucideIcon; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <Icon className="h-4 w-4 text-ink-muted" aria-hidden /> {title}
      </h3>
      <ul className="mt-2 divide-y divide-line text-sm text-ink-muted">
        {items.map((x, i) => (
          <li key={i} className="py-2.5 first:pt-0">
            {x}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SimulationPanel({ feedback, score }: { feedback: HiringManagerFeedback | null; score: number | null }) {
  const overall = feedback?.overall ?? score;
  return (
    <Section title="Hiring-manager view">
      <div className="space-y-6">
        <Alert tone="warning">This is an AI simulation, not a prediction of hiring outcomes.</Alert>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-4xl font-semibold tabular-nums" aria-label={`Simulation score ${formatScore(overall)}`}>
            {formatScore(overall)}
          </span>
          {feedback && (
            <Badge tone={LIKELIHOOD_TONE[feedback.interview_likelihood] ?? "neutral"}>
              Simulated interview likelihood: <span className="capitalize">{feedback.interview_likelihood}</span>
            </Badge>
          )}
        </div>
        {!feedback ? (
          <p className="text-sm text-ink-muted">No simulated feedback for this version.</p>
        ) : (
          <>
            <div className="grid gap-5 sm:grid-cols-2">
              <ScoreBar label="Technical alignment" value={feedback.technical_alignment} />
              <ScoreBar label="Leadership" value={feedback.leadership} />
              <ScoreBar label="Domain alignment" value={feedback.domain_alignment} />
              <ScoreBar label="Communication" value={feedback.communication} />
            </div>
            <div className="grid gap-6 md:grid-cols-3">
              <Column title="Strengths" icon={ThumbsUp} items={feedback.strengths} />
              <Column title="Weaknesses" icon={AlertTriangle} items={feedback.weaknesses} />
              <Column title="Suggestions" icon={Lightbulb} items={feedback.suggested_improvements} />
            </div>
            {feedback.competitive_positioning && <p className="text-sm text-ink-muted">{feedback.competitive_positioning}</p>}
          </>
        )}
      </div>
    </Section>
  );
}
