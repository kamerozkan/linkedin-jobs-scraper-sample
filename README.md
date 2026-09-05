# LinkedIn Jobs Scraper API & Dataset Sample (No Login)

[![Apify Actor](https://img.shields.io/badge/Apify-Actor-blue?logo=apify)](https://apify.com/kamerozkan/linkedin-jobs-scraper)
[![Pricing](https://img.shields.io/badge/Price-%241.00%20%2F%201k%20jobs-brightgreen)](https://apify.com/kamerozkan/linkedin-jobs-scraper)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Runnable Python and Node.js examples, sanitized JSON outputs, and input schema for the [LinkedIn Jobs Scraper Apify Actor](https://apify.com/kamerozkan/linkedin-jobs-scraper).

Scrape public LinkedIn job postings by keyword, location, company, and seniority without login or cookies.

---

## Key Features

- **No login, account, or session cookies required:** Scrapes public search and unauthenticated detail endpoints.
- **Fair pricing:** **$1.00 per 1,000 jobs** ($0.001 per result; 50% cheaper than market leaders).
- **Free unavailable rows:** If a job's detail page cannot be retrieved due to upstream deletion, it is marked `detailStatus: "unavailable"` and is **100% free**.
- **Automatic filter workaround:** In August 2026, LinkedIn quietly stopped respecting guest query parameters (`f_JT`, `f_WT`, `f_E`). This Actor dynamically compiles user filters into strict boolean query syntax `(Role AND Remote)` in the keyword field, restoring 95%+ accurate remote and job-type filtering.
- **`newJobsOnly` mode:** Only emit jobs posted within the last 24 hours (`f_TPR=r86400`) for clean scheduled daily monitoring.
- **Isolated proxy sessions:** Each search page and detail fetch runs under dedicated datacenter proxy sessions with automatic 3x retries.

---

## Quickstart (Python)

Run the scraper using the official `apify-client` Python SDK:

```bash
pip install apify-client
```

```python
from apify_client import ApifyClient

# Initialize with your Apify API token
client = ApifyClient("YOUR_APIFY_TOKEN")

# Define search parameters
run_input = {
    "keywords": "AI Engineer",
    "location": "United States",
    "maxJobs": 50,
    "sortBy": "date",
    "remote": "remote_only",
    "newJobsOnly": True
}

# Run the Actor and fetch results
run = client.actor("kamerozkan/linkedin-jobs-scraper").call(run_input=run_input)

for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(f"[{item.get('postedAt')}] {item.get('title')} at {item.get('companyName')} ({item.get('location')})")
    print(f"  URL: {item.get('jobUrl')}")
    print(f"  Applicants: {item.get('applicantCount', 'N/A')}")
```

---

## Quickstart (Node.js)

```bash
npm install apify-client
```

```javascript
import { ApifyClient } from 'apify-client';

const client = new ApifyClient({
    token: 'YOUR_APIFY_TOKEN',
});

const run = await client.actor('kamerozkan/linkedin-jobs-scraper').call({
    keywords: 'Staff Software Engineer',
    location: 'Germany',
    maxJobs: 25,
    sortBy: 'date',
});

const { items } = await client.dataset(run.defaultDatasetId).listItems();
console.log(`Fetched ${items.length} jobs:`);
for (const job of items) {
    console.log(`- ${job.title} @ ${job.companyName} (${job.location}) -> ${job.jobUrl}`);
}
```

---

## Sample Output Record

```json
{
  "jobId": "4125896321",
  "title": "Staff Software Engineer, Platform Infrastructure",
  "companyName": "GitHub",
  "companyUrl": "https://www.linkedin.com/company/github",
  "companyId": "1418841",
  "location": "San Francisco, CA (Remote)",
  "jobUrl": "https://www.linkedin.com/jobs/view/4125896321",
  "postedAt": "2026-09-04",
  "postedTimeAgo": "1 day ago",
  "applicantCount": 42,
  "employmentType": "Full-time",
  "seniorityLevel": "Mid-Senior level",
  "jobFunction": "Engineering and Information Technology",
  "industries": "Software Development",
  "descriptionText": "As a Staff Software Engineer on Platform Infrastructure, you will design and scale...",
  "descriptionHtml": "<div><p>As a Staff Software Engineer...</p></div>",
  "detailStatus": "available",
  "scrapedAt": "2026-09-05T08:00:15.120Z"
}
```

---

## Input Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `keywords` | String | *Required* | Job title, skill, or company (e.g. `"Python Developer"`). |
| `location` | String | `""` | Country, state, city, or postal code. |
| `maxJobs` | Integer | `50` | Maximum job postings to collect (up to 5,000). |
| `sortBy` | Enum | `"date"` | Sort by `"date"` or `"relevance"`. |
| `jobType` | Array | `[]` | `["full_time", "contract", "part_time", "internship"]`. |
| `remote` | Enum | `"any"` | `"any"`, `"remote_only"`, `"on_site"`, `"hybrid"`. |
| `experienceLevel` | Array | `[]` | `["entry_level", "associate", "mid_senior", "director"]`. |
| `newJobsOnly` | Boolean | `false` | Restrict search to jobs posted in the last 24 hours. |

---

## Links

- **Live Apify Actor:** [https://apify.com/kamerozkan/linkedin-jobs-scraper](https://apify.com/kamerozkan/linkedin-jobs-scraper)
- **Author Profile:** [https://apify.com/kamerozkan](https://apify.com/kamerozkan)
- **Report Issues / Feedback:** [GitHub Issues](https://github.com/kamerozkan/linkedin-jobs-scraper-sample/issues)
