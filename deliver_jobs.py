#!/usr/bin/env python3
"""Deliver observed new jobs to local JSON/CSV with durable SQLite state (stdlib only)."""
import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parent
FIELDS = tuple(json.loads((ROOT / "dataset.schema.json").read_text())["properties"])
CONTENT_FIELDS = ("title", "companyName", "location", "postedAt", "descriptionText",
                  "descriptionHtml", "employmentType", "seniorityLevel", "salaryText",
                  "officialApplyUrl", "jobStatus", "detailStatus")
API = "https://api.apify.com"


class DeliveryError(Exception):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeliveryError("Cannot read a valid JSON input file.") from exc


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, TypeError):
        raise DeliveryError("Source observation time must be an ISO timestamp with timezone.") from None


def number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise DeliveryError("Invalid numeric source provenance.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise DeliveryError("Invalid numeric source provenance.") from None
    if not math.isfinite(result) or result < 0:
        raise DeliveryError("Invalid numeric source provenance.")
    return result


def normalize_source(run, summary=None, mode="offline_snapshot"):
    if isinstance(run, dict) and isinstance(run.get("data"), dict):
        run = run["data"]
    if not isinstance(run, dict) or run.get("status") != "SUCCEEDED":
        raise DeliveryError("Only a confirmed SUCCEEDED source run can advance seen state.")
    source = {"mode": mode, "platformStatus": "SUCCEEDED"}
    for output, key in (("runId", "id"), ("datasetId", "defaultDatasetId"), ("buildId", "buildId")):
        value = run.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{4,64}", value):
            raise DeliveryError("Missing or invalid run, dataset or build provenance.")
        source[output] = value
    build = run.get("buildNumber")
    if not isinstance(build, str) or not re.fullmatch(r"\d+\.\d+\.\d+", build):
        raise DeliveryError("Missing source build number.")
    source.update(buildNumber=build, observedAt=timestamp(run.get("finishedAt")))
    options = run.get("options") or {}
    if not isinstance(options, dict):
        raise DeliveryError("Invalid source run options.")
    source["maxTotalChargeUsd"] = number(options.get("maxTotalChargeUsd"))
    source["runTimeoutSecs"] = number(options.get("timeoutSecs"))
    source["memoryMbytes"] = number(options.get("memoryMbytes"))
    source["reportedUsageTotalUsd"] = number(run.get("usageTotalUsd"))
    source["datasetItemCount"] = run.get("datasetItemCount")
    if source["datasetItemCount"] is not None and (type(source["datasetItemCount"]) is not int or source["datasetItemCount"] < 0):
        raise DeliveryError("Invalid dataset item count.")
    source["datasetMetadataItemCount"] = run.get("datasetMetadataItemCount")
    source["datasetCountAuthority"] = run.get("datasetCountAuthority")
    summary = summary or {}
    if not isinstance(summary, dict) or str(summary.get("status")) in {"FAILED", "ERROR"}:
        raise DeliveryError("Source OUTPUT reports a failure.")
    if summary.get("searchesRequested", 0) and not summary.get("searchesSucceeded", 0):
        raise DeliveryError("Source OUTPUT contains no successful search.")
    source["output"] = {key: summary[key] for key in (
        "searchesRequested", "searchesSucceeded", "searchesFailed", "jobsFound", "jobsUnique",
        "detailsComplete", "detailsUnavailable", "rowsEmitted") if type(summary.get(key)) is int}
    source["warningCount"] = len(summary["warnings"]) if isinstance(summary.get("warnings"), list) else None
    source["searchCoverage"] = [{"complete": item.get("complete") if type(item.get("complete")) is bool else None,
                                "stopReason": item.get("stopReason") if re.fullmatch(r"[a-z_]{1,60}", str(item.get("stopReason"))) else None}
                               for item in summary.get("searches", []) if isinstance(item, dict)]
    return source


def job_identity(row):
    raw_id = row.get("id")
    job_id = str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
    if job_id and not re.fullmatch(r"\d+", job_id):
        raise DeliveryError("invalid_identity")
    raw_url = row.get("url")
    canonical = None
    url_id = None
    if raw_url:
        if not isinstance(raw_url, str):
            raise DeliveryError("invalid_identity")
        parts = urlsplit(raw_url)
        host = (parts.hostname or "").lower()
        if (parts.scheme not in {"http", "https"} or parts.username or parts.password
                or not (host == "linkedin.com" or host.endswith(".linkedin.com"))
                or not parts.path.startswith("/jobs/view/")):
            raise DeliveryError("invalid_identity")
        path = parts.path.rstrip("/")
        canonical = urlunsplit(("https", "www.linkedin.com", path, "", ""))
        match = re.search(r"(?:/|-)(\d+)$", path)
        url_id = match.group(1) if match else None
    if job_id and url_id and job_id != url_id:
        raise DeliveryError("identity_mismatch")
    if job_id or url_id:
        return "id:" + (job_id or url_id)
    if canonical and canonical.split("/jobs/view/", 1)[1]:
        return "url:" + canonical
    raise DeliveryError("missing_identity")


def select_rows(rows, source):
    if not isinstance(rows, list):
        raise DeliveryError("Dataset snapshot must be a JSON array.")
    expected = source.get("datasetItemCount")
    if expected is not None and len(rows) != expected:
        raise DeliveryError("Dataset download does not match its declared item count.")
    emitted = source.get("output", {}).get("rowsEmitted")
    if emitted is not None and len(rows) != emitted:
        raise DeliveryError("Snapshot does not match the source OUTPUT rowsEmitted count.")
    selected, rejected, conflicted = {}, {}, set()
    duplicates = 0
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise DeliveryError("invalid_record")
            if str(row.get("status", "")).upper() in {"FAILED", "ERROR"}:
                raise DeliveryError("failed_record")
            if set(row) - set(FIELDS):
                raise DeliveryError("unexpected_fields")
            if not isinstance(row.get("title"), str) or not row["title"].strip():
                raise DeliveryError("missing_title")
            if row.get("detailStatus") == "unavailable":
                raise DeliveryError("details_unavailable")
            if row.get("detailStatus") not in {"complete", "not_requested"}:
                raise DeliveryError("invalid_detail_status")
            if row.get("detailStatus") == "complete" and not any(
                    isinstance(row.get(key), str) and row[key].strip() for key in ("descriptionText", "descriptionHtml")):
                raise DeliveryError("empty_complete_description")
            key = job_identity(row)
            observed = timestamp(row.get("scrapedAt") or source["observedAt"])
            fingerprint = digest({field: row.get(field) for field in CONTENT_FIELDS})
            candidate = {"key": key, "observedAt": observed, "fingerprint": fingerprint, "row": row}
            if key in selected:
                duplicates += 1
                previous = selected[key]
                if observed == previous["observedAt"] and fingerprint != previous["fingerprint"]:
                    conflicted.add(key)
                elif observed > previous["observedAt"]:
                    selected[key] = candidate
            else:
                selected[key] = candidate
        except (DeliveryError, ValueError, TypeError):
            reason = str(sys.exc_info()[1]) if isinstance(sys.exc_info()[1], DeliveryError) else "invalid_record"
            if reason not in {"invalid_identity", "identity_mismatch", "missing_identity", "invalid_record",
                              "failed_record", "unexpected_fields", "missing_title", "details_unavailable",
                              "invalid_detail_status", "empty_complete_description"}:
                reason = "invalid_observation"
            rejected[reason] = rejected.get(reason, 0) + 1
    for key in conflicted:
        selected.pop(key, None)
    if conflicted:
        rejected["conflicting_duplicate"] = len(conflicted)
    return sorted(selected.values(), key=lambda item: item["key"]), duplicates, rejected


def csv_cell(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict)) else "" if value is None else str(value)
    if isinstance(value, str) and (text.startswith(("\t", "\r", "\n")) or text.lstrip("\ufeff \t\r\n").startswith(("=", "+", "-", "@"))):
        return "'" + text
    return text


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(FIELDS)
    for row in rows:
        writer.writerow(csv_cell(row.get(field)) for field in FIELDS)
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


