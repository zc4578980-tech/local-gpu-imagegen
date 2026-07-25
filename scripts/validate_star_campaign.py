#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit


CAMPAIGN_FIELDS = {
    "schema_version",
    "campaign_id",
    "repository",
    "release",
    "goal",
    "events_file",
    "hash_algorithm",
}
RELEASE_FIELDS = {"id", "tag_name", "html_url", "published_at"}
GOAL_FIELDS = {
    "metric",
    "target",
    "target_days",
    "baseline_grace_seconds",
    "collection_window_hours",
}
EVENT_FIELDS = {
    "schema_version",
    "sequence",
    "event_type",
    "phase",
    "recorded_at",
    "scheduled_at",
    "observed_at",
    "observation_status",
    "repository_star_count",
    "source",
    "failure",
    "supersedes_sequence",
    "correction_reason",
    "previous_event_sha256",
    "event_sha256",
}
SOURCE_FIELDS = {"api_url", "response_date", "etag"}
FAILURE_FIELDS = {"kind", "message"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAMPAIGN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
IDENTITY_KEY_RE = re.compile(
    r"(?i)(stargazer|login|user|account|email|token|authorization)"
)


class DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _parse_json(text: str) -> object:
    return json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def event_sha256(event: dict[str, object]) -> str:
    payload = {
        key: value for key, value in event.items() if key != "event_sha256"
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def format_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def scheduled_at(campaign: dict[str, object], phase: str) -> datetime:
    release = campaign.get("release")
    if not isinstance(release, dict):
        raise ValueError("invalid release")
    published_at = parse_utc(release.get("published_at"))
    if published_at is None:
        raise ValueError("invalid release publication timestamp")
    if phase == "baseline":
        return published_at
    if phase == "t30":
        return published_at + timedelta(days=30)
    raise ValueError("invalid observation phase")


def make_event(
    *,
    sequence: int,
    event_type: str,
    phase: str,
    recorded_at: str,
    scheduled_at_value: str,
    observed_at: str,
    observation_status: str,
    repository_star_count: int | None,
    source: dict[str, object],
    failure: dict[str, str] | None,
    supersedes_sequence: int | None,
    correction_reason: str | None,
    previous_event_sha256: str | None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "schema_version": "1.0",
        "sequence": sequence,
        "event_type": event_type,
        "phase": phase,
        "recorded_at": recorded_at,
        "scheduled_at": scheduled_at_value,
        "observed_at": observed_at,
        "observation_status": observation_status,
        "repository_star_count": repository_star_count,
        "source": source,
        "failure": failure,
        "supersedes_sequence": supersedes_sequence,
        "correction_reason": correction_reason,
        "previous_event_sha256": previous_event_sha256,
    }
    event["event_sha256"] = event_sha256(event)
    return event


def _is_int(value: object, *, minimum: int | None = None) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return minimum is None or value >= minimum


def _bounded_text(value: object, maximum: int, *, minimum: int = 1) -> bool:
    return (
        isinstance(value, str)
        and minimum <= len(value) <= maximum
        and "\n" not in value
        and "\r" not in value
    )


def _contains_identity_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            IDENTITY_KEY_RE.search(str(key)) is not None
            or _contains_identity_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_identity_key(item) for item in value)
    return False


def _valid_release_url(value: object, repository: object, tag: object) -> bool:
    if not isinstance(value, str) or len(value) > 500:
        return False
    if not isinstance(repository, str) or not isinstance(tag, str):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path == f"/{repository}/releases/tag/{tag}"
    )


def _validate_campaign_document(
    campaign: dict[str, object], campaign_dir: Path
) -> set[str]:
    findings: set[str] = set()
    if set(campaign) != CAMPAIGN_FIELDS:
        findings.add("invalid_campaign_fields")
    if campaign.get("schema_version") != "1.0":
        findings.add("invalid_campaign_schema_version")

    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or not CAMPAIGN_ID_RE.fullmatch(campaign_id):
        findings.add("invalid_campaign_id")
    elif campaign_id != campaign_dir.name:
        findings.add("campaign_id_path_mismatch")

    repository = campaign.get("repository")
    if (
        not isinstance(repository, str)
        or len(repository) > 200
        or not REPOSITORY_RE.fullmatch(repository)
    ):
        findings.add("invalid_repository")

    release = campaign.get("release")
    if not isinstance(release, dict) or set(release) != RELEASE_FIELDS:
        findings.add("invalid_release")
    else:
        release_id = release.get("id")
        tag = release.get("tag_name")
        if (
            not _is_int(release_id, minimum=1)
            or not _bounded_text(tag, 100)
            or parse_utc(release.get("published_at")) is None
            or not _valid_release_url(release.get("html_url"), repository, tag)
        ):
            findings.add("invalid_release")

    goal = campaign.get("goal")
    if not isinstance(goal, dict) or set(goal) != GOAL_FIELDS:
        findings.add("invalid_goal_fields")
    elif goal != {
        "metric": "net_new_repository_stars",
        "target": 100,
        "target_days": 30,
        "baseline_grace_seconds": 300,
        "collection_window_hours": 24,
    }:
        findings.add("invalid_goal_policy")

    if campaign.get("events_file") != "events.jsonl":
        findings.add("invalid_events_file")
    if campaign.get("hash_algorithm") != "sha256":
        findings.add("invalid_hash_algorithm")
    return findings


