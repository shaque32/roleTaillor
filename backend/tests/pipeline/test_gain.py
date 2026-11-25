"""The value gate: edits that only reword or reshuffle are dropped."""

from roletailor.domain.models import JobAnalysis, Keyword
from roletailor.pipeline.stages import _match_ending
from roletailor.pipeline.validation.rules import has_gain

JOB = JobAnalysis(keywords=[Keyword(term="PostgreSQL", synonyms=["Postgres"]),
                            Keyword(term="A/B testing", synonyms=["A/B tests"]),
                            Keyword(term="code review")])


def test_job_term_alignment_is_a_gain():
    assert has_gain("Moved invoices to a Postgres queue.", "Moved invoices to a PostgreSQL queue.", JOB)


def test_leading_with_the_job_keyword_is_a_gain():
    assert has_gain("Practices: testing, documentation, code review",
                    "Practices: code review, testing, documentation", JOB)


def test_cosmetic_rewording_is_not_a_gain():
    assert not has_gain("Migrated 80 reports to BigQuery with side-by-side reconciliation.",
                        "Migrated 80 reports to BigQuery, checked through side-by-side reconciliation.", JOB)
    assert not has_gain("Mentored four engineers and introduced data contracts.",
                        "Mentored four engineers; introduced data contracts.", JOB)


def test_no_keywords_means_no_gate():
    assert has_gain("a", "b", JobAnalysis())


def test_closing_full_stop_follows_the_original():
    assert _match_ending("Built the thing.", "Built the service") == "Built the service."
    assert _match_ending("Python, SQL", "SQL, Python.") == "SQL, Python"
    assert _match_ending("Built it.", "Built it well.") == "Built it well."