@contextmanager
def locked_state(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(str(path) + ".lock", "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        connection = sqlite3.connect(path, isolation_level=None, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS seen (
                watchlist TEXT, identity TEXT, fingerprint TEXT, observed_at TEXT,
                first_batch TEXT, last_batch TEXT, PRIMARY KEY(watchlist, identity));
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, status TEXT, plan TEXT NOT NULL);
        """)
        try:
            yield connection
        finally:
            connection.close()
            fcntl.flock(lock, fcntl.LOCK_UN)


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def artifact_content(plan):
    files = {"new-jobs.json": encoded(plan["newRows"]), "new-jobs.csv": csv_bytes(plan["newRows"]),
             "updated-jobs.json": encoded(plan["updatedRows"]), "updated-jobs.csv": csv_bytes(plan["updatedRows"])}
    metadata = dict(plan["metadata"])
    metadata["artifacts"] = {name: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                             for name, body in files.items()}
    files["metadata.json"] = encoded(metadata)
    return files, metadata


def write_artifacts(plan):
    target = Path(plan["artifactDir"])
    files, metadata = artifact_content(plan)
    if target.exists():
        if not all((target / name).is_file() and (target / name).read_bytes() == body for name, body in files.items()):
            raise DeliveryError("Existing batch artifacts do not match prepared state; refusing overwrite.")
        return metadata
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=target.parent))
    try:
        for name, body in files.items():
            with open(temporary / name, "xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        fsync_dir(temporary)
        os.rename(temporary, target)
        fsync_dir(target.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return metadata


def commit_seen(connection, plan):
    connection.execute("BEGIN IMMEDIATE")
    try:
        for item in plan["observations"]:
            previous = connection.execute("SELECT fingerprint, observed_at FROM seen WHERE watchlist=? AND identity=?",
                                          (plan["watchlist"], item["key"])).fetchone()
            current = dict(previous) if previous else None
            if current != item["previous"]:
                raise DeliveryError("Seen state changed while a batch was prepared; refusing unsafe commit.")
            connection.execute("""INSERT INTO seen VALUES(?,?,?,?,?,?)
                ON CONFLICT(watchlist,identity) DO UPDATE SET fingerprint=excluded.fingerprint,
                observed_at=excluded.observed_at,last_batch=excluded.last_batch""",
                (plan["watchlist"], item["key"], item["fingerprint"], item["observedAt"], plan["batchId"], plan["batchId"]))
        connection.execute("UPDATE batches SET status='committed' WHERE id=?", (plan["batchId"],))
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def mark_ready(connection, plan):
    target = Path(plan["artifactDir"])
    ready = target / "READY"
    if not ready.exists():
        with open(target / ".ready.tmp", "wb") as handle:
            handle.write((plan["batchId"] + "\n").encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(target / ".ready.tmp", ready)
        fsync_dir(target)
    connection.execute("UPDATE batches SET status='ready' WHERE id=?", (plan["batchId"],))


def recover_batches(connection):
    recovered = []
    for record in connection.execute("SELECT * FROM batches WHERE status!='ready' ORDER BY rowid").fetchall():
        plan = json.loads(record["plan"])
        metadata = write_artifacts(plan)
        if record["status"] == "prepared":
            commit_seen(connection, plan)
        mark_ready(connection, plan)
        recovered.append((plan, metadata))
    return recovered


def process_dataset(rows, source, watchlist, state, output_dir, include_updates=False):
    if not isinstance(source, dict) or source.get("platformStatus") != "SUCCEEDED":
        raise DeliveryError("Only a confirmed successful source can advance seen state.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", watchlist):
        raise DeliveryError("Watchlist must be a short label containing letters, numbers, dots, underscores or hyphens.")
    candidates, duplicates, rejected = select_rows(rows, source)
    source_hash = digest({"rows": rows, "source": source, "watchlist": watchlist, "includeUpdates": include_updates})
    with locked_state(state) as connection:
        recovered = recover_batches(connection)
        for old, metadata in recovered:
            if old["sourceHash"] == source_hash:
                return {"metadata": metadata, "artifactDir": old["artifactDir"], "recovered": True}
        batch_id = uuid.uuid4().hex
        new_rows, changed_rows, observations = [], [], []
        unchanged = stale = 0
        for item in candidates:
            previous = connection.execute("SELECT fingerprint, observed_at FROM seen WHERE watchlist=? AND identity=?",
                                          (watchlist, item["key"])).fetchone()
            previous = dict(previous) if previous else None
            if previous and (item["observedAt"] < previous["observed_at"] or
                             item["observedAt"] == previous["observed_at"] and item["fingerprint"] != previous["fingerprint"]):
                stale += 1
                continue
            if previous is None:
                new_rows.append(item["row"])
            elif previous["fingerprint"] != item["fingerprint"]:
                changed_rows.append(item["row"])
            else:
                unchanged += 1
            observations.append({key: item[key] for key in ("key", "observedAt", "fingerprint")} | {"previous": previous})
        metadata = {"formatVersion": 1, "batchId": batch_id, "createdAt": datetime.now(timezone.utc).isoformat(),
                    "watchlist": watchlist, "source": source, "sourceRowsSha256": digest(rows),
                    "counts": {"inputRows": len(rows), "acceptedUniqueRows": len(candidates),
                               "duplicateRows": duplicates, "rejectedReasons": rejected,
                               "newJobs": len(new_rows), "changedJobsObserved": len(changed_rows),
                               "updatedJobsExported": len(changed_rows) if include_updates else 0,
                               "unchangedJobs": unchanged, "staleObservations": stale},
                    "updatesEnabled": include_updates, "csvFormulaProtection": "apostrophe prefix for dangerous text cells",
                    "closureInference": False, "ownerRunIsCustomerRevenue": False}
        plan = {"batchId": batch_id, "sourceHash": source_hash, "watchlist": watchlist,
                "artifactDir": str(Path(output_dir).resolve() / ("batch-" + batch_id)),
                "observations": observations, "newRows": new_rows,
                "updatedRows": changed_rows if include_updates else [], "metadata": metadata}
        connection.execute("INSERT INTO batches VALUES(?, 'prepared', ?)", (batch_id, encoded(plan).decode("utf-8")))
        metadata = write_artifacts(plan)
        commit_seen(connection, plan)
        mark_ready(connection, plan)
        return {"metadata": metadata, "artifactDir": plan["artifactDir"], "recovered": False,
                "recoveredBatchIds": [old["batchId"] for old, _ in recovered]}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeliveryError("Refusing an API redirect; authorization is confined to api.apify.com.")


class ApifyAPI:
    def __init__(self, token, opener=None):
        if not token or "\n" in token or "\r" in token:
            raise DeliveryError("Set APIFY_TOKEN in the environment.")
        self.token = token
        self.opener = opener or build_opener(NoRedirects())

    def request(self, method, path, payload=None, params=None):
        if not re.fullmatch(r"/v2/[A-Za-z0-9_~./-]+", path):
            raise DeliveryError("Invalid internal API path.")
        if params and any(re.search(r"token|credential|authorization|api.?key", key, re.I) for key in params):
            raise DeliveryError("Credentials are not permitted in API URL parameters.")
        url = API + path + ("?" + urlencode(params) if params else "")
        request = Request(url, data=encoded(payload) if payload is not None else None, method=method,
                          headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(request, timeout=20) as response:
                    if urlsplit(response.url).hostname != "api.apify.com":
                        raise DeliveryError("Refusing a non-official API response.")
                    body = response.read(64 * 1024 * 1024 + 1)
                    if len(body) > 64 * 1024 * 1024:
                        raise DeliveryError("API response exceeded the local size limit.")
                    return json.loads(body)
            except HTTPError as error:
                retry = error.code in {429, 500, 502, 503, 504}
                if attempt + 1 < attempts and retry:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                message = f"Apify API returned HTTP {error.code}; response body withheld."
                if method == "POST":
                    message += " Check Console before starting another run."
                raise DeliveryError(message) from None
            except (URLError, ValueError, OSError):
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                message = "API request failed; private request details withheld."
                if method == "POST":
                    message += " Run creation may be uncertain; check Console before starting again."
                raise DeliveryError(message) from None


def read_consistent_page(api, dataset_id, offset, limit, expected_count):
    for attempt in range(3):
        page = api.request("GET", "/v2/datasets/" + dataset_id + "/items",
                           params={"format": "json", "clean": "false", "offset": offset, "limit": limit})
        if not isinstance(page, list):
            raise DeliveryError("Dataset API returned no JSON array; no seen state was advanced.")
        if len(page) == expected_count:
            return page
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    raise DeliveryError("Dataset pages do not match OUTPUT.rowsEmitted after bounded GET retries; no seen state was advanced.")


def completed_snapshot(api, run, mode):
    # Check run provenance before requesting its storage. OUTPUT, not eventually
    # consistent dataset metadata, supplies the expected exported-row count.
    normalize_source(run)
    run = dict(run)
    dataset_id = run["defaultDatasetId"]
    store_id = run.get("defaultKeyValueStoreId")
    if not isinstance(store_id, str) or not re.fullmatch(r"[A-Za-z0-9]{4,64}", store_id):
        raise DeliveryError("A completed Jobs run with an OUTPUT store is required.")
    summary = api.request("GET", "/v2/key-value-stores/" + store_id + "/records/OUTPUT")
    expected = summary.get("rowsEmitted") if isinstance(summary, dict) else None
    if type(expected) is not int or not 0 <= expected <= 10000:
        raise DeliveryError("OUTPUT.rowsEmitted must be an integer from 0 to 10,000.")
    normalize_source(run, summary, mode)
    metadata = api.request("GET", "/v2/datasets/" + dataset_id)["data"]
    metadata_count = metadata.get("itemCount") if isinstance(metadata, dict) else None
    if metadata_count is not None and (type(metadata_count) is not int or metadata_count < 0):
        raise DeliveryError("Invalid informational dataset metadata count.")
    rows = []
    while len(rows) < expected:
        size = min(1000, expected - len(rows))
        rows.extend(read_consistent_page(api, dataset_id, len(rows), size, size))
    # Includes the expected-zero case and prevents accepting extra undeclared rows.
    read_consistent_page(api, dataset_id, expected, 1, 0)
    run["datasetItemCount"] = len(rows)
    run["datasetMetadataItemCount"] = metadata_count
    run["datasetCountAuthority"] = "OUTPUT.rowsEmitted; actual pages checked"
    return rows, normalize_source(run, summary, mode)


def existing_run_snapshot(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9]{4,64}", run_id):
        raise DeliveryError("Invalid existing run ID.")
    api = ApifyAPI(os.environ.get("APIFY_TOKEN"))
    run = api.request("GET", "/v2/actor-runs/" + run_id)["data"]
    if run.get("id") != run_id:
        raise DeliveryError("Existing run response did not match the requested run ID.")
    return completed_snapshot(api, run, "existing_cloud_run")


def live_snapshot(input_path, max_charge, timeout_secs, build):
    api = ApifyAPI(os.environ.get("APIFY_TOKEN"))
    run_input = load_json(input_path)
    if not isinstance(run_input, dict) or run_input.get("verifyApplyLinks"):
        raise DeliveryError("This bounded feed example excludes separately billed apply-link verification.")
    if run_input.get("newJobsOnly"):
        raise DeliveryError("Use newJobsOnly=false so this consumer owns incremental history.")
    started = api.request("POST", "/v2/actors/kamerozkan~linkedin-jobs-scraper/runs", run_input,
                          {"build": build, "memory": 512, "timeout": timeout_secs, "maxTotalChargeUsd": max_charge})
    run = started["data"]
    run_id = run.get("id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9]{4,64}", run_id):
        raise DeliveryError("Run creation returned no usable ID; check Console before starting again.")
    print("Started Apify run " + run_id, file=sys.stderr)
    deadline = time.monotonic() + timeout_secs + 60
    while run.get("status") not in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
        if time.monotonic() >= deadline:
            raise DeliveryError("Run polling deadline reached; the server timeout and charge limit still apply. Inspect Console.")
        time.sleep(2)
        run = api.request("GET", "/v2/actor-runs/" + run_id)["data"]
    if run.get("status") != "SUCCEEDED":
        raise DeliveryError("Cloud run did not succeed; no seen state was advanced.")
    rows, source = completed_snapshot(api, run, "live_api")
    # Retain actual returned limits, rather than substituting requested limits.
    if source["maxTotalChargeUsd"] != max_charge or source["runTimeoutSecs"] != timeout_secs:
        raise DeliveryError("Returned run options do not confirm the requested spending/time limits.")
    return rows, source


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dataset-file", type=Path)
    mode.add_argument("--live-input", type=Path, help="Explicitly starts one billable cloud run")
    mode.add_argument("--run-id", help="Read an existing completed cloud run with GET only; never starts a run")
    parser.add_argument("--run-file", type=Path)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--state", type=Path, default=Path(".delivery/seen.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path(".delivery/batches"))
    parser.add_argument("--include-updates", action="store_true")
    parser.add_argument("--max-total-charge-usd", type=float, default=0.05)
    parser.add_argument("--timeout-secs", type=int, default=300)
    parser.add_argument("--build", default=os.environ.get("APIFY_BUILD", "latest"))
    args = parser.parse_args(argv)
    try:
        if args.dataset_file:
            if not args.run_file:
                raise DeliveryError("Offline mode requires --run-file for genuine source provenance.")
            source = normalize_source(load_json(args.run_file), load_json(args.output_file) if args.output_file else None)
            rows = load_json(args.dataset_file)
        elif args.run_id:
            if args.run_file or args.output_file:
                raise DeliveryError("Run/output files are only used in offline mode.")
            rows, source = existing_run_snapshot(args.run_id)
        else:
            if args.run_file or args.output_file:
                raise DeliveryError("Run/output files are only used in offline mode.")
            if number(args.max_total_charge_usd) == 0 or not 10 <= args.timeout_secs <= 600:
                raise DeliveryError("Live mode requires a positive charge cap and 10-600 second timeout.")
            rows, source = live_snapshot(args.live_input, args.max_total_charge_usd, args.timeout_secs, args.build)
        result = process_dataset(rows, source, args.watchlist, args.state, args.output_dir, args.include_updates)
        print(json.dumps({"batchId": result["metadata"]["batchId"], "artifactDir": result["artifactDir"],
                          "counts": result["metadata"]["counts"], "source": result["metadata"]["source"],
                          "recovered": result["recovered"], "recoveredBatchIds": result.get("recoveredBatchIds", [])}))
        return 0
    except Exception:
        # Never emit a traceback, upstream body, environment value or private input.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeliveryError) else "Delivery failed; seen state is recoverable. Private details withheld.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; retry the same snapshot to recover any prepared batch.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
