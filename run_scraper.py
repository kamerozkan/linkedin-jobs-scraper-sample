#!/usr/bin/env python3
"""Run the current LinkedIn Jobs Actor. Install apify-client first."""
import argparse
import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from apify_client import ApifyClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default=str(Path(__file__).with_name("input.sample.json")))
    args = parser.parse_args()
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        parser.error("Set APIFY_TOKEN in your environment before running this example.")
    run_input = json.loads(Path(args.input).read_text())
    client = ApifyClient(token)
    run = client.actor("kamerozkan/linkedin-jobs-scraper").call(
        run_input=run_input, build=os.environ.get("APIFY_BUILD", "latest"), memory_mbytes=512, run_timeout=timedelta(seconds=300),
        max_total_charge_usd=Decimal("0.50"), logger=None,
    )
    if not run or run.status != "SUCCEEDED":
        raise RuntimeError("Actor did not complete successfully; inspect the run in Apify Console.")
    print(f"Run: {run.id} | Dataset: {run.default_dataset_id}")
    items = list(client.dataset(run.default_dataset_id).iterate_items())
    print(f"Collected {len(items)} job postings")
    for job in items:
        print(f"{job.get('title')} @ {job.get('companyName')} | {job.get('location')} | {job.get('url')}")


if __name__ == "__main__":
    main()
