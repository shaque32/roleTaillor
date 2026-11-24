from roletailor.domain.models import FactInventory, JobAnalysis, Keyword
from roletailor.pipeline.text import bare_numbers, contains_term, tech_terms
from roletailor.pipeline.validation.rules import BlockContext, DocContext, check_block

JOB = JobAnalysis(keywords=[
    Keyword(term="machine learning", importance="must", synonyms=["ML"]),
    Keyword(term="Snowflake", importance="must", category="tool"),
    Keyword(term="A/B testing", importance="should", synonyms=["A/B tests"]),
])
DOC = DocContext(facts=FactInventory(tools=["Python", "Spark", "Airflow"]), job=JOB)
ORIG = "Built ML features in Spark that lifted conversion 12% across 3 markets."


def rules(new: str, scope: str = "bullet") -> set[str]:
    return {v.rule_key for v in check_block(BlockContext("p1", ORIG, scope), new, DOC)}


def test_contains_term_respects_tech_tokens():
    assert contains_term("Wrote C++ and C# services", "C++")
    assert contains_term("ran A/B tests weekly", "A/B tests")
    assert not contains_term("Scala developer", "Scal")
    assert contains_term("Node.js APIs", "node.js")


def test_numbers_are_canonical():
    assert bare_numbers("Cut cost by $2.1M (38%) for 1,200 users") == {"2.1", "38", "1200"}


def test_tech_terms_skip_sentence_start():
    assert tech_terms("Built pipelines on Snowflake with dbt and AWS") >= {"Snowflake", "AWS"}
    assert "Built" not in tech_terms("Built pipelines")


def test_faithful_terminology_alignment_passes():
    assert rules("Built machine learning features in Spark that lifted conversion 12% across 3 markets.") == set()


def test_invented_metric_is_blocked():
    new = "Built ML features in Spark that lifted conversion 12% across 3 markets, saving $400K."
    assert "facts.numbers" in rules(new)


def test_invented_tool_is_blocked_in_bullets():
    got = rules("Built ML features in Spark and Snowflake that lifted conversion 12% across 3 markets.")
    assert {"facts.terms", "facts.keywords"} & got


def test_fact_inventory_allows_known_tool_in_summary_only():
    new = "Built ML features in Spark and Airflow that lifted conversion 12% across 3 markets."
    assert "facts.terms" in rules(new, scope="bullet")
    assert "facts.terms" not in rules(new, scope="summary")


def test_unsupported_jd_keyword_is_blocked():
    new = "Built ML features in Spark with A/B testing that lifted conversion 12% in 3 markets."
    assert "facts.keywords" in rules(new)


def test_length_budget_and_banned_phrases():
    assert "layout.length" in rules("Built ML features.")
    new = "Spearheaded ML features in Spark that lifted conversion 12% across 3 markets."
    assert "authenticity.phrases" in rules(new)