def _load_campaign(campaign_dir: Path) -> tuple[dict[str, object] | None, set[str]]:
    findings: set[str] = set()
    try:
        encoded = (campaign_dir / "campaign.json").read_bytes()
        if encoded.startswith(b"\xef\xbb\xbf"):
            raise UnicodeError("UTF-8 BOM is forbidden")
        value = _parse_json(encoded.decode("utf-8", errors="strict"))
    except DuplicateKeyError:
        findings.add("duplicate_json_key")
        return None, findings
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        findings.add("invalid_campaign_json")
        return None, findings
    if not isinstance(value, dict):
        findings.add("invalid_campaign_json")
        return None, findings
    return value, findings


def _load_events(campaign_dir: Path) -> tuple[list[dict[str, object]], set[str]]:
    findings: set[str] = set()
    events: list[dict[str, object]] = []
    try:
        encoded = (campaign_dir / "events.jsonl").read_bytes()
        text = encoded.decode("ascii", errors="strict")
    except OSError:
        return events, {"invalid_event_file"}
    except UnicodeError:
        return events, {"invalid_event_encoding"}

    if text and not text.endswith("\n"):
        findings.add("noncanonical_event_line")
    for raw_line in text.splitlines(keepends=True):
        line = raw_line[:-1] if raw_line.endswith("\n") else raw_line
        if not line:
            findings.add("blank_event_line")
            continue
        try:
            value = _parse_json(line)
        except DuplicateKeyError:
            findings.add("duplicate_json_key")
            continue
        except (ValueError, json.JSONDecodeError):
            findings.add("invalid_event_json")
            continue
        if not isinstance(value, dict):
            findings.add("invalid_event_json")
            continue
        try:
            if line != canonical_json(value).decode("ascii"):
                findings.add("noncanonical_event_line")
        except (TypeError, ValueError, UnicodeError):
            findings.add("invalid_event_json")
            continue
        events.append(value)
    return events, findings


def _validate_source(source: object, repository: object) -> set[str]:
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        return {"invalid_source"}
    expected_url = (
        f"https://api.github.com/repos/{repository}"
        if isinstance(repository, str)
        else None
    )
    response_date = source.get("response_date")
    etag = source.get("etag")
    if (
        source.get("api_url") != expected_url
        or (response_date is not None and parse_utc(response_date) is None)
        or (
            etag is not None
            and (not isinstance(etag, str) or len(etag) > 500 or "\n" in etag)
        )
    ):
        return {"invalid_source"}
    return set()


def _validate_failure(failure: object) -> bool:
    return (
        isinstance(failure, dict)
        and set(failure) == FAILURE_FIELDS
        and _bounded_text(failure.get("kind"), 100)
        and _bounded_text(failure.get("message"), 500)
    )


def _validate_event(
    event: dict[str, object],
    *,
    expected_sequence: int,
    prior_hash: str | None,
    campaign: dict[str, object] | None,
) -> set[str]:
    findings: set[str] = set()
    if _contains_identity_key(event):
        findings.add("identity_field_forbidden")
    if set(event) != EVENT_FIELDS:
        findings.add("invalid_event_fields")
    if event.get("schema_version") != "1.0":
        findings.add("invalid_event_schema_version")

    sequence = event.get("sequence")
    if not _is_int(sequence, minimum=1) or sequence != expected_sequence:
        findings.add("invalid_event_sequence")
    event_type = event.get("event_type")
    if event_type not in {"observation", "correction"}:
        findings.add("invalid_event_type")
    phase = event.get("phase")
    if phase not in {"baseline", "t30"}:
        findings.add("invalid_event_phase")

    recorded = parse_utc(event.get("recorded_at"))
    observed = parse_utc(event.get("observed_at"))
    scheduled = parse_utc(event.get("scheduled_at"))
    if recorded is None or observed is None or scheduled is None:
        findings.add("invalid_event_timestamp")
    if campaign is not None and phase in {"baseline", "t30"}:
        try:
            if event.get("scheduled_at") != format_utc(scheduled_at(campaign, phase)):
                findings.add("invalid_event_schedule")
        except ValueError:
            findings.add("invalid_event_schedule")

    findings.update(_validate_source(event.get("source"), None if campaign is None else campaign.get("repository")))

    status = event.get("observation_status")
    count = event.get("repository_star_count")
    failure = event.get("failure")
    if status == "observed":
        if not _is_int(count, minimum=0) or failure is not None:
            findings.add("invalid_observation_fields")
    elif status == "observation_failed":
        if count is not None or not _validate_failure(failure):
            findings.add("invalid_observation_fields")
    else:
        findings.add("invalid_observation_status")

    supersedes = event.get("supersedes_sequence")
    reason = event.get("correction_reason")
    if event_type == "observation":
        if supersedes is not None or reason is not None:
            findings.add("invalid_observation_fields")
    elif event_type == "correction":
        if not _is_int(supersedes, minimum=1) or not _bounded_text(reason, 500):
            findings.add("invalid_correction_fields")

    if event.get("previous_event_sha256") != prior_hash:
        findings.add("previous_event_sha256_mismatch")
    declared_hash = event.get("event_sha256")
    if not isinstance(declared_hash, str) or not SHA256_RE.fullmatch(declared_hash):
        findings.add("invalid_event_sha256")
    else:
        try:
            if declared_hash != event_sha256(event):
                findings.add("event_sha256_mismatch")
        except (TypeError, ValueError, UnicodeError):
            findings.add("invalid_event_json")
    return findings


