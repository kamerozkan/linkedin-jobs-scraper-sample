#!/usr/bin/env node
import { readFile } from 'node:fs/promises';
import { ApifyClient } from 'apify-client';

if (!process.env.APIFY_TOKEN) {
    throw new Error('Set APIFY_TOKEN in your environment before running this example.');
}
const inputPath = process.argv[2] || new URL('./input.sample.json', import.meta.url);
const input = JSON.parse(await readFile(inputPath, 'utf8'));
const client = new ApifyClient({ token: process.env.APIFY_TOKEN });
const run = await client.actor('kamerozkan/linkedin-jobs-scraper').call(input, {
    build: process.env.APIFY_BUILD || 'latest', memory: 512, timeout: 300, maxTotalChargeUsd: 0.5,
});
if (!run || run.status !== 'SUCCEEDED') {
    throw new Error('Actor did not complete successfully; inspect the run in Apify Console.');
}
console.log(`Run: ${run.id} | Dataset: ${run.defaultDatasetId}`);
const { items } = await client.dataset(run.defaultDatasetId).listItems();
console.log(`Collected ${items.length} job postings`);
for (const job of items) {
    console.log(`${job.title} @ ${job.companyName} | ${job.location} | ${job.url}`);
}
