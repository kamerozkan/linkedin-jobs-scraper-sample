#!/usr/bin/env python3
"""
Quickstart script to run LinkedIn Jobs Scraper on Apify.
Requires: pip install apify-client
"""
import os
import sys
from apify_client import ApifyClient

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
if not APIFY_TOKEN:
    print("Error: Please set APIFY_TOKEN environment variable.")
    print("Example: export APIFY_TOKEN=your_token_here")
    sys.exit(1)

client = ApifyClient(APIFY_TOKEN)

run_input = {
    "keywords": "AI Engineer",
    "location": "United States",
    "maxJobs": 10,
    "sortBy": "date",
    "remote": "remote_only",
    "newJobsOnly": True
}

print(f"Starting LinkedIn Jobs Scraper for '{run_input['keywords']}' in '{run_input['location']}'...")
run = client.actor("kamerozkan/linkedin-jobs-scraper").call(run_input=run_input)

print(f"Run completed with status: {run['status']}")
dataset = client.dataset(run["defaultDatasetId"])

items = list(dataset.iterate_items())
print(f"Collected {len(items)} job postings:\n")

for i, job in enumerate(items, 1):
    print(f"[{i}] {job.get('title')} @ {job.get('companyName')}")
    print(f"    Location: {job.get('location')}")
    print(f"    URL: {job.get('jobUrl')}\n")
