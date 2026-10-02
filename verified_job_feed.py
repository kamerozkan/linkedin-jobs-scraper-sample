#!/usr/bin/env python3
"""Prepare an existing new-job batch, then join saved verifier decisions offline.

No HTTP, token, Actor run, schedule or external publication is implemented.
"""
import argparse
import csv
import hashlib
import io
import ipaddress
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

MAX_FILE_BYTES = 50_000_000
MAX_SOURCE_ROWS = 10_000
PUBLISHABLE = {"ACTIVE", "AUTHORIZED_APPLY_ROUTE", "LINKEDIN_EASY_APPLY"}
USEFUL = PUBLISHABLE | {"EXPIRED", "SOURCE_MISMATCH", "STATUS_CONFLICT"}
DIAGNOSTIC = {"AMBIGUOUS", "INVALID_INPUT", "DUPLICATE_INPUT"}
SOURCE_ARTIFACTS = {"new-jobs.json", "new-jobs.csv", "updated-jobs.json", "updated-jobs.csv"}
SETTINGS = {"autoDiscoverCompanyWebsite": True, "useReaderFallback": True,
            "maxSearchQueries": 1, "maxCandidates": 1, "maxBridgePages": 0,
            "includeVerificationReport": False}


class FeedError(Exception):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(encoded(value))


