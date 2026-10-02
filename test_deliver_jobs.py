"""Synthetic failure/identity fixtures; these are not live job or coverage evidence."""
import copy
import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import deliver_jobs as delivery


def run_info(run_id="TestRun0001", observed="2026-09-30T12:00:00Z"):
    return {"id": run_id, "status": "SUCCEEDED", "defaultDatasetId": "TestDataset0001",
            "buildId": "TestBuild0001", "buildNumber": "0.1.3", "finishedAt": observed,
            "options": {"maxTotalChargeUsd": 0.05, "timeoutSecs": 300, "memoryMbytes": 512},
            "usageTotalUsd": 0.0001}


def job(job_id="1000000001", observed="2026-09-30T12:00:00Z", **changes):
    row = {"id": job_id, "url": "https://www.linkedin.com/jobs/view/" + job_id,
           "title": "Synthetic test role", "companyName": "Synthetic test company",
           "descriptionText": "Synthetic description for transaction tests.",
           "detailStatus": "complete", "scrapedAt": observed}
    row.update(changes)
    return row


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = Path(__file__).parent / ".test-tmp"
        temporary_parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_parent)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state.sqlite"
        self.output = self.root / "batches"
        self.source = delivery.normalize_source(run_info())

    def tearDown(self):
        self.temporary.cleanup()

    def process(self, rows, source=None, updates=False, watchlist="test-watchlist"):
        return delivery.process_dataset(rows, source or self.source, watchlist, self.state, self.output, updates)

    def seen_count(self):
        with sqlite3.connect(self.state) as connection:
            return connection.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

    def test_first_delivery_replay_and_source_build_are_exact(self):
        rows = [job(), job("1000000002")]
        first = self.process(rows)
        target = Path(first["artifactDir"])
        self.assertEqual(first["metadata"]["counts"]["newJobs"], 2)
        self.assertEqual(json.loads((target / "new-jobs.json").read_text()), rows)
        self.assertTrue((target / "READY").exists())
        second_source = delivery.normalize_source(run_info("TestRun0002", "2026-09-30T13:00:00Z"))
        second_source["buildNumber"] = "0.1.4"
        second = self.process(rows, second_source)
        replay = self.process(rows)
        self.assertEqual(second["metadata"]["counts"]["newJobs"], 0)
        self.assertEqual(replay["metadata"]["counts"]["newJobs"], 0)
        self.assertEqual(second["metadata"]["source"]["buildNumber"], "0.1.4")
        self.assertNotEqual(first["artifactDir"], second["artifactDir"])
        self.assertEqual(self.seen_count(), 2)

    def test_id_url_aliases_and_duplicate_rows_only_deliver_once(self):
        row = job()
        alias = copy.deepcopy(row)
        alias.pop("id")
        alias["url"] += "?trackingId=irrelevant#details"
        result = self.process([row, alias, row])
        self.assertEqual(result["metadata"]["counts"]["newJobs"], 1)
        self.assertEqual(result["metadata"]["counts"]["duplicateRows"], 2)
        self.assertEqual(self.seen_count(), 1)

    def test_new_second_job_is_delivered_but_absence_never_closes_first(self):
        self.process([job()])
        result = self.process([job("1000000002")])
        self.assertEqual(result["metadata"]["counts"]["newJobs"], 1)
        self.assertEqual(self.seen_count(), 2)
        self.assertFalse(result["metadata"]["closureInference"])

    def test_optional_updates_and_old_snapshot_do_not_reverse_current_content(self):
        initial = job()
        changed = job(observed="2026-09-30T13:00:00Z", title="Synthetic changed role")
        later_source = delivery.normalize_source(run_info("TestRun0002", "2026-09-30T13:00:00Z"))
        self.process([initial], updates=True)
        result = self.process([changed], later_source, updates=True)
        self.assertEqual(result["metadata"]["counts"]["newJobs"], 0)
        self.assertEqual(result["metadata"]["counts"]["updatedJobsExported"], 1)
        self.assertEqual(json.loads((Path(result["artifactDir"]) / "updated-jobs.json").read_text()), [changed])
        stale = self.process([initial], updates=True)
        self.assertEqual(stale["metadata"]["counts"]["staleObservations"], 1)
        self.assertEqual(stale["metadata"]["counts"]["updatedJobsExported"], 0)
        self.assertEqual(self.process([changed], later_source, updates=True)["metadata"]["counts"]["updatedJobsExported"], 0)

    def test_volatile_source_fields_do_not_create_updates(self):
        row = job(applicantsCount=1, isNew=True, firstSeenAt="2026-09-30T12:00:00Z")
        self.process([row], updates=True)
        later = dict(row, applicantsCount=9, isNew=False, firstSeenAt="2026-09-30T13:00:00Z",
                     scrapedAt="2026-09-30T13:00:00Z", postedText="2 days ago")
        later_source = delivery.normalize_source(run_info("TestRun0002", "2026-09-30T13:00:00Z"))
        result = self.process([later], later_source, updates=True)
        self.assertEqual(result["metadata"]["counts"]["changedJobsObserved"], 0)

    def test_future_observation_does_not_poison_seen_or_hide_later_valid_delivery(self):
        future = self.process([job(observed="2030-01-01T00:00:00Z")])
        self.assertEqual(future["metadata"]["counts"]["newJobs"], 0)
        self.assertEqual(future["metadata"]["counts"]["rejectedReasons"], {"observation_after_source_finish": 1})
        self.assertEqual(self.seen_count(), 0)
        later_source = delivery.normalize_source(run_info("TestRun0002", "2026-09-30T13:00:00Z"))
        legitimate = self.process([job(observed="2026-09-30T13:00:00Z")], later_source)
        self.assertEqual(legitimate["metadata"]["counts"]["newJobs"], 1)
        self.assertEqual(legitimate["metadata"]["counts"]["staleObservations"], 0)

    def test_source_clock_tolerance_is_bounded_and_existing_seen_cannot_jump_forward(self):
        self.assertEqual(self.process([job(observed="2026-09-30T12:00:05Z")])["metadata"]["counts"]["newJobs"], 1)
        rejected = self.process([job(observed="2026-09-30T12:00:06Z", title="Synthetic future content")], updates=True)
        self.assertEqual(rejected["metadata"]["counts"]["updatedJobsExported"], 0)
        self.assertEqual(rejected["metadata"]["counts"]["rejectedReasons"], {"observation_after_source_finish": 1})
        later_source = delivery.normalize_source(run_info("TestRun0002", "2026-09-30T12:01:00Z"))
        updated = self.process([job(observed="2026-09-30T12:01:00Z", title="Synthetic valid updated content")], later_source, updates=True)
        self.assertEqual(updated["metadata"]["counts"]["updatedJobsExported"], 1)

    def test_present_malformed_job_route_cannot_hide_behind_numeric_id(self):
        for url in ("https://www.linkedin.com/jobs/view/not-a-job", "https://www.linkedin.com/jobs/view/role-1000000001/extra", "https://www.linkedin.com:65535/jobs/view/1000000001", "https://www.linkedin.com/jobs/view/role\\-1000000001"):
            with self.subTest(url=url):
                result = self.process([job(url=url)])
                self.assertEqual(result["metadata"]["counts"]["newJobs"], 0)
                self.assertEqual(result["metadata"]["counts"]["rejectedReasons"], {"invalid_identity": 1})
                self.assertEqual(self.seen_count(), 0)
        valid = self.process([job(url="https://www.linkedin.com/jobs/view/synthetic-role-1000000001/?trackingId=synthetic#details")])
        self.assertEqual(valid["metadata"]["counts"]["newJobs"], 1)

    def test_csv_formula_protection_does_not_change_original_json(self):
        row = job(title=' =HYPERLINK("https://example.invalid","click")', companyName="\t=cmd()",
                  salaryText="\ufeff+1+1", location="@danger", descriptionText="-danger\nmore")
        result = self.process([row])
        target = Path(result["artifactDir"])
        csv_row = next(csv.DictReader(io.StringIO((target / "new-jobs.csv").read_text(encoding="utf-8-sig"))))
        for field in ("title", "companyName", "salaryText", "location", "descriptionText"):
            self.assertTrue(csv_row[field].startswith("'"), field)
        self.assertEqual(json.loads((target / "new-jobs.json").read_text()), [row])

    def test_empty_unavailable_and_conflicting_rows_do_not_poison_seen(self):
        empty = self.process([])
        self.assertEqual(empty["metadata"]["counts"]["newJobs"], 0)
        unavailable = self.process([job(detailStatus="unavailable", descriptionText=None)])
        self.assertEqual(unavailable["metadata"]["counts"]["newJobs"], 0)
        conflicting = self.process([job(), job(title="Contradictory same-time synthetic row")])
        self.assertIn("conflicting_duplicate", conflicting["metadata"]["counts"]["rejectedReasons"])
        self.assertEqual(self.seen_count(), 0)
        self.assertEqual(self.process([job()])["metadata"]["counts"]["newJobs"], 1)

    def test_failed_or_truncated_source_cannot_advance_state(self):
        with self.assertRaises(delivery.DeliveryError):
            delivery.normalize_source(dict(run_info(), status="FAILED"))
        with self.assertRaises(delivery.DeliveryError):
            delivery.normalize_source(run_info(), {"searchesRequested": 1, "searchesSucceeded": 0})
        source = delivery.normalize_source(run_info(), {"rowsEmitted": 2})
        with self.assertRaises(delivery.DeliveryError):
            self.process([job()], source)
        self.assertFalse(self.state.exists())

    def test_export_failure_is_recovered_under_same_stable_batch_id(self):
        with patch.object(delivery, "write_artifacts", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.process([job()])
        self.assertEqual(self.seen_count(), 0)
        with sqlite3.connect(self.state) as connection:
            batch_id = connection.execute("SELECT id FROM batches").fetchone()[0]
        recovered = self.process([job()])
        self.assertTrue(recovered["recovered"])
        self.assertEqual(recovered["metadata"]["batchId"], batch_id)
        self.assertEqual(self.seen_count(), 1)

    def test_crash_after_files_before_state_commit_does_not_lose_delivery(self):
        with patch.object(delivery, "commit_seen", side_effect=OSError("synthetic commit failure")):
            with self.assertRaises(OSError):
                self.process([job()])
        target = next(self.output.glob("batch-*"))
        self.assertFalse((target / "READY").exists())
        self.assertEqual(self.seen_count(), 0)
        before = (target / "new-jobs.json").read_bytes()
        result = self.process([job()])
        self.assertEqual(result["artifactDir"], str(target))
        self.assertEqual((target / "new-jobs.json").read_bytes(), before)
        self.assertTrue((target / "READY").exists())

    def test_crash_after_commit_before_ready_marker_recovers_delivery(self):
        with patch.object(delivery, "mark_ready", side_effect=OSError("synthetic readiness failure")):
            with self.assertRaises(OSError):
                self.process([job()])
        self.assertEqual(self.seen_count(), 1)
        target = next(self.output.glob("batch-*"))
        self.assertFalse((target / "READY").exists())
        recovered = self.process([job()])
        self.assertTrue(recovered["recovered"])
        self.assertTrue((target / "READY").exists())
        self.assertEqual(self.seen_count(), 1)

    def test_tampered_prepared_export_blocks_commit_instead_of_poisoning_seen(self):
        with patch.object(delivery, "commit_seen", side_effect=OSError("synthetic commit failure")):
            with self.assertRaises(OSError):
                self.process([job()])
        target = next(self.output.glob("batch-*"))
        (target / "new-jobs.json").write_text("[]")
        with self.assertRaises(delivery.DeliveryError):
            self.process([job()])
        self.assertEqual(self.seen_count(), 0)

    def test_same_bytes_symlink_export_blocks_recovery_before_seen_commit(self):
        with patch.object(delivery, "commit_seen", side_effect=OSError("synthetic commit failure")):
            with self.assertRaises(OSError):
                self.process([job()])
        target = next(self.output.glob("batch-*"))
        original = (target / "new-jobs.json").read_bytes()
        alternate = self.root / "same-bytes.json"
        alternate.write_bytes(original)
        (target / "new-jobs.json").unlink()
        (target / "new-jobs.json").symlink_to(alternate)
        with self.assertRaisesRegex(delivery.DeliveryError, "artifacts"):
            self.process([job()])
        self.assertEqual(self.seen_count(), 0)
        self.assertFalse((target / "READY").exists())
        (target / "new-jobs.json").unlink()
        (target / "new-jobs.json").write_bytes(original)
        self.assertTrue(self.process([job()])["recovered"])
        self.assertEqual(self.seen_count(), 1)

    def test_corrupt_ready_marker_cannot_complete_recovery_and_can_be_repaired(self):
        with patch.object(delivery, "mark_ready", side_effect=OSError("synthetic readiness failure")):
            with self.assertRaises(OSError):
                self.process([job()])
        target = next(self.output.glob("batch-*"))
        (target / "READY").write_text("different-synthetic-batch\n")
        with self.assertRaisesRegex(delivery.DeliveryError, "false readiness"):
            self.process([job()])
        with sqlite3.connect(self.state) as connection:
            self.assertEqual(connection.execute("SELECT status FROM batches").fetchone()[0], "committed")
        (target / "READY").unlink()
        self.assertTrue(self.process([job()])["recovered"])
        self.assertEqual(self.seen_count(), 1)

    def test_watchlists_have_independent_history(self):
        self.process([job()])
        second = self.process([job()], watchlist="other-watchlist")
        self.assertEqual(second["metadata"]["counts"]["newJobs"], 1)


class FakeResponse:
    url = "https://api.apify.com/v2/test"

    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def read(self, limit):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class APITests(unittest.TestCase):
    def test_authorization_header_only_and_get_retry_but_no_creation_retry(self):
        requests = []

        class FakeOpener:
            def open(self, request, timeout):
                requests.append(request)
                if len(requests) < 3:
                    raise HTTPError(request.full_url, 503, "synthetic error", {}, None)
                return FakeResponse({"data": {}})

        api = delivery.ApifyAPI("SYNTHETIC_TOKEN_SECRET", FakeOpener())
        with patch.object(delivery.time, "sleep"):
            api.request("GET", "/v2/actor-runs/TestRun0001")
        self.assertEqual(len(requests), 3)
        self.assertTrue(all("SYNTHETIC_TOKEN_SECRET" not in request.full_url for request in requests))
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer SYNTHETIC_TOKEN_SECRET")
        requests.clear()
        with self.assertRaises(delivery.DeliveryError):
            api.request("POST", "/v2/actors/kamerozkan~linkedin-jobs-scraper/runs", {})
        self.assertEqual(len(requests), 1)
        with self.assertRaises(delivery.DeliveryError):
            api.request("GET", "/v2/test", params={"token": "forbidden"})

    def test_redirect_does_not_forward_authorization(self):
        with self.assertRaises(delivery.DeliveryError):
            delivery.NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://example.invalid")

    def test_live_mode_requests_real_caps_and_preserves_returned_provenance_without_network(self):
        calls = []
        run = run_info()
        run["options"]["timeoutSecs"] = 20
        run["defaultKeyValueStoreId"] = "TestStore0001"

        def fake_request(api, method, path, payload=None, params=None):
            calls.append((method, path, payload, params))
            if method == "POST":
                return {"data": run}
            if path.endswith("/items"):
                return [job(), {}] if params["offset"] == 0 else []
            if path.endswith("/OUTPUT"):
                return {"rowsEmitted": 2, "searchesRequested": 1, "searchesSucceeded": 1,
                        "searches": [{"complete": False, "stopReason": "limit_reached"}], "warnings": []}
            return {"data": {"itemCount": 0}}

        with patch.object(delivery.ApifyAPI, "request", fake_request), patch.dict(os.environ, {"APIFY_TOKEN": "SYNTHETIC_TOKEN_SECRET"}):
            rows, source = delivery.live_snapshot(Path(__file__).parent / "input.sample.json", 0.05, 20, "0.1.3")
        self.assertEqual(calls[0][3]["maxTotalChargeUsd"], 0.05)
        self.assertEqual(calls[0][3]["timeout"], 20)
        self.assertEqual(calls[0][3]["memory"], 512)
        self.assertEqual(calls[0][1], "/v2/actors/kamerozkan~linkedin-jobs-scraper/runs")
        self.assertEqual(next(call for call in calls if call[1].endswith("/items"))[3]["clean"], "false")
        self.assertEqual(source["datasetItemCount"], 2)
        self.assertEqual(source["datasetMetadataItemCount"], 0)
        self.assertEqual(source["buildNumber"], "0.1.3")
        self.assertFalse(source["searchCoverage"][0]["complete"])
        self.assertEqual(len(rows), 2)
        self.assertNotIn("SYNTHETIC_TOKEN_SECRET", json.dumps(source))

    def test_existing_run_get_only_output_ten_metadata_zero_recovers_short_first_page(self):
        calls, page_attempts = [], []
        run = run_info("TestRun0002")
        run.update(buildNumber="0.1.4", defaultKeyValueStoreId="TestStore0001")
        rows = [job(str(1000000000 + index)) for index in range(10)]

        def fake_request(api, method, path, payload=None, params=None):
            calls.append((method, path))
            self.assertEqual(method, "GET")
            if path.startswith("/v2/actor-runs/"):
                return {"data": run}
            if path.endswith("/OUTPUT"):
                return {"rowsEmitted": 10, "searchesRequested": 1, "searchesSucceeded": 1,
                        "searches": [{"complete": False, "stopReason": "limit_reached"}]}
            if path.endswith("/items"):
                if params["offset"] == 10:
                    return []
                page_attempts.append(1)
                return [] if len(page_attempts) == 1 else rows
            return {"data": {"itemCount": 0}}

        with patch.object(delivery.ApifyAPI, "request", fake_request), patch.object(delivery.time, "sleep"), \
                patch.dict(os.environ, {"APIFY_TOKEN": "SYNTHETIC_TOKEN_SECRET"}):
            observed, source = delivery.existing_run_snapshot("TestRun0002")
        self.assertEqual(observed, rows)
        self.assertEqual(source["datasetItemCount"], 10)
        self.assertEqual(source["datasetMetadataItemCount"], 0)
        self.assertEqual(source["mode"], "existing_cloud_run")
        self.assertEqual(source["buildNumber"], "0.1.4")
        self.assertEqual(source["maxTotalChargeUsd"], 0.05)
        self.assertEqual(len(page_attempts), 2)
        output_index = next(index for index, call in enumerate(calls) if call[1].endswith("/OUTPUT"))
        metadata_index = next(index for index, call in enumerate(calls) if call[1] == "/v2/datasets/TestDataset0001")
        self.assertLess(output_index, metadata_index)

    def test_short_pages_exhaust_retries_without_creating_or_poisoning_state(self):
        run = dict(run_info(), defaultKeyValueStoreId="TestStore0001")
        page_attempts = []

        def fake_request(api, method, path, payload=None, params=None):
            self.assertEqual(method, "GET")
            if path.startswith("/v2/actor-runs/"):
                return {"data": run}
            if path.endswith("/OUTPUT"):
                return {"rowsEmitted": 10, "searchesRequested": 1, "searchesSucceeded": 1}
            if path.endswith("/items"):
                page_attempts.append(1)
                return [job(str(1000000000 + index)) for index in range(9)]
            return {"data": {"itemCount": 0}}

        parent = Path(__file__).parent / ".test-tmp"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            state = Path(directory) / "state.sqlite"
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(delivery.ApifyAPI, "request", fake_request), patch.object(delivery.time, "sleep"), \
                    patch.dict(os.environ, {"APIFY_TOKEN": "SYNTHETIC_TOKEN_SECRET"}), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                code = delivery.main(["--run-id", "TestRun0001", "--watchlist", "test",
                                      "--state", str(state), "--output-dir", str(Path(directory) / "batches")])
            self.assertEqual(code, 1)
            self.assertEqual(len(page_attempts), 3)
            self.assertFalse(state.exists())
            self.assertNotIn("SYNTHETIC_TOKEN_SECRET", stdout.getvalue() + stderr.getvalue())
            self.assertIn("no seen state was advanced", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
