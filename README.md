# LinkedIn Jobs Scraper - Full Descriptions, No Login: Samples

LinkedIn jobs scraper by keyword, location or company, without login. Export full public descriptions for job-board feeds, recruitment research and job alerts. Use new-jobs-only history and ready-to-run Berlin, London and US examples. From $1 per 1,000 jobs; optional apply-link checks cost extra.

[Run LinkedIn Jobs Scraper - Full Descriptions, No Login on Apify](https://apify.com/kamerozkan/linkedin-jobs-scraper)

Collect public LinkedIn jobs by keyword and location without a LinkedIn login. These examples use the current contracts of the [live Actor](https://apify.com/kamerozkan/linkedin-jobs-scraper), build `0.1.3`, verified on September 30, 2026.

The output includes title, company, location, posting date and full public description. It excludes recruiter profiles, applicant identities, emails and phone numbers. Missing source fields remain null.

## Consumer QA fixes on October 2, 2026

The offline delivery and verification helpers were hardened after five reproducible local failures: future source timestamps could poison seen history, a malformed LinkedIn job route could hide behind a numeric ID, a string billing flag could bypass useful-decision accounting, and symlink exports or corrupt READY markers could break recovery. Future row clocks over collection finish plus five seconds are rejected; present URLs must match a numeric LinkedIn job identity. Recovery now refuses unsafe files and false readiness before claiming a usable batch. Verification requires an actual boolean billing mode and consistent event counts.

All 57 local tests passed: 23 delivery and 34 verification-handoff tests, with zero network connections. Replaying the genuine dated September 30 source batches still prepared 10 new jobs and skipped the second batch's zero new jobs; the invented demo still produced two publishable rows and one held row. [October 2 findings, code hashes and validation scope](qa-verification-2026-10-02.json). Earlier September 30 and October 1 evidence describes the code and observations from those dates; it is not a fresh live-source check. No Actor runtime, build, schema or price changed, and no new cloud run or external delivery was made.

## Verify only newly delivered jobs

For job-board editors and recruitment teams, [verified_job_feed.py](verified_job_feed.py) connects this collector's incremental feed to the [Apply Link Verifier](https://apify.com/kamerozkan/linkedin-job-apply-link-verifier). It prepares only a READY batch's `new-jobs.json`, rather than sending the original collection dataset, including previously seen jobs, into another verification run. It then joins exported verification decisions back to the same job identities and produces separate publication and review files.

The helper uses Python 3.11+ and the standard library. Both commands are entirely offline: they read local files, never use a token, never fetch URLs and never start or charge an Actor.

### Try the free, synthetic demonstration

The bundled fixture is completely invented. It demonstrates file handling and release decisions, not real job availability, source access, customer results or revenue. Do not submit its input to a paid Actor.

```bash
python3 verified_job_feed.py prepare \
  --batch examples/verified-feed-synthetic-demo/source-batch \
  --out .delivery/synthetic-verification-request

python3 verified_job_feed.py merge \
  --request .delivery/synthetic-verification-request \
  --verifier-input examples/verified-feed-synthetic-demo/synthetic-INPUT.json \
  --run examples/verified-feed-synthetic-demo/synthetic-run.json \
  --rows examples/verified-feed-synthetic-demo/synthetic-rows.json \
  --summary examples/verified-feed-synthetic-demo/synthetic-OUTPUT.json \
  --out .delivery/synthetic-verified-feed \
  --as-of 2026-09-30T13:00:00Z
```

Expected local results: two publishable fixture rows and one held `EXPIRED` fixture, in JSON and CSV. The explicit evaluation clock is part of the dated synthetic replay; it does not recheck today's availability. Nothing is sent to an external job board. [Fixture notice and expected counts](examples/verified-feed-synthetic-demo/NOTICE.md).

### Use your own completed collection and verification

1. Export your completed collection with [deliver_jobs.py](#deliver-only-new-jobs). Use a batch directory containing `READY`, and retain its metadata and all four JSON/CSV artifacts.
2. Run `python3 verified_job_feed.py prepare --batch YOUR_READY_BATCH --out .delivery/verification-request --max-items 20`. Inspect `manifest.json` and `verifier-input.json`. Empty new-job batches return `SKIPPED_NO_NEW_JOBS` and produce no runnable verifier input. Larger batches retain deferred rows locally; use `--offset` and a separate request directory for the next slice.
3. If you choose to make a paid verification run, submit the exact prepared JSON to the Verifier with a spending limit you set after checking current pricing. Keep its actual saved `INPUT`, run metadata, complete dataset JSON and `OUTPUT`. Neither helper starts this run. Editing settings or using an older run changes the request contract and causes merge to reject it.
4. Merge those actual files:

```bash
python3 verified_job_feed.py merge \
  --request .delivery/verification-request \
  --verifier-input private-verification/INPUT.json \
  --run private-verification/run.json \
  --rows private-verification/rows.json \
  --summary private-verification/OUTPUT.json \
  --out .delivery/verified-feed
```

Use `publishable-jobs.json` or `.csv` only after reading the summary. Inspect `held-jobs.json` or `.csv` for missing, expired, ambiguous, unsafe, mismatched or review-required decisions. A charged/useful decision is not automatically a publishable application route. Safe LinkedIn Easy Apply routes can have no separate employer URL.

Preparation checks READY metadata, counts, identity and artifact hashes. Merge checks the saved input's exact types and digest, job identity plus source index, source timestamps, run status, counts, supported decision flags and public HTTPS routes. Rows are not joined by dataset order. The original description stays on the local source row; only necessary job hints enter the prepared request. Scores and statuses remain source observations at `checkedAt`. Current availability stays unknown without another source check; missing jobs never imply closure. CSV formula protection is applied to the exported text cells. Keep these full local source and review files private.

This prevents unchanged locally seen jobs from entering this prepared verification input; it does not refund collection charges or prevent charges if you manually repeat a paid verification run. No schedule, webhook, email or external job-board importer is installed.

On October 1, 2026, local replay of the genuine September 30 batches prepared 10 new jobs from the first snapshot and skipped the second snapshot's zero new jobs. The older four-row verification request was correctly rejected as a different input. A newly matched live collection-to-verification run was not performed. Separately, 29 synthetic local tests and the free demo passed. [Dated proof and exact validation limits](verified-feed-verification-2026-10-01.json).

## Deliver only new jobs

The September 30 owner integration used two genuine cloud runs of the same capped Berlin search, with 10 complete job rows each. The first local batch delivered 10 new jobs; the second delivered zero new jobs and retained all 10 seen identities. The second run's initial export stopped on a count disagreement; GET-only resumption of that same completed run passed the checks and exported the ready batch. No third scrape was started for recovery. [Source IDs, caps and validation boundaries](workflow-verification-2026-09-30.json), [the input](workflow-input.json) and [observed identities without full descriptions](workflow-observed-identities.json).

Release `0.1.4` changes only the Actor README and was checked by the second cloud run. Local filtering does not refund either run's collection charges: both source runs returned 10 billable job rows. The collector keeps `newJobsOnly:false` because this consumer owns its history; the separate saved Task's native `newJobsOnly` feature is another option when you want Actor-managed history. These owner tests are not customer revenue or full-market evidence.

[deliver_jobs.py](deliver_jobs.py) turns actual completed-run datasets into a local incremental JSON/CSV feed. It needs Python 3.11 or later on macOS or Linux and uses only the standard library. You can process an already downloaded dataset without a token or another paid run.

Export the dataset as a JSON array and save the actual source run JSON and its `OUTPUT` record. Use the same watchlist label and SQLite state for both observations:

```bash
python3 deliver_jobs.py \
  --dataset-file private-snapshots/first/rows.json \
  --run-file private-snapshots/first/run.json \
  --output-file private-snapshots/first/OUTPUT.json \
  --watchlist berlin-software-engineer \
  --state .delivery/seen.sqlite --output-dir .delivery/batches

python3 deliver_jobs.py \
  --dataset-file private-snapshots/second/rows.json \
  --run-file private-snapshots/second/run.json \
  --output-file private-snapshots/second/OUTPUT.json \
  --watchlist berlin-software-engineer \
  --state .delivery/seen.sqlite --output-dir .delivery/batches
```

The `private-snapshots` paths above are your downloaded files, not bundled example datasets. Source run, dataset and build IDs come from `run.json`; the script never labels a local replay as another cloud run. It requires source platform status `SUCCEEDED`, rejects a failed `OUTPUT` or a snapshot with a mismatched declared row count, and records capped or incomplete search coverage separately. A useful 10-row sample with `complete:false` and `stopReason:limit_reached` does not prove complete market coverage.

Every new delivery batch has a stable `batch-<id>` directory with `new-jobs.json`, `new-jobs.csv`, `updated-jobs.json`, `updated-jobs.csv` and `metadata.json`. Only consume directories containing `READY`. Metadata includes source run/dataset/build, observed time, source row hash, event charge limit returned by the API, download/count checks, rejection counts and artifact hashes. `reportedUsageTotalUsd` preserves the API field; it is not an estimated price, an invoice or customer revenue.

New means first observed in that watchlist's local state. Numeric `id` and canonical LinkedIn job URLs resolve to the same identity, including URL tracking-parameter variations. An identical dataset processed again delivers zero new jobs. Missing identities, failed rows, unavailable details, empty descriptions marked complete and conflicting duplicate observations are excluded without being added to seen history. A genuinely empty successful dataset exports empty files and does not remove prior jobs. An absent job is never inferred to be closed.

Use `--include-updates` from the start if you also need observed content changes in `updated-jobs.*`. Changes to title, company, location, posting date, descriptions, employment/seniority, salary, official apply URL, job status or detail status count as updates to an existing identity. Source timestamps, relative posting text, applicant counts and Actor `isNew` flags do not. Older observations cannot roll back newer content. Updates observed while the flag is disabled are recorded in state but are not backfilled when it is later enabled.

CSV text cells that could be interpreted as spreadsheet formulas receive an apostrophe prefix, including leading whitespace/control-character cases. JSON retains the actual source records. Local locking, durable prepared batches, atomic directory publication and SQLite transactions recover interrupted exports before advancing seen state. A retry completes the same prepared batch and keeps its ID; downstream consumers should also remember batch IDs. This local workflow does not guarantee exactly-once delivery to an external service.

To explicitly start one new cloud run, set `APIFY_TOKEN` in your existing environment and use:

```bash
python3 deliver_jobs.py --live-input input.sample.json \
  --watchlist berlin-software-engineer --state .delivery/seen.sqlite \
  --output-dir .delivery/batches --max-total-charge-usd 0.05 \
  --timeout-secs 300 --build 0.1.3
```

Live mode uses 512 MB, the requested server timeout and `maxTotalChargeUsd`, checks the returned limits, and downloads only after the run succeeds. Its requests follow the official [Run Actor API](https://docs.apify.com/api/v2/actors-runs-post) and [dataset items API](https://docs.apify.com/api/v2/dataset-items-get). It rejects `verifyApplyLinks:true` and `newJobsOnly:true`: this consumer owns incremental history. The token is sent only in the Authorization header to `https://api.apify.com`, redirects are refused, and request bodies or private error details are not logged. GET requests have bounded retries; run creation is attempted once because retrying an uncertain POST could create another charged run. Check Console after an uncertain creation or polling failure. Rerunning `--live-input` starts another potentially billable run; offline mode never starts one.

If a run already exists, resume its download/export without starting another Actor. Replace `RUN_ID_FROM_CONSOLE` with that completed run's ID, keep `APIFY_TOKEN` in your environment, and reuse the same local state:

```bash
python3 deliver_jobs.py --run-id RUN_ID_FROM_CONSOLE \
  --watchlist berlin-software-engineer --state .delivery/seen.sqlite \
  --output-dir .delivery/batches
```

This mode uses GET only and labels provenance `existing_cloud_run`. It preserves the original run's saved build, time and charge limits; it does not change them. Both API modes read `OUTPUT.rowsEmitted` before downloading. Fresh dataset metadata can temporarily report zero while actual items exist, so `datasetMetadataItemCount` is informational. The exported `datasetItemCount` is the actual downloaded count checked against `OUTPUT`. Each page has at most three consistency attempts, and a final probe must contain no extra rows. A remaining mismatch stops delivery without advancing seen state. Resume the known run after a download/export interruption instead of starting another paid run.

A reasonable starting cadence is one scheduled daily collection for a capped watchlist, followed by this local export step. Reuse the same state and watchlist, consume only ready batches and inspect source warnings and rejection counts. No schedule, webhook, email delivery or paid external destination is configured by these examples. Keep a backup of SQLite state and local artifacts; deleting the state intentionally makes observed jobs new again.

On September 30, 2026, two owner cloud runs of the same capped Berlin search returned 10 accepted rows each: build `0.1.3` first, then build `0.1.4`. Using the same local SQLite history, the first delivery exported 10 new jobs; the second exported zero new jobs and counted 10 unchanged jobs, with no changed or rejected rows. The second run was downloaded through GET-only resumption of its existing run ID. Both searches stopped at their configured limit with `complete:false`. This verifies overlapping-run deduplication for those observations; it does not establish complete coverage, newly posted market activity, continuous source availability or delivery to an external destination.

Run the local verification suite with `python3 -m unittest -v test_deliver_jobs.py`. All 18 tests passed on September 30, 2026. Its synthetic fixtures test duplicate/replay handling, stale updates, transaction/export recovery, invalid rows, CSV protection, metadata lag, short-page failures and GET-only resumption. They are separate from the two actual cloud observations and are not live source availability evidence. Existing public input/output examples and schemas are unchanged.

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