def read_bytes(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise FeedError("Expected a regular local file, not a symlink.")
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise FeedError("A local input file exceeds the 50 MB limit.")
    return raw


def read_json(path):
    try:
        return json.loads(read_bytes(path), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (OSError, ValueError, UnicodeError):
        raise FeedError("Cannot read a valid bounded JSON input file.") from None


def when(value, label="timestamp"):
    try:
        if not isinstance(value, str):
            raise ValueError()
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise FeedError(label + " must be an ISO timestamp with timezone.") from None


def norm(value):
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def plain(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 10_000 and not any(ord(c) < 32 and c not in "\t\r\n" for c in value)


def safe_https(value):
    if not isinstance(value, str) or len(value) > 4096 or re.search(r"[\x00-\x20\x7f\\]", value):
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme != "https" or url.username or url.password or url.port or not host:
            return False
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host) or any(not label or label.startswith("-") or label.endswith("-") for label in host.split(".")):
                return False
            # Browsers can interpret legacy hex/octal/short numeric hosts as IPv4.
            # A final numeric label is not accepted unless ipaddress parsed a
            # canonical global address above. No DNS or URL is requested here.
            if re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", host.split(".")[-1], re.I):
                return False
        return True
    except ValueError:
        return False


def linkedin_id(value):
    if not isinstance(value, str) or not safe_https(value):
        return None
    url = urlsplit(value)
    host = (url.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    match = re.fullmatch(r"/jobs/view/(?:[^/]*-)?(\d{1,24})/?", url.path)
    return match.group(1) if match else None


def source_identity(row):
    raw = row.get("id")
    job_id = str(raw).strip() if isinstance(raw, (str, int)) and not isinstance(raw, bool) else None
    if job_id and not re.fullmatch(r"\d{1,24}", job_id):
        raise FeedError("Source job identity is invalid.")
    url_id = linkedin_id(row.get("url"))
    if row.get("url") and not url_id:
        raise FeedError("Source job URL is invalid.")
    if job_id and url_id and job_id != url_id:
        raise FeedError("Source ID and URL disagree.")
    job_id = job_id or url_id
    if not job_id:
        raise FeedError("Source job identity is missing.")
    return job_id


def load_source_batch(directory):
    directory = Path(directory)
    metadata_raw = read_bytes(directory / "metadata.json")
    metadata = read_json(directory / "metadata.json")
    if not isinstance(metadata, dict) or metadata.get("formatVersion") != 1:
        raise FeedError("Unsupported delivery batch metadata.")
    batch_id = metadata.get("batchId")
    if not isinstance(batch_id, str) or not re.fullmatch(r"[a-f0-9]{32}", batch_id) or read_bytes(directory / "READY").decode("ascii").strip() != batch_id:
        raise FeedError("The source batch is not READY under its saved batch identity.")
    source = metadata.get("source")
    if not isinstance(source, dict) or source.get("platformStatus") != "SUCCEEDED":
        raise FeedError("The source batch does not represent a successful collection.")
    for key in ("runId", "datasetId", "buildId"):
        if not isinstance(source.get(key), str) or not re.fullmatch(r"[A-Za-z0-9]{4,64}", source[key]):
            raise FeedError("Missing source run/dataset/build provenance.")
    if not isinstance(source.get("buildNumber"), str) or not re.fullmatch(r"\d+\.\d+\.\d+", source["buildNumber"]):
        raise FeedError("Missing or invalid source build number.")
    when(source.get("observedAt"), "Source observation")
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != SOURCE_ARTIFACTS:
        raise FeedError("The source batch has an unexpected artifact set.")
    for name, expected in artifacts.items():
        raw = read_bytes(directory / name)
        if not isinstance(expected, dict) or expected.get("sha256") != sha(raw) or type(expected.get("bytes")) is not int or expected["bytes"] != len(raw):
            raise FeedError("A source batch artifact no longer matches its recorded hash/size.")
    rows = read_json(directory / "new-jobs.json")
    if not isinstance(metadata.get("counts"), dict):
        raise FeedError("Invalid source batch counts.")
    count = metadata["counts"].get("newJobs")
    if not isinstance(rows, list) or len(rows) > MAX_SOURCE_ROWS or any(not isinstance(r, dict) for r in rows) or type(count) is not int or count != len(rows):
        raise FeedError("The source batch's new-job count or records are inconsistent.")
    return metadata, rows, sha(metadata_raw)


def project_job(row, source):
    job_id = source_identity(row)
    for key in ("title", "companyName", "location"):
        if not plain(row.get(key)):
            raise FeedError("missing_" + key)
    if row.get("detailStatus") not in {"complete", "not_requested"} or str(row.get("status", "")).upper() in {"FAILED", "ERROR"}:
        raise FeedError("source_details_unavailable_or_failed")
    if row.get("detailStatus") == "complete" and not any(isinstance(row.get(k), str) and row[k].strip() for k in ("descriptionText", "descriptionHtml")):
        raise FeedError("source_complete_description_missing")
    source_finished = when(source["observedAt"], "Source observation")
    row_observed = when(row.get("scrapedAt") or source["observedAt"], "Job source observation")
    if row_observed > source_finished + timedelta(seconds=5):
        raise FeedError("source_observation_after_collection_finish")
    observed = max(row_observed, source_finished)
    result = {"jobId": job_id, "jobUrl": "https://www.linkedin.com/jobs/view/" + job_id,
              "jobTitle": row["title"], "companyName": row["companyName"], "location": row["location"]}
    warnings = []
    for key, target in (("companyUrl", "companyUrl"), ("companyWebsite", "companyWebsite"), ("officialApplyUrl", "applyUrl")):
        if row.get(key):
            if safe_https(row[key]):
                result[target] = row[key]
            else:
                warnings.append("unsafe_" + key + "_hint_omitted")
    return result, observed.isoformat(), warnings


def publish_directory(directory, files):
    directory = Path(directory)
    if directory.exists():
        if directory.is_dir() and all((directory / name).is_file() and not (directory / name).is_symlink() and read_bytes(directory / name) == raw for name, raw in files.items()) and set(p.name for p in directory.iterdir()) == set(files):
            return
        raise FeedError("Output already exists with different contents; refusing overwrite.")
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".verified-feed-", dir=directory.parent))
    try:
        for name, raw in files.items():
            if len(raw) > MAX_FILE_BYTES:
                raise FeedError("An output artifact exceeds the 50 MB limit.")
            with (temporary / name).open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        os.rename(temporary, directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def prepare(batch_dir, output_dir, max_items=20, offset=0):
    if type(max_items) is not int or not 1 <= max_items <= 500 or type(offset) is not int or offset < 0:
        raise FeedError("max-items must be 1-500 and offset must be nonnegative.")
    metadata, rows, metadata_hash = load_source_batch(batch_dir)
    eligible, held, identities = [], [], set()
    for row in rows:
        try:
            job_id = source_identity(row)
        except FeedError as exc:
            held.append({"reason": str(exc), "sourceRow": row})
            continue
        if job_id in identities:
            raise FeedError("Duplicate/conflicting source identities are not accepted.")
        identities.add(job_id)
        try:
            projected, observed, warnings = project_job(row, metadata["source"])
            eligible.append({"jobId": job_id, "sourceRow": row, "sourceRowSha256": digest(row),
                             "sourceObservedAt": observed, "verifierRow": projected, "warnings": warnings})
        except FeedError as exc:
            held.append({"jobId": job_id, "reason": str(exc), "sourceRow": row})
    if eligible and offset >= len(eligible):
        raise FeedError("offset is outside the eligible source jobs.")
    selected = eligible[offset:offset + max_items]
    deferred = eligible[:offset] + eligible[offset + max_items:]
    for index, item in enumerate(selected):
        item["sourceIndex"] = index
    verifier_input = {**SETTINGS, "maxItems": len(selected), "rows": [item["verifierRow"] for item in selected]}
    status = "PREPARED" if selected else "SKIPPED_NO_NEW_JOBS" if not rows else "SKIPPED_NO_ELIGIBLE_JOBS"
    files = {"selected-source-jobs.json": encoded(selected), "held-source-jobs.json": encoded(held), "deferred-source-jobs.json": encoded(deferred)}
    if selected:
        files["verifier-input.json"] = encoded(verifier_input)
    manifest = {"formatVersion": 1, "status": status, "sourceBatchId": metadata["batchId"], "watchlist": metadata.get("watchlist"),
                "source": metadata["source"], "sourceMetadataSha256": metadata_hash,
                "sourceNewJobsSha256": metadata["artifacts"]["new-jobs.json"]["sha256"],
                "maxItems": max_items, "eligibleOffset": offset,
                "counts": {"newSourceJobs": len(rows), "eligibleJobs": len(eligible), "selectedJobs": len(selected), "heldSourceJobs": len(held), "deferredJobs": len(deferred)},
                "verificationInputSha256": digest(verifier_input) if selected else None,
                "artifactHashes": {name: sha(raw) for name, raw in files.items()},
                "startsActor": False, "sourceCollectionChargesRefunded": False, "closureInference": False,
                "scope": "Only new-jobs.json from the existing READY batch. No full-dataset verification or automatic external delivery."}
    manifest["requestId"] = digest(manifest)
    files["manifest.json"] = encoded(manifest)
    files["READY"] = (sha(files["manifest.json"]) + "\n").encode("ascii")
    publish_directory(output_dir, files)
    return manifest


def load_request(directory):
    directory = Path(directory)
    raw = read_bytes(directory / "manifest.json")
    if read_bytes(directory / "READY").decode("ascii").strip() != sha(raw):
        raise FeedError("Prepared request READY hash does not match its manifest.")
    manifest = read_json(directory / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("formatVersion") != 1 or manifest.get("status") != "PREPARED":
        raise FeedError("Only a nonempty PREPARED request can be merged.")
    if digest({key: value for key, value in manifest.items() if key != "requestId"}) != manifest.get("requestId"):
        raise FeedError("Prepared request ID does not match its saved manifest content.")
    allowed = {"selected-source-jobs.json", "held-source-jobs.json", "deferred-source-jobs.json", "verifier-input.json"}
    hashes = manifest.get("artifactHashes")
    if not isinstance(hashes, dict) or set(hashes) != allowed:
        raise FeedError("Prepared request has an unexpected artifact set.")
    for name, expected in hashes.items():
        if sha(read_bytes(directory / name)) != expected:
            raise FeedError("A prepared request artifact changed after preparation.")
    selected = read_json(directory / "selected-source-jobs.json")
    verifier_input = read_json(directory / "verifier-input.json")
    if not isinstance(verifier_input, dict) or not isinstance(verifier_input.get("rows"), list) or not isinstance(manifest.get("counts"), dict) or type(manifest["counts"].get("selectedJobs")) is not int:
        raise FeedError("Prepared verifier input or selected counts are invalid.")
    if digest(verifier_input) != manifest.get("verificationInputSha256"):
        raise FeedError("Prepared verifier input does not match its manifest.")
    if not isinstance(selected, list) or len(selected) != manifest.get("counts", {}).get("selectedJobs") or len(selected) != len(verifier_input.get("rows", [])) or not 1 <= len(selected) <= 500:
        raise FeedError("Prepared selected job counts do not agree.")
    identities = set()
    for index, item in enumerate(selected):
        if not isinstance(item, dict) or type(item.get("sourceIndex")) is not int or item["sourceIndex"] != index or item.get("jobId") in identities or digest(item.get("sourceRow")) != item.get("sourceRowSha256"):
            raise FeedError("Prepared source rows contain invalid or duplicate identities.")
        projected, observed, warnings = project_job(item["sourceRow"], manifest["source"])
        if item["jobId"] != projected["jobId"] or item.get("verifierRow") != projected or verifier_input["rows"][index] != projected or item.get("sourceObservedAt") != observed or item.get("warnings") != warnings:
            raise FeedError("Prepared source content and verifier projections disagree.")
        identities.add(item["jobId"])
    return manifest, selected, verifier_input


def normalized_verifier_input(value):
    if not isinstance(value, dict) or value.get("datasetId") or set(value) - set(SETTINGS) - {"rows", "maxItems", "datasetId"}:
        raise FeedError("Expected the saved explicit-row verifier input, without datasetId or extra settings.")
    normalized = {**SETTINGS, **{key: value[key] for key in SETTINGS if key in value}, "maxItems": value.get("maxItems", 500), "rows": value.get("rows")}
    for key in ("autoDiscoverCompanyWebsite", "useReaderFallback", "includeVerificationReport"):
        if type(normalized[key]) is not bool:
            raise FeedError("Saved verifier settings must preserve exact boolean types.")
    for key, minimum, maximum in (("maxItems", 1, 500), ("maxSearchQueries", 1, 5), ("maxCandidates", 1, 12), ("maxBridgePages", 0, 6)):
        if type(normalized[key]) is not int or not minimum <= normalized[key] <= maximum:
            raise FeedError("Saved verifier settings must preserve bounded integer types.")
    if not isinstance(normalized["rows"], list) or not 1 <= len(normalized["rows"]) <= 500 or any(not isinstance(row, dict) for row in normalized["rows"]):
        raise FeedError("Saved verifier input must contain one to 500 explicit job objects.")
    return normalized


def safe_csv(records):
    fields = ("id", "title", "companyName", "location", "descriptionText", "postedAt", "sourceJobUrl", "actionUrl", "verificationStatus", "verificationConfidence", "verificationCheckedAt", "reason", "sourceRunId", "verificationRunId")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for record in records:
        cells = {}
        for field in fields:
            value = record.get(field)
            text = "" if value is None else str(value)
            probe = text.lstrip(" \t\r\n\v\f\ufeff\x00")
            cells[field] = "'" + text if probe.startswith(("=", "+", "-", "@")) else text
        writer.writerow(cells)
    return output.getvalue().encode("utf-8")


def merge(request_dir, saved_input, run, rows, summary, output_dir, as_of=None):
    manifest, selected, verifier_input = load_request(request_dir)
    if digest(normalized_verifier_input(saved_input)) != digest(verifier_input):
        raise FeedError("Saved verifier input does not match this prepared request. Refusing to attach a different run.")
    if isinstance(run, dict) and isinstance(run.get("data"), dict):
        run = run["data"]
    if not isinstance(run, dict) or run.get("status") != "SUCCEEDED" or not isinstance(summary, dict) or summary.get("status") != "SUCCEEDED":
        raise FeedError("Both platform run and verifier OUTPUT must report SUCCEEDED.")
    for key in ("id", "defaultDatasetId", "buildId"):
        if not isinstance(run.get(key), str) or not re.fullmatch(r"[A-Za-z0-9]{4,64}", run[key]):
            raise FeedError("Missing verifier run/dataset/build provenance.")
    if not isinstance(run.get("buildNumber"), str) or not re.fullmatch(r"\d+\.\d+\.\d+", run["buildNumber"]):
        raise FeedError("Missing or invalid verifier build number.")
    started = when(run.get("startedAt"), "Verifier startedAt")
    finished = when(run.get("finishedAt"), "Verifier finishedAt")
    evaluated = when(as_of, "Evaluation time") if as_of else datetime.now(timezone.utc)
    if finished < started or finished > evaluated + timedelta(seconds=5):
        raise FeedError("Verifier run time window is invalid or after evaluation time.")
    if not isinstance(rows, list) or len(rows) > 500 or any(not isinstance(row, dict) for row in rows):
        raise FeedError("Expected at most 500 exported verifier dataset rows.")
    for key, count in (("requestedRows", len(selected)), ("deliveredRows", len(rows))):
        if type(summary.get(key)) is not int or summary[key] != count:
            raise FeedError("Verifier OUTPUT request/delivery counts do not match this input and dataset.")
    decisions = {}
    useful = publishable_flags = valid_count = 0
    for decision in rows:
        index = decision.get("sourceIndex")
        if type(index) is not int or not 0 <= index < len(selected) or index in decisions:
            raise FeedError("Verifier decisions have orphan, duplicate or invalid sourceIndex values.")
        expected = selected[index]["verifierRow"]
        if str(decision.get("jobId", "")) != expected["jobId"] or linkedin_id(decision.get("linkedinUrl")) != expected["jobId"]:
            raise FeedError("Verifier result identity does not match its prepared source index.")
        for output_key, input_key in (("title", "jobTitle"), ("company", "companyName"), ("location", "location")):
            if norm(decision.get(output_key)) != norm(expected[input_key]):
                raise FeedError("Verifier result content does not match the prepared job observation.")
        status = decision.get("status")
        if status not in USEFUL | DIAGNOSTIC:
            raise FeedError("Unknown verifier decision status.")
        for flag in ("safeToPublish", "reviewRequired", "usefulClassification"):
            if type(decision.get(flag)) is not bool:
                raise FeedError("Verifier decision flags must be actual booleans.")
        if decision["usefulClassification"] != (status in USEFUL):
            raise FeedError("Useful decision flag conflicts with the verifier status.")
        confidence = decision.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise FeedError("Verifier confidence must be a finite source value from zero to one.")
        if decision["safeToPublish"] and (status not in PUBLISHABLE or not decision.get("actionUrl")):
            raise FeedError("Verifier publish flag conflicts with status or action URL.")
        if status not in PUBLISHABLE and decision.get("actionUrl"):
            raise FeedError("A held verifier decision unexpectedly has an action URL.")
        if not isinstance(decision.get("evidence"), list) or any(not isinstance(x, str) for x in decision["evidence"]):
            raise FeedError("Verifier evidence must be a list of source strings.")
        checked = when(decision.get("checkedAt"), "Verifier checkedAt")
        if checked < started - timedelta(seconds=5) or checked > finished + timedelta(seconds=5):
            raise FeedError("Verifier decision time does not belong to the saved run window.")
        decisions[index] = decision
        useful += int(decision["usefulClassification"])
        publishable_flags += int(decision["safeToPublish"])
        valid_count += int(status not in {"INVALID_INPUT", "DUPLICATE_INPUT"})
    for key, count in (("usefulClassifications", useful), ("safeToPublishRows", publishable_flags), ("rows", valid_count)):
        if type(summary.get(key)) is not int or summary[key] != count:
            raise FeedError("Verifier OUTPUT decision totals do not match the exported dataset.")
    billing = summary.get("billing")
    if not isinstance(billing, dict) or billing.get("unresolvedRowsCharged") is not False or billing.get("invalidOrDuplicateRowsCharged") is not False:
        raise FeedError("Verifier OUTPUT does not confirm unbillable diagnostic protection.")
    if type(billing.get("payPerEventActive")) is not bool:
        raise FeedError("Verifier OUTPUT billing mode must be an actual boolean.")
    charges = run.get("chargedEventCounts")
    if charges is None:
        charges = {}
    if not isinstance(charges, dict):
        raise FeedError("Verifier chargedEventCounts must be an object.")
    charged = charges.get("verified-job")
    if billing["payPerEventActive"] and (type(charged) is not int or charged != useful):
        raise FeedError("Verified-job event count does not match useful decisions.")
    if not billing["payPerEventActive"] and charged is not None and (type(charged) is not int or charged != 0):
        raise FeedError("Verified-job event charges conflict with inactive pay-per-event billing.")
    input_hashes = {"preparedVerifierInput": digest(verifier_input), "savedVerifierInput": digest(normalized_verifier_input(saved_input)), "verifierRun": digest(run), "verifierRows": digest(rows), "verifierOutput": digest(summary)}
    # An identical retry preserves its first evaluation timestamp. Reuse is
    # allowed only after validating this invocation and all prior artifact hashes.
    if as_of is None and Path(output_dir).exists():
        previous_raw = read_bytes(Path(output_dir) / "handoff-summary.json")
        previous = read_json(Path(output_dir) / "handoff-summary.json")
        marker = read_bytes(Path(output_dir) / "READY").decode("ascii").strip()
        allowed_outputs = {"publishable-jobs.json", "publishable-jobs.csv", "held-jobs.json", "held-jobs.csv"}
        if marker != sha(previous_raw) or not isinstance(previous, dict) or not isinstance(previous.get("artifactHashes"), dict) or set(previous["artifactHashes"]) != allowed_outputs:
            raise FeedError("Existing handoff integrity checks failed; refusing timestamp reuse or overwrite.")
        for name, expected in previous["artifactHashes"].items():
            if sha(read_bytes(Path(output_dir) / name)) != expected:
                raise FeedError("An existing handoff artifact changed after publication.")
        if previous.get("requestId") == manifest["requestId"] and digest(previous.get("inputHashes")) == digest(input_hashes):
            evaluated = when(previous.get("evaluatedAt"), "Previous evaluation time")
            if finished > evaluated + timedelta(seconds=5):
                raise FeedError("Previous handoff evaluation predates the saved verifier run.")
    published, held = [], []
    for index, item in enumerate(selected):
        decision = decisions.get(index)
        reason = None
        if decision is None:
            reason = "MISSING_VERIFIER_DECISION"
        elif when(decision["checkedAt"]) < when(item["sourceObservedAt"]):
            reason = "VERIFICATION_PREDATES_SOURCE_OBSERVATION"
        elif decision["status"] not in PUBLISHABLE or not decision["safeToPublish"]:
            reason = "VERIFIER_" + decision["status"]
        elif decision["reviewRequired"]:
            reason = "VERIFIER_REQUIRES_REVIEW"
        elif not decision["evidence"] or any(not x.strip() for x in decision["evidence"]):
            reason = "MISSING_VERIFICATION_EVIDENCE"
        elif not safe_https(decision.get("actionUrl")):
            reason = "UNSAFE_ACTION_URL"
        elif decision["status"] == "LINKEDIN_EASY_APPLY" and linkedin_id(decision["actionUrl"]) != item["jobId"]:
            reason = "EASY_APPLY_IDENTITY_MISMATCH"
        record = dict(item["sourceRow"])
        # Existing hints/flags are never carried as a publish gate or action route.
        for field in ("officialApplyUrl", "safeToPublish", "reviewRequired", "verificationConfidence", "verifiedAt", "verificationStatus", "verificationEvidence", "jobStatus", "ghostJobRisk", "applyMethod"):
            record.pop(field, None)
        record.update(id=item["jobId"], sourceJobUrl=item["verifierRow"]["jobUrl"], actionUrl=decision.get("actionUrl") if decision and reason is None else None,
                      safeToPublish=reason is None, reviewRequired=reason is not None, reason=reason,
                      verificationStatus=decision.get("status") if decision else None,
                      verificationConfidence=decision.get("confidence") if decision else None,
                      verificationCheckedAt=decision.get("checkedAt") if decision else None,
                      verificationEvidence=decision.get("evidence") if decision else [],
                      applyMethod=decision.get("applyMethod") if decision else None,
                      sourceProvider=decision.get("sourceProvider") if decision else None,
                      sourceRunId=manifest["source"]["runId"], sourceDatasetId=manifest["source"]["datasetId"],
                      sourceBatchId=manifest["sourceBatchId"], verificationRunId=run["id"], verificationDatasetId=run["defaultDatasetId"],
                      sourceObservedAt=item["sourceObservedAt"], currentAvailabilityUnknown=True)
        if reason is None:
            published.append(record)
        else:
            record["sourceOriginal"] = item["sourceRow"]
            record["verificationDecision"] = decision
            held.append(record)
    partial = any(r["reason"] in {"MISSING_VERIFIER_DECISION", "VERIFICATION_PREDATES_SOURCE_OBSERVATION", "UNSAFE_ACTION_URL", "EASY_APPLY_IDENTITY_MISMATCH", "MISSING_VERIFICATION_EVIDENCE"} for r in held)
    result = {"formatVersion": 1, "status": "HANDOFF_PARTIAL" if partial else "HANDOFF_COMPLETE", "requestId": manifest["requestId"],
              "evaluatedAt": evaluated.isoformat(), "source": manifest["source"], "sourceBatchId": manifest["sourceBatchId"],
              "verifier": {"runId": run["id"], "datasetId": run["defaultDatasetId"], "buildId": run["buildId"], "buildNumber": run.get("buildNumber"), "startedAt": run["startedAt"], "finishedAt": run["finishedAt"]},
              "counts": {"selectedJobs": len(selected), "verifierDatasetRows": len(rows), "usefulDecisions": useful, "publishableJobs": len(published), "heldJobs": len(held), "heldSourceJobsBeforeVerification": manifest["counts"]["heldSourceJobs"], "deferredSourceJobs": manifest["counts"]["deferredJobs"]},
              "inputHashes": input_hashes,
              "startsActor": False, "publishesExternally": False, "closureInference": False, "realizedRevenueUsd": None,
              "limitations": ["This is an offline join of saved, dated source and verifier observations, not a fresh cloud check.", "Publishable means the saved verifier route passed the explicit output gate; current job availability remains unknown.", "Missing or absent decisions are held, never inferred to be closed. Source coverage remains as recorded by the collection.", "Preparing and merging do not refund or change previous collection/verification charges."]}
    files = {"publishable-jobs.json": encoded(published), "publishable-jobs.csv": safe_csv(published), "held-jobs.json": encoded(held), "held-jobs.csv": safe_csv(held), "handoff-summary.json": encoded(result)}
    result["artifactHashes"] = {name: sha(raw) for name, raw in files.items() if name != "handoff-summary.json"}
    files["handoff-summary.json"] = encoded(result)
    files["READY"] = (sha(files["handoff-summary.json"]) + "\n").encode("ascii")
    publish_directory(output_dir, files)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    prep = modes.add_parser("prepare", help="Project only new jobs from an existing READY batch; never starts a run.")
    prep.add_argument("--batch", required=True, type=Path)
    prep.add_argument("--out", required=True, type=Path)
    prep.add_argument("--max-items", type=int, default=20)
    prep.add_argument("--offset", type=int, default=0)
    joined = modes.add_parser("merge", help="Join matching saved verifier exports into local publishable and held files.")
    joined.add_argument("--request", required=True, type=Path)
    joined.add_argument("--verifier-input", required=True, type=Path, help="Saved INPUT record from this verifier run, without credentials.")
    joined.add_argument("--run", required=True, type=Path)
    joined.add_argument("--rows", required=True, type=Path)
    joined.add_argument("--summary", required=True, type=Path)
    joined.add_argument("--out", required=True, type=Path)
    joined.add_argument("--as-of", help="Optional timezone-aware evaluation clock for clearly dated offline replay.")
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            result = prepare(args.batch, args.out, args.max_items, args.offset)
        else:
            result = merge(args.request, *(read_json(path) for path in (args.verifier_input, args.run, args.rows, args.summary)), args.out, args.as_of)
        print(json.dumps({"status": result["status"], "requestId": result["requestId"], "counts": result["counts"], "startsActor": False}))
        return 0
    except (FeedError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, FeedError) else "Local input or export failed; source files and seen history were not modified."
        print("Handoff stopped: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