def _empty_report() -> dict[str, object]:
    return {
        "ok": False,
        "findings": [],
        "campaign_id": None,
        "event_count": 0,
        "effective_sequences": {"baseline": None, "t30": None},
        "baseline_quality": None,
        "t30_quality": None,
        "baseline_count": None,
        "t30_count": None,
        "net_new_stars": None,
        "outcome": "measurement_incomplete",
    }


def validate_campaign(campaign_dir: Path) -> dict[str, object]:
    report = _empty_report()
    findings: set[str] = set()
    campaign, campaign_findings = _load_campaign(campaign_dir)
    findings.update(campaign_findings)
    if campaign is not None:
        report["campaign_id"] = campaign.get("campaign_id")
        findings.update(_validate_campaign_document(campaign, campaign_dir))

    events, event_findings = _load_events(campaign_dir)
    findings.update(event_findings)
    report["event_count"] = len(events)

    prior_hash: str | None = None
    events_by_sequence: dict[int, dict[str, object]] = {}
    effective: dict[str, dict[str, object]] = {}
    for expected_sequence, event in enumerate(events, start=1):
        local_findings = _validate_event(
            event,
            expected_sequence=expected_sequence,
            prior_hash=prior_hash,
            campaign=campaign,
        )
        sequence = event.get("sequence")
        phase = event.get("phase")
        if event.get("event_type") == "correction" and _is_int(sequence, minimum=1):
            target_sequence = event.get("supersedes_sequence")
            target = (
                events_by_sequence.get(target_sequence)
                if _is_int(target_sequence, minimum=1)
                else None
            )
            if target is not None and target.get("phase") != phase:
                local_findings.add("correction_phase_mismatch")
            current = effective.get(phase) if isinstance(phase, str) else None
            if current is None or current.get("sequence") != target_sequence:
                local_findings.add("invalid_correction_target")
        findings.update(local_findings)

        if not local_findings and _is_int(sequence, minimum=1):
            events_by_sequence[sequence] = event
            if phase in {"baseline", "t30"}:
                effective[phase] = event
        declared_hash = event.get("event_sha256")
        prior_hash = declared_hash if isinstance(declared_hash, str) else None

    report["effective_sequences"] = {
        phase: effective.get(phase, {}).get("sequence")
        for phase in ("baseline", "t30")
    }
    if not findings and campaign is not None:
        _derive_outcome(report, campaign, effective)
    report["findings"] = sorted(findings)
    report["ok"] = not findings
    return report


def _derive_outcome(
    report: dict[str, object],
    campaign: dict[str, object],
    effective: dict[str, dict[str, object]],
) -> None:
    published = scheduled_at(campaign, "baseline")
    target_at = scheduled_at(campaign, "t30")
    window_close = target_at + timedelta(hours=24)

    baseline = effective.get("baseline")
    if baseline is not None:
        if baseline.get("observation_status") == "observation_failed":
            report["baseline_quality"] = "failed"
        else:
            observed = parse_utc(baseline.get("observed_at"))
            assert observed is not None
            report["baseline_quality"] = (
                "on_time"
                if observed <= published + timedelta(seconds=300)
                else "degraded"
            )
            report["baseline_count"] = baseline.get("repository_star_count")

    t30 = effective.get("t30")
    if t30 is not None:
        if t30.get("observation_status") == "observation_failed":
            report["t30_quality"] = "failed"
        else:
            observed = parse_utc(t30.get("observed_at"))
            assert observed is not None
            if observed < target_at:
                report["t30_quality"] = "early"
            elif observed > window_close:
                report["t30_quality"] = "late"
            else:
                report["t30_quality"] = "within_window"
                report["t30_count"] = t30.get("repository_star_count")

    baseline_count = report["baseline_count"]
    t30_count = report["t30_count"]
    if _is_int(baseline_count, minimum=0) and _is_int(t30_count, minimum=0):
        net_new = t30_count - baseline_count
        report["net_new_stars"] = net_new
        report["outcome"] = "goal_met" if net_new >= 100 else "goal_missed"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate append-only post-release Star campaign evidence."
    )
    parser.add_argument("campaign_dir", type=Path)
    args = parser.parse_args()
    report = validate_campaign(args.campaign_dir)
    stream = None if report["ok"] else sys.stderr
    print(json.dumps(report, indent=2, sort_keys=True), file=stream)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
