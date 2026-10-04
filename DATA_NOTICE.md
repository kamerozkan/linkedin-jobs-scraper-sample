# Data notice

This repository contains integration examples for an independent, unofficial Actor. It is not affiliated with or endorsed by LinkedIn.

Output samples come from owner-run public-page tests on September 30, 2026. Description text is redacted and HTML is omitted. Public job IDs, URLs and metadata demonstrate the contract. Shortened samples are not complete job content, customer evidence or complete market inventories.

The Actor does not collect recruiter profiles, applicant identities, emails or phone numbers. Check source terms, applicable rights and permissions before collecting or redistributing content.

Keep API tokens, private customer inputs, webhooks, secrets and personal applicant data out of this repository. Seen job IDs remain in watchlist storage; manage state and retention in your own account.

## Earlier listing-only update on September 30, 2026

The Store title, description and search metadata were checked against the owned Actor and synchronized with this repository. This documentation update does not alter executable code, input or output schemas, recorded test outputs, artifact hashes, billing or runtime builds. Existing examples retain their original dates and validation limits. A public listing is not evidence of successful output, network acceptance or an achieved search ranking.

## Local incremental delivery workflow

`deliver_jobs.py` is new consumer-side integration code. It does not change the Actor executable, existing examples, input/output schemas, billing or the source run's build. Offline mode reads actual downloaded rows and run provenance, without API access. Explicit live mode starts one bounded Actor run; `--run-id` retrieves an existing completed run with GET only and does not create another Actor run. API modes use an environment token only in an Authorization header to the official Apify API. They refuse redirects and do not persist or print the token, request headers, private input or raw API error bodies.

The script exports actual source rows observed as new by a customer-owned SQLite watchlist. The first processed snapshot establishes local history; a later snapshot can overlap entirely and correctly export zero new jobs. A local replay is not a new source run, new market activity or another paid customer. Capped, incomplete and failed-search information from `OUTPUT` stays separate from local delivery counts. Platform success does not establish complete job-market coverage. Unavailable or malformed job rows are excluded and counted; exclusions are not proof that jobs do not exist.

API downloads take their expected count from `OUTPUT.rowsEmitted` and check actual pages with bounded retries and an empty final probe. Dataset metadata may lag behind a newly completed run; its count is retained as informational `datasetMetadataItemCount`, rather than silently replacing the source output count. A mismatch still fails before seen state advances. Resumed source provenance is labeled `existing_cloud_run` and retains the actual saved limits and source build.

Optional content updates are observations of the same identity, not new postings. Older snapshots do not reverse newer content. Disappearance, absence and empty datasets are never treated as job closure or a verified application outcome. Official application, ghost-job and publication-safety fields retain only the source's values; the export adds no verification evidence.

Prepared SQLite batches can contain full job descriptions for crash recovery. JSON/CSV artifacts can also contain full public description text when the source provided it. Store these files privately, apply appropriate retention and redistribution permissions, and do not commit them to this sample repository. `.delivery`, SQLite files and local test artifacts are ignored by Git. Public verification should use minimized job IDs, URLs, titles and metadata with provenance/counts rather than publishing full description bodies or customer watchlist inputs. Existing shortened output samples retain their original scope.

The September 30 owner verification used two actual, capped cloud runs of the same Berlin search, on builds `0.1.3` and `0.1.4`. Each returned 10 accepted rows. Shared local history produced 10 new jobs from the first observation and zero new jobs with 10 unchanged jobs from the second; both source searches were marked incomplete because their configured limit was reached. The second export resumed its existing source run through GET only. These observations verify the local overlap handling for that pair, not complete market coverage, new market activity, an external delivery or a paying customer's result.

CSV formula protection changes dangerous text cells only in the CSV representation; the JSON source row remains unchanged. All 18 synthetic unit tests passed on September 30, 2026, covering crash boundaries, local state, duplicates, exports and mocked HTTP behavior. They do not prove continuous source availability or an external destination's delivery guarantees. No local schedule or external destination is activated by adding these files.

The added workflow verification records two actual owner-started public-search observations on September 30, 2026, with 10 rows each. `workflow-observed-identities.json` omits full descriptions and account/platform-cost data. Local SQLite state and complete raw datasets are not published. GET-only export recovery uses the existing cloud run and is not another scrape. Local filtering does not refund collection charges. No external customer or delivery endpoint is represented.

## Offline collection-to-verification handoff on October 1, 2026

`verified_job_feed.py` is local consumer code, independent of the Actor runtime and pricing. It uses no network, credentials or Actor SDK. READY new-job artifacts are hash-bound and only selected minimum job hints enter the prepared request. Full source rows, deferred rows and held decisions remain local and should not be committed. Merge requires the exact saved verification input and provenance, with identity, timestamp, count and publication checks. A local publishable file is not an external delivery, a current availability guarantee or customer revenue.

The bundled `verified-feed-synthetic-demo` contains invented jobs, source records and decisions. It demonstrates two publishable fixture records and one held expired fixture; none is a real verified application route or charged event. Its explicit historical evaluation clock does not establish current availability. Do not send the invented input to a paid Actor.

The separate public proof records local replay of genuine September 30 collection batches: 10 new prepared rows, then zero new rows and no verification input. A different historical mixed verification request was rejected. No newly matched live end-to-end run occurred. Synthetic merge tests remain distinct from those real source preparation observations. Existing Actor builds, schemas, prices and earlier evidence retain their original dates and scope.

## Consumer helper repairs on October 2, 2026

The local delivery and verification helpers and their regression tests changed after demonstrated identity, observation-clock, billing-type and recovery failures. `qa-verification-2026-10-02.json` contains redacted before/after counts, local test results, current helper hashes and replay provenance. The old dated evidence files are retained as historical snapshots rather than relabeled. No newly collected jobs, customer datasets, account finance or private files are published in this repair. The historical owner batches and invented fixture are separate from fresh source availability, customer adoption or realized revenue. Actor runtime/build/schema/pricing and external delivery are unchanged.

## Maintenance evidence on October 4, 2026

[example_run_input.json](example_run_input.json) is the exact public JSON body saved and read back as the Actor's API `exampleRunInput`, replacing an unrelated `helloWorld` placeholder. [Verification evidence](maintenance-verification-2026-10-04.json) records deployed-schema validation and saved metadata parity. Its values come from already-public input-schema prefills, not a private customer Task.

This change did not start an Actor run or change runtime/build/schema/pricing. JSON/schema validity and a retrieved public fixture do not establish successful processing, current source availability or useful output. Existing outputs remain unchanged with their original dates and evidence class. Set your own run spending limit before execution; workload limits are not a hard financial cap. Keep tokens in your environment and Authorization header, and keep customer files out of this repository.
