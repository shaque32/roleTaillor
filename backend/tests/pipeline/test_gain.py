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


def test_job_language_and_moving_any_keyword_forward_are_gains():
    job = JobAnalysis(title="Controller", responsibilities=["Own the monthly close and consolidation"],
                      keywords=[Keyword(term="GAAP"), Keyword(term="audit")])
    assert has_gain("Ran month-end for 4 entities under GAAP.",
                    "Ran the monthly close for 4 entities under GAAP.", job)
    assert has_gain("Built schedules for 4 entities and supported the external audit under GAAP.",
                    "Supported the external audit under GAAP and built schedules for 4 entities.", job)
    assert not has_gain("Ran month-end for 4 entities under GAAP.",
                        "Handled month-end for 4 entities under GAAP.", job)


def test_term_evidence_needs_a_real_quote_and_a_quotable_category():
    from roletailor.domain.models import BlockPlan, TermEvidence
    from roletailor.pipeline.stages import _valid_term_evidence

    job = JobAnalysis(keywords=[Keyword(term="infrastructure as code", category="skill"),
                                Keyword(term="board reporting", category="skill"),
                                Keyword(term="Kubernetes", category="tool"),
                                Keyword(term="CPA", category="certification")])
    texts = {"p1": "Wrote Terraform modules that cut setup from three days to two hours.",
             "p2": "Reported results to the executive committee each quarter."}
    bp = BlockPlan(block_id="p1", term_evidence=[
        TermEvidence(job_term="Infrastructure as Code", resume_quote="Wrote Terraform  modules"),
        TermEvidence(job_term="board reporting", resume_quote="reported to the board"),      # not in resume
        TermEvidence(job_term="board reporting", resume_quote="executive committee"),        # other block
        TermEvidence(job_term="Kubernetes", resume_quote="Terraform modules"),               # tool
        TermEvidence(job_term="CPA", resume_quote="Wrote Terraform modules"),                # credential
        TermEvidence(job_term="agile", resume_quote="Wrote Terraform modules"),              # not a job keyword
    ])
    assert [te.job_term for te in _valid_term_evidence(bp, job, "bullet", texts)] == ["infrastructure as code"]
    # The summary may lean on any line of the resume; the verifier judges the meaning.
    kept = _valid_term_evidence(bp, job, "summary", texts)
    assert [te.job_term for te in kept] == ["infrastructure as code", "board reporting"]


def test_keyword_gate_passes_only_backed_terms():
    from roletailor.domain.models import FactInventory
    from roletailor.pipeline.validation.rules import BlockContext, DocContext, check_block

    job = JobAnalysis(keywords=[Keyword(term="infrastructure as code"), Keyword(term="incident response")])
    doc = DocContext(facts=FactInventory(), job=job)
    orig = "Wrote Terraform modules that cut new-environment setup from three days to two hours."
    new = "Built infrastructure as code with Terraform modules, cutting setup from three days to two hours."
    rules = lambda ctx, text: {v.rule_key for v in check_block(ctx, text, doc)}  # noqa: E731
    assert "facts.keywords" in rules(BlockContext("p1", orig, "bullet"), new)
    assert not rules(BlockContext("p1", orig, "bullet", supported_terms=["infrastructure as code"]), new)
    sneaky = new.replace("cutting setup", "improving incident response and cutting setup")
    assert "facts.keywords" in rules(BlockContext("p1", orig, "bullet",
                                                  supported_terms=["infrastructure as code"]), sneaky)
