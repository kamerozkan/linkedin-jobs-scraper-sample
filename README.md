# LinkedIn Jobs Scraper - Full Descriptions, No Login: Samples

LinkedIn jobs scraper by keyword, location or company, without login. Export full public descriptions for job-board feeds, recruitment research and job alerts. Use new-jobs-only history and ready-to-run Berlin, London and US examples. From $1 per 1,000 jobs; optional apply-link checks cost extra.

[Run LinkedIn Jobs Scraper - Full Descriptions, No Login on Apify](https://apify.com/kamerozkan/linkedin-jobs-scraper)

Collect public LinkedIn jobs by keyword and location without a LinkedIn login. These examples use the current contracts of the [live Actor](https://apify.com/kamerozkan/linkedin-jobs-scraper), build `0.1.3`, verified on September 30, 2026.

The output includes title, company, location, posting date and full public description. It excludes recruiter profiles, applicant identities, emails and phone numbers. Missing source fields remain null.

## Ready to run examples

| Workflow | Store example | Exact input |
| --- | --- | --- |
| Repeat Berlin engineering search | [Collect new Berlin jobs](https://apify.com/kamerozkan/linkedin-jobs-scraper/examples/collect-new-software-engineering-jobs-in-berlin) | [Berlin input](examples/berlin-input.json) |
| London recruitment research | [Export London analyst jobs](https://apify.com/kamerozkan/linkedin-jobs-scraper/examples/export-data-analyst-jobs-in-london) | [London input](examples/london-input.json) |
| US hiring market sample | [Research US cybersecurity hiring](https://apify.com/kamerozkan/linkedin-jobs-scraper/examples/research-cybersecurity-hiring-in-the-united-states) | [US input](examples/us-input.json) |

Each starter is capped at 20 jobs. Duplicate the task into your account, customize its keywords and locations, then adjust the result and spending caps. The published examples do not automatically create a schedule.

## Python and Node.js

Use Python 3.11 or later with the official Python client 3.x, or Node.js with the official JavaScript client. Set `APIFY_TOKEN` in your environment:

```bash
pip install -r requirements.txt
python run_scraper.py
python run_scraper.py examples/london-input.json
```

```bash
npm install
node run_scraper.mjs
node run_scraper.mjs examples/us-input.json
```

Both scripts default to [input.sample.json](input.sample.json), use a $0.50 maximum charge and a 300-second timeout, and print returned job URLs. They never print your token. Set optional `APIFY_BUILD` to a specific build number when your integration needs a pinned release.

```json
{
  "keywords": ["software engineer"],
  "locations": ["Berlin, Germany"],
  "datePosted": "pastWeek",
  "sortBy": "date",
  "maxJobsPerSearch": 20,
  "includeJobDetails": true,
  "newJobsOnly": false,
  "verifyApplyLinks": false
}
```

## Current input contract

[input.schema.json](input.schema.json) is the deployed Actor input schema.

| Field | Type | Meaning |
| --- | --- | --- |
| `keywords` | String array | Up to 20 terms |
| `locations` | String array | Up to 20 locations; empty means worldwide |
| `searchUrls` | String array | Up to 20 public LinkedIn search URLs |
| `datePosted` | String | `anyTime`, `past24Hours`, `pastWeek`, `pastMonth` |
| `maxJobsPerSearch` | Integer | 10 to 1,000 results per search |
| `includeJobDetails` | Boolean | Fetch public details, enabled by default |
| `newJobsOnly` | Boolean | Suppress IDs seen in earlier runs of the same watchlist |
| `stateNamespace` | String | `auto` isolates each saved Task's history |
| `verifyApplyLinks` | Boolean | Optional separate paid verification Actor; disabled here |

`newJobsOnly` does not set the posting-date filter. For daily alerts, choose `datePosted: "past24Hours"` and `sortBy: "date"` separately, save an Apify Task and schedule it. An empty later run can mean there are no unseen jobs.

Workplace type, employment type and seniority selections are search-text hints in the current implementation, not exact filters. Inspect returned structured fields when those conditions matter. LinkedIn can rank or geo-resolve a broad search differently between sessions.

## Output and billing

[output.sample.json](output.sample.json) contains shortened records from September 30 owner tests. [dataset.schema.json](dataset.schema.json) is the current record contract.

Canonical keys include `id`, `url`, `applicantsCount` and `detailStatus`. `detailStatus` is `complete`, `not_requested` or `unavailable`. Descriptions are available as `descriptionText` and `descriptionHtml` when requested and publicly readable.

The FREE discount tier costs $0.001 per delivered job plus $0.005 per GB of memory, with a minimum of one start event. Paid plans have lower job rates. A 20-job run at 512 MB is approximately $0.025 at FREE or $0.023 at BRONZE. Unavailable detail rows are not charged. Optional apply-link verification adds separate Actor charges. Check the live pricing tab for current rates.

## Verification and limits

On September 30, all three saved example inputs completed on build `0.1.2`, each returning 20 unique jobs with 20 nonempty descriptions. [verification.json](verification.json) records the run IDs and scoped checks. Release `0.1.3` changes only the Store README, retaining the same input and output contracts. A further London-input check returned 20 unique jobs and 20 nonempty descriptions on that build. The Python client 3.2.1 and JavaScript client 2.25.0 scripts were also exercised against cloud runs; see [release-verification.json](release-verification.json). These are owner tests, not customer testimonials or guarantees for every market. A capped sample does not establish complete market coverage.

Read [DATA_NOTICE.md](DATA_NOTICE.md) before redistributing source content. This repository is an integration sample, not an official LinkedIn API or a licensed bulk dataset.

## Build a recruitment data pipeline

Start with this Actor to collect postings. If you need official application URLs, pass its dataset to the [apply-link verifier](https://apify.com/kamerozkan/linkedin-job-apply-link-verifier). For recurring changes on a fixed list of employers, use [Hiring Signals](https://apify.com/kamerozkan/linkedin-hiring-signals). Each Actor has separate billing and quality checks. Verify the returned evidence before publishing jobs to your board.
