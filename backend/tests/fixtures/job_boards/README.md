# Job board fixtures

These files mirror the response shapes of each board's public posting API (and Ashby's
posting page), as observed on 2026-11-25: same keys, nesting, HTML escaping and markup
quirks. Company names, ids and description text are synthetic and shortened, so no real
posting is stored in the repository.

| File | Source endpoint |
| --- | --- |
| greenhouse_job.json | `GET boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}` |
| lever_posting.json | `GET api.lever.co/v0/postings/{company}/{id}` |
| ashby_job_board.json | `GET api.ashbyhq.com/posting-api/job-board/{org}` |
| ashby_job_page.html | `GET jobs.ashbyhq.com/{org}/{id}` (JSON-LD in the served HTML) |
| smartrecruiters_posting.json | `GET api.smartrecruiters.com/v1/companies/{company}/postings/{id}` |

`RT_LIVE_JOB_BOARDS=1 pytest tests/platform/test_job_boards.py -m live` checks the real APIs.
