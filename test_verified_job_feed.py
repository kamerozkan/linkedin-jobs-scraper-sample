"""Synthetic offline handoff tests. These are not live checks or customer results."""
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import verified_job_feed as feed

AS_OF = "2026-09-30T13:00:00Z"


def job(job_id="1000000001", **changes):
    return {"id": job_id, "url": "https://www.linkedin.com/jobs/view/" + job_id,
            "title": "Synthetic test role", "companyName": "Synthetic test company", "location": "Synthetic test location",
            "descriptionText": "Synthetic description retained in the local handoff.", "detailStatus": "complete",
            "scrapedAt": "2026-09-30T12:00:00Z", **changes}


def source_batch(directory, rows, updates=None):
    directory.mkdir()
    files = {"new-jobs.json": feed.encoded(rows), "new-jobs.csv": b"synthetic,test\n",
             "updated-jobs.json": feed.encoded(updates or []), "updated-jobs.csv": b"synthetic,test\n"}
    metadata = {"formatVersion": 1, "batchId": "a" * 32, "watchlist": "synthetic-test",
                "source": {"platformStatus": "SUCCEEDED", "runId": "SyntheticRun0001", "datasetId": "SyntheticDataset0001", "buildId": "SyntheticBuild0001", "buildNumber": "0.1.4", "observedAt": "2026-09-30T12:00:00Z", "searchCoverage": [{"complete": False, "stopReason": "limit_reached"}]},
                "counts": {"newJobs": len(rows)}, "artifacts": {name: {"sha256": feed.sha(raw), "bytes": len(raw)} for name, raw in files.items()}}
    for name, raw in files.items():
        (directory / name).write_bytes(raw)
    (directory / "metadata.json").write_bytes(feed.encoded(metadata))
    (directory / "READY").write_text(metadata["batchId"] + "\n")


def exported_run(selected, statuses=None):
    statuses = statuses or ["ACTIVE"] * len(selected)
    decisions = []
    for index, (item, status) in enumerate(zip(selected, statuses)):
        row = item["verifierRow"]
        publish = status in feed.PUBLISHABLE
        decisions.append({"sourceIndex": index, "jobId": row["jobId"], "linkedinUrl": row["jobUrl"], "title": row["jobTitle"], "company": row["companyName"], "location": row["location"], "status": status,
                          "actionUrl": row["jobUrl"] if status == "LINKEDIN_EASY_APPLY" else "https://careers.synthetic-example.invalid/jobs/" + row["jobId"] if publish else None,
                          "safeToPublish": publish, "reviewRequired": status in feed.DIAGNOSTIC, "usefulClassification": status in feed.USEFUL,
                          "confidence": 0.97, "sourceProvider": "synthetic_test_provider", "evidence": ["synthetic_test_evidence"], "checkedAt": "2026-09-30T12:01:30Z"})
    run = {"id": "SyntheticVerifier0001", "status": "SUCCEEDED", "defaultDatasetId": "SyntheticVerifierDataset0001", "buildId": "SyntheticVerifierBuild0001", "buildNumber": "0.0.22", "startedAt": "2026-09-30T12:01:00Z", "finishedAt": "2026-09-30T12:02:00Z"}
    summary = summary_for(decisions, len(selected))
    run["chargedEventCounts"] = {"verified-job": summary["usefulClassifications"]}
    return run, decisions, summary


