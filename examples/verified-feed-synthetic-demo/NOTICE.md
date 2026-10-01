# Entirely synthetic offline demonstration

Every job, company, source ID, timestamp, decision, confidence value, status and event count in this directory is invented for a local demonstration. These files are not Actor runs, source availability, customer results, verified application links or revenue evidence. No URL is fetched by the example. Do not send this fixture input to a paid Actor.

The three prepared synthetic jobs produce two local publishable fixture records (`ACTIVE` and `LINKEDIN_EASY_APPLY`) and one held fixture (`EXPIRED`). A useful expired decision is distinct from a publishable route. The example's event counter is fictional; no charge occurred.

From the repository root, try the helper without a token or network:

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

The explicit evaluation clock is part of this dated, invented fixture. `currentAvailabilityUnknown` stays true. Local JSON/CSV files are produced; nothing is published to an external job board. Matching input/settings/hashes and the READY markers are checked before output. Expected counts are recorded in `expected-summary.json`.
