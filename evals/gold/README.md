# Gold set: real resumes, human judgement

This folder is for real resume and job description pairs, so we can answer two
questions with evidence: is the tool's output actually good, and can we trust the
automatic (LLM) judge that scores it?

## Privacy first

Real resumes are personal data. Everything under `evals/gold/<your_case>/` is ignored by
git (see `.gitignore`), so it cannot be committed by accident. Never copy a real resume
into the repo anywhere else, never paste one into an issue or pull request, and never
upload the `output/` folders. The only tracked case is `_example/`, which uses an
invented person (an example.com email) and an invented job posting. Real text is sent
to the Anthropic API when you run the tool, so only use resumes whose owners agreed.

## Folder layout

One folder per case. Pick a short name with no spaces, such as `alex_data_analyst`.

```
evals/gold/alex_data_analyst/
  resume.docx            the original resume (DOCX preferred; resume.pdf also works)
  job.txt                the job description, pasted as plain text
  human_tailored.docx    optional: the same resume tailored by a person (or human_tailored.txt)
  ratings.yaml           optional: your scores of the tool's output (step 3)
  output/                created by the tool: changes, review page, judge results
```

See `_example/` for a working layout.

## Workflow

1. Run the tool on your cases. From the repo root: `make eval-gold` (needs
   `ANTHROPIC_API_KEY` in `.env`; costs about 5 to 10 cents per case and stops at
   `GOLD_MAX_USD`, default 2). To run one case: `cd backend && .venv/bin/python
   ../evals/run_gold.py run --yes --case alex_data_analyst`.
2. Read `output/review.md` in each case. It lists every change side by side (original
   vs proposed, and why), then the gaps the tool reported. If you have a
   `human_tailored` file, the judge also scores that version, so we can see how it
   treats careful human work. Copy `output/ratings.template.yaml` to
   `ratings.yaml` (one level up, next to `resume.docx`) and fill it in: 1 to 5 for
   truthfulness, relevance, readability, and voice, plus keep/drop for each change. The
   template explains each score. Leave a score as `null` if you are unsure.
3. Run `make eval-gold-calibrate`. It compares your scores with the judge's, offline and
   free, and writes a report to `evals/reports/gold_<time>/`. It tells you per
   dimension whether the judge is calibrated or only directional. With fewer than 10
   rated cases the report says it cannot conclude anything: collect more pairs.

If you re-run step 1, the output changes and your old ratings no longer match it. The
report skips them with a "stale" warning; copy the new template and re-rate.