def summary_for(rows, requested):
    return {"status": "SUCCEEDED", "requestedRows": requested, "deliveredRows": len(rows),
            "rows": sum(row["status"] not in {"INVALID_INPUT", "DUPLICATE_INPUT"} for row in rows),
            "usefulClassifications": sum(row["usefulClassification"] for row in rows),
            "safeToPublishRows": sum(row["safeToPublish"] is True for row in rows),
            "billing": {"payPerEventActive": True, "unresolvedRowsCharged": False, "invalidOrDuplicateRowsCharged": False}}


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.batch = self.root / "source-batch"
        self.request = self.root / "request"
        self.output = self.root / "handoff"

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, rows=None, **kwargs):
        source_batch(self.batch, [job()] if rows is None else rows)
        result = feed.prepare(self.batch, self.request, **kwargs)
        return result

    def data(self):
        _, selected, verifier_input = feed.load_request(self.request)
        return selected, verifier_input

    def merge(self, run=None, decisions=None, summary=None, saved_input=None, statuses=None):
        selected, prepared_input = self.data()
        expected_run, expected_rows, expected_summary = exported_run(selected, statuses)
        return feed.merge(self.request, saved_input if saved_input is not None else prepared_input,
                          run or expected_run, decisions if decisions is not None else expected_rows,
                          summary if summary is not None else expected_summary, self.output, AS_OF)

    def test_only_new_batch_rows_are_projected_and_source_is_unchanged(self):
        source_batch(self.batch, [job()], updates=[job("1000000002")])
        before = {p.name: p.read_bytes() for p in self.batch.iterdir()}
        manifest = feed.prepare(self.batch, self.request)
        payload = feed.read_json(self.request / "verifier-input.json")
        self.assertEqual([r["jobId"] for r in payload["rows"]], ["1000000001"])
        self.assertNotIn("datasetId", payload)
        self.assertNotIn("descriptionText", payload["rows"][0])
        self.assertEqual(manifest["source"]["searchCoverage"][0]["complete"], False)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.batch.iterdir()})

    def test_empty_new_batch_skips_input_even_if_updates_exist(self):
        source_batch(self.batch, [], updates=[job()])
        result = feed.prepare(self.batch, self.request)
        self.assertEqual(result["status"], "SKIPPED_NO_NEW_JOBS")
        self.assertFalse((self.request / "verifier-input.json").exists())
        self.assertFalse(result["startsActor"])

    def test_ready_marker_artifact_hash_and_count_are_required(self):
        self.prepare()
        (self.batch / "READY").write_text("wrong\n")
        with self.assertRaises(feed.FeedError):
            feed.prepare(self.batch, self.root / "other")
        (self.batch / "READY").write_text("a" * 32 + "\n")
        (self.batch / "new-jobs.json").write_bytes(feed.encoded([]))
        with self.assertRaisesRegex(feed.FeedError, "hash/size"):
            feed.prepare(self.batch, self.root / "other")

    def test_duplicate_or_conflicting_source_id_stops_preparation(self):
        source_batch(self.batch, [job(), job(title="Synthetic conflicting title")])
        with self.assertRaisesRegex(feed.FeedError, "Duplicate/conflicting"):
            feed.prepare(self.batch, self.request)
        self.assertFalse(self.request.exists())

    def test_missing_fields_are_held_without_losing_original(self):
        result = self.prepare([job(), job("1000000002", companyName=None)])
        self.assertEqual(result["counts"]["selectedJobs"], 1)
        self.assertEqual(result["counts"]["heldSourceJobs"], 1)
        held = feed.read_json(self.request / "held-source-jobs.json")
        self.assertEqual(held[0]["sourceRow"]["id"], "1000000002")
        self.assertEqual(held[0]["reason"], "missing_companyName")

    def test_bounded_selection_retains_deferred_jobs_and_supports_offset(self):
        result = self.prepare([job(str(1000000001 + i)) for i in range(3)], max_items=1)
        self.assertEqual(result["counts"]["deferredJobs"], 2)
        second = self.root / "request-2"
        feed.prepare(self.batch, second, max_items=1, offset=1)
        self.assertEqual(feed.read_json(second / "verifier-input.json")["rows"][0]["jobId"], "1000000002")

    def test_existing_apply_hint_is_mapped_and_unsafe_hints_omitted(self):
        self.prepare([job(officialApplyUrl="https://careers.synthetic-example.invalid/jobs/1", companyUrl="https://www.linkedin.com/company/synthetic-example", companyWebsite="https://user:secret@careers.synthetic-example.invalid")])
        selected, payload = self.data()
        self.assertEqual(payload["rows"][0]["applyUrl"], "https://careers.synthetic-example.invalid/jobs/1")
        self.assertNotIn("companyWebsite", payload["rows"][0])
        self.assertIn("unsafe_companyWebsite_hint_omitted", selected[0]["warnings"])

    def test_mutated_request_input_does_not_merge(self):
        self.prepare()
        (self.request / "verifier-input.json").write_bytes(feed.encoded({"rows": []}))
        with self.assertRaisesRegex(feed.FeedError, "changed"):
            feed.load_request(self.request)

    def test_different_saved_input_and_dataset_id_are_rejected(self):
        self.prepare()
        _, payload = self.data()
        wrong = copy.deepcopy(payload)
        wrong["rows"][0]["jobTitle"] = "Different synthetic title"
        with self.assertRaisesRegex(feed.FeedError, "different run"):
            self.merge(saved_input=wrong)
        with self.assertRaisesRegex(feed.FeedError, "datasetId"):
            self.merge(saved_input={**payload, "datasetId": "OtherDataset0001"})

    def test_actual_decision_order_is_irrelevant_and_scores_are_preserved(self):
        self.prepare([job(), job("1000000002")])
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected, ["ACTIVE", "LINKEDIN_EASY_APPLY"])
        decisions.reverse()
        result = self.merge(run, decisions, summary)
        records = feed.read_json(self.output / "publishable-jobs.json")
        self.assertEqual([r["id"] for r in records], ["1000000001", "1000000002"])
        self.assertEqual(records[0]["verificationConfidence"], 0.97)
        self.assertEqual(records[0]["descriptionText"], job()["descriptionText"])
        self.assertTrue(records[0]["currentAvailabilityUnknown"])
        self.assertEqual(result["counts"]["publishableJobs"], 2)

    def test_missing_decision_is_held_and_not_inferred_closed(self):
        self.prepare([job(), job("1000000002")])
        selected, _ = self.data()
        run, decisions, _ = exported_run(selected)
        decisions = decisions[:1]
        summary = summary_for(decisions, 2)
        run["chargedEventCounts"]["verified-job"] = 1
        result = self.merge(run, decisions, summary)
        self.assertEqual(result["status"], "HANDOFF_PARTIAL")
        held = feed.read_json(self.output / "held-jobs.json")
        self.assertEqual(held[0]["reason"], "MISSING_VERIFIER_DECISION")
        self.assertIsNone(held[0]["actionUrl"])
        self.assertFalse(result["closureInference"])

    def test_expired_ambiguous_and_review_flags_never_publish(self):
        self.prepare([job(), job("1000000002"), job("1000000003")])
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected, ["EXPIRED", "AMBIGUOUS", "ACTIVE"])
        decisions[2]["reviewRequired"] = True
        result = self.merge(run, decisions, summary)
        self.assertEqual(result["counts"]["publishableJobs"], 0)
        self.assertEqual(result["counts"]["heldJobs"], 3)

    def test_wrong_source_index_id_url_or_content_stops_merge(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        for key, value in (("sourceIndex", True), ("sourceIndex", 9), ("jobId", "999"), ("linkedinUrl", "https://www.linkedin.com/jobs/view/999"), ("title", "Different synthetic title"), ("company", "Different synthetic company")):
            bad = copy.deepcopy(decisions)
            bad[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(feed.FeedError):
                self.merge(run, bad, summary)
        self.assertFalse(self.output.exists())

    def test_duplicate_verifier_decision_stops_merge(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, _ = exported_run(selected)
        duplicated = decisions + copy.deepcopy(decisions)
        with self.assertRaisesRegex(feed.FeedError, "duplicate"):
            self.merge(run, duplicated, summary_for(duplicated, 1))

    def test_exact_boolean_flags_unknown_status_and_nonfinite_scores_are_rejected(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        for key, value in (("safeToPublish", "true"), ("reviewRequired", 0), ("usefulClassification", 1), ("status", "NEW_UNKNOWN_STATUS"), ("confidence", float("nan")), ("confidence", True), ("confidence", 1.1)):
            bad = copy.deepcopy(decisions)
            bad[0][key] = value
            with self.subTest(key=key), self.assertRaises(feed.FeedError):
                self.merge(run, bad, summary)

    def test_decision_before_source_observation_is_held(self):
        self.prepare([job(scrapedAt="2026-09-30T12:01:40Z")])
        result = self.merge()
        self.assertEqual(result["status"], "HANDOFF_PARTIAL")
        held = feed.read_json(self.output / "held-jobs.json")
        self.assertEqual(held[0]["reason"], "VERIFICATION_PREDATES_SOURCE_OBSERVATION")

    def test_verification_must_not_predate_collection_finish_even_with_older_row_scrape(self):
        self.prepare([job(scrapedAt="2026-09-30T10:00:00Z")])
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        run["startedAt"] = "2026-09-30T10:30:00Z"
        run["finishedAt"] = "2026-09-30T11:30:00Z"
        decisions[0]["checkedAt"] = "2026-09-30T11:00:00Z"
        result = self.merge(run, decisions, summary)
        self.assertEqual(result["counts"]["publishableJobs"], 0)
        self.assertEqual(feed.read_json(self.output / "held-jobs.json")[0]["reason"], "VERIFICATION_PREDATES_SOURCE_OBSERVATION")

    def test_decision_outside_actual_verifier_run_time_is_rejected(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        decisions[0]["checkedAt"] = "2026-09-30T13:00:00Z"
        with self.assertRaisesRegex(feed.FeedError, "run window"):
            self.merge(run, decisions, summary)

    def test_unsafe_action_url_and_other_job_easy_apply_are_held(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        for url in ("javascript:alert(1)", "file:///tmp/test", "http://example.invalid", "https://u:secret@example.invalid", "https://127.0.0.1/path", "https://localhost/path", "https://example.invalid:443/path", "https://example.invalid\\@private/path"):
            bad = copy.deepcopy(decisions)
            bad[0]["actionUrl"] = url
            out = self.root / ("held-" + str(abs(hash(url))))
            result = feed.merge(self.request, self.data()[1], run, bad, summary, out, AS_OF)
            self.assertEqual(result["counts"]["publishableJobs"], 0)
            self.assertEqual(feed.read_json(out / "held-jobs.json")[0]["reason"], "UNSAFE_ACTION_URL")
        easy = copy.deepcopy(decisions)
        easy[0].update(status="LINKEDIN_EASY_APPLY", actionUrl="https://www.linkedin.com/jobs/view/999")
        result = self.merge(run, easy, summary)
        self.assertEqual(result["counts"]["publishableJobs"], 0)

    def test_empty_evidence_is_held_not_replaced_with_invented_proof(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        decisions[0]["evidence"] = []
        result = self.merge(run, decisions, summary)
        self.assertEqual(result["counts"]["publishableJobs"], 0)
        self.assertEqual(feed.read_json(self.output / "held-jobs.json")[0]["reason"], "MISSING_VERIFICATION_EVIDENCE")

    def test_failed_run_summary_count_and_charge_conflicts_are_rejected(self):
        self.prepare()
        selected, _ = self.data()
        run, decisions, summary = exported_run(selected)
        with self.assertRaises(feed.FeedError):
            self.merge({**run, "status": "FAILED"}, decisions, summary)
        with self.assertRaises(feed.FeedError):
            self.merge(run, decisions, {**summary, "deliveredRows": 0})
        with self.assertRaisesRegex(feed.FeedError, "event count"):
            self.merge({**run, "chargedEventCounts": {"verified-job": 0}}, decisions, summary)

    def test_json_keeps_source_text_csv_protects_formula_and_no_old_flags_survive(self):
        self.prepare([job(title="\ufeff =SUM(1,2)", officialApplyUrl="https://old.synthetic-example.invalid/old", safeToPublish=True, jobStatus="OLD_HINT")])
        self.merge()
        records = feed.read_json(self.output / "publishable-jobs.json")
        self.assertEqual(records[0]["title"], "\ufeff =SUM(1,2)")
        self.assertNotIn("officialApplyUrl", records[0])
        self.assertNotIn("jobStatus", records[0])
        csv_row = next(csv.DictReader(io.StringIO((self.output / "publishable-jobs.csv").read_text())))
        self.assertTrue(csv_row["title"].startswith("'"))

    def test_artifact_hashes_and_ready_summary_are_exact_and_replay_is_idempotent(self):
        self.prepare()
        result = self.merge()
        for name, expected in result["artifactHashes"].items():
            self.assertEqual(feed.sha((self.output / name).read_bytes()), expected)
        self.assertEqual((self.output / "READY").read_text().strip(), feed.sha((self.output / "handoff-summary.json").read_bytes()))
        self.assertEqual(self.merge(), result)

    def test_source_symlink_and_existing_different_output_are_refused(self):
        self.prepare()
        (self.batch / "new-jobs.csv").unlink()
        (self.batch / "new-jobs.csv").symlink_to(self.request / "manifest.json")
        with self.assertRaises(feed.FeedError):
            feed.prepare(self.batch, self.root / "other")
        self.output.mkdir()
        (self.output / "unrelated.txt").write_text("preserve")
        with self.assertRaisesRegex(feed.FeedError, "overwrite"):
            self.merge()
        self.assertEqual((self.output / "unrelated.txt").read_text(), "preserve")

    def test_saved_input_default_population_is_equivalent_without_altering_rows(self):
        self.prepare()
        _, payload = self.data()
        smaller = {"rows": payload["rows"], "maxItems": payload["maxItems"], "datasetId": ""}
        result = self.merge(saved_input=smaller)
        self.assertEqual(result["counts"]["publishableJobs"], 1)

    def test_saved_input_boolean_integer_aliases_do_not_pass_hash_binding(self):
        self.prepare()
        _, payload = self.data()
        for field, value in (("maxItems", True), ("useReaderFallback", 1), ("maxCandidates", True), ("includeVerificationReport", 0)):
            wrong = copy.deepcopy(payload)
            wrong[field] = value
            with self.subTest(field=field), self.assertRaises(feed.FeedError):
                self.merge(saved_input=wrong)
        self.assertFalse(self.output.exists())

    def test_browser_legacy_loopback_host_spellings_are_rejected_without_dns(self):
        for host in ("0x7f.0.0.1", "127.000.000.001", "127.1", "2130706433", "0x7f000001", "example.0x7f"):
            with self.subTest(host=host):
                self.assertFalse(feed.safe_https("https://" + host + "/apply"))
        self.assertTrue(feed.safe_https("https://8.8.8.8/apply"))

    def test_default_clock_identical_replay_reuses_verified_previous_artifacts(self):
        self.prepare()
        selected, payload = self.data()
        run, decisions, summary = exported_run(selected)
        first = feed.merge(self.request, payload, run, decisions, summary, self.output)
        second = feed.merge(self.request, payload, run, decisions, summary, self.output)
        self.assertEqual(first, second)
        (self.output / "publishable-jobs.csv").write_text("modified export")
        with self.assertRaisesRegex(feed.FeedError, "artifact changed"):
            feed.merge(self.request, payload, run, decisions, summary, self.output)

    def test_bundled_demo_is_self_contained_and_explicitly_synthetic(self):
        demo = Path(__file__).parent / "examples" / "verified-feed-synthetic-demo"
        self.assertTrue(feed.read_json(demo / "source-batch/metadata.json")["exampleIsSynthetic"])
        manifest = feed.prepare(demo / "source-batch", self.request)
        self.assertEqual(manifest["counts"]["selectedJobs"], 3)
        run = feed.read_json(demo / "synthetic-run.json")
        self.assertTrue(run["exampleIsSynthetic"])
        result = feed.merge(self.request, feed.read_json(demo / "synthetic-INPUT.json"), run,
                            feed.read_json(demo / "synthetic-rows.json"), feed.read_json(demo / "synthetic-OUTPUT.json"), self.output, AS_OF)
        self.assertEqual(result["counts"]["publishableJobs"], 2)
        self.assertEqual(result["counts"]["heldJobs"], 1)
        self.assertEqual(feed.read_json(self.output / "held-jobs.json")[0]["reason"], "VERIFIER_EXPIRED")


if __name__ == "__main__":
    unittest.main()
