#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import quote, urlsplit

from validate_star_campaign import (
    CAMPAIGN_ID_RE,
    REPOSITORY_RE,
    canonical_json,
    format_utc,
    make_event,
    parse_utc,
    scheduled_at,
    validate_campaign,
)


MAX_RESPONSE_BYTES = 1_048_576
EVENT_VALUE_FIELDS = {
    "event_type",
    "phase",
    "recorded_at",
    "scheduled_at_value",
    "observed_at",
    "observation_status",
    "repository_star_count",
    "source",
    "failure",
    "supersedes_sequence",
    "correction_reason",
}


@dataclass(frozen=True)
class ApiResult:
    document: dict[str, object]
    response_date: str | None
    etag: str | None


class ObservationError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        token = os.environ.get("GITHUB_TOKEN", "")
        safe = message.replace(token, "[redacted]") if token else message
        self.kind = kind.replace("\r", " ").replace("\n", " ")[:100]
        self.safe_message = safe.replace("\r", " ").replace("\n", " ")[:500]
        super().__init__(self.safe_message)


def _duplicate_free(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _api_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.github.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/repos/")
        and not parsed.query
        and not parsed.fragment
    )


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        if not _api_url(newurl):
            raise ObservationError(
                "redirect_host_rejected",
                "GitHub API redirect host rejected",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubApi:
    def __init__(
        self,
        token: str | None = None,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes <= 0:
            raise ValueError("timeout and response limit must be positive")
        self.token = token.strip() if token else None
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.opener = urllib.request.build_opener(_SameHostRedirect())

    def get_json(self, url: str) -> ApiResult:
        if not _api_url(url):
            raise ObservationError("api_url_rejected", "GitHub API URL rejected")
        headers = {
            "User-Agent": "local-gpu-imagegen-star-recorder/1.0",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                if not _api_url(response.geturl()):
                    raise ObservationError(
                        "redirect_host_rejected",
                        "GitHub API redirect host rejected",
                    )
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > self.max_response_bytes:
                            raise ObservationError(
                                "response_too_large",
                                "GitHub API response exceeds the byte limit",
                            )
                    except ValueError as error:
                        raise ObservationError(
                            "invalid_response_header",
                            "GitHub API Content-Length is invalid",
                        ) from error
                encoded = response.read(self.max_response_bytes + 1)
                if len(encoded) > self.max_response_bytes:
                    raise ObservationError(
                        "response_too_large",
                        "GitHub API response exceeds the byte limit",
                    )
                response_date = self._response_date(response.headers.get("Date"))
                etag = response.headers.get("ETag")
                if etag is not None and (len(etag) > 500 or "\n" in etag):
                    raise ObservationError(
                        "invalid_response_header",
                        "GitHub API ETag is invalid",
                    )
        except ObservationError:
            raise
        except urllib.error.HTTPError as error:
            raise ObservationError(
                "http_error", f"GitHub returned HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ObservationError(
                "network_error", f"GitHub request failed: {error}"
            ) from error
        try:
            document = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=_duplicate_free,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid JSON constant: {value}")
                ),
            )
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise ObservationError("invalid_json", "GitHub returned invalid JSON") from error
        if not isinstance(document, dict):
            raise ObservationError(
                "invalid_json_object", "GitHub response must be a JSON object"
            )
        return ApiResult(document, response_date, etag)

    @staticmethod
    def _response_date(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError) as error:
            raise ObservationError(
                "invalid_response_header", "GitHub API Date is invalid"
            ) from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return format_utc(parsed)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _bounded_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and "\n" not in value
        and "\r" not in value
    )


def _repository_urls(repository: str, release_tag: str) -> tuple[str, str]:
    if not REPOSITORY_RE.fullmatch(repository) or len(repository) > 200:
        raise ObservationError("invalid_repository", "Repository name is invalid")
    if not _bounded_text(release_tag, 100):
        raise ObservationError("invalid_release_tag", "Release tag is invalid")
    encoded_repository = "/".join(quote(part, safe="") for part in repository.split("/"))
    repository_url = f"https://api.github.com/repos/{encoded_repository}"
    return repository_url, f"{repository_url}/releases/tags/{quote(release_tag, safe='')}"


def _campaign_document(
    campaign_id: str,
    repository: str,
    release_tag: str,
    release: dict[str, object],
) -> dict[str, object]:
    expected_html = f"https://github.com/{repository}/releases/tag/{release_tag}"
    if (
        not isinstance(release.get("id"), int)
        or isinstance(release.get("id"), bool)
        or int(release["id"]) <= 0
        or release.get("tag_name") != release_tag
        or release.get("html_url") != expected_html
        or parse_utc(release.get("published_at")) is None
        or release.get("draft") is not False
    ):
        raise ObservationError(
            "invalid_release", "GitHub Release is not a published exact match"
        )
    return {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "repository": repository,
        "release": {
            "id": release["id"],
            "tag_name": release_tag,
            "html_url": expected_html,
            "published_at": release["published_at"],
        },
        "goal": {
            "metric": "net_new_repository_stars",
            "target": 100,
            "target_days": 30,
            "baseline_grace_seconds": 300,
            "collection_window_hours": 24,
        },
        "events_file": "events.jsonl",
        "hash_algorithm": "sha256",
    }


def _create_campaign(campaign_dir: Path, campaign: dict[str, object]) -> None:
    try:
        campaign_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError as error:
        raise ObservationError("campaign_exists", "Campaign already exists") from error
    temporary = campaign_dir / "campaign.json.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write((json.dumps(campaign, indent=2) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, campaign_dir / "campaign.json")
        with (campaign_dir / "events.jsonl").open("xb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        if not validate_campaign(campaign_dir)["ok"]:
            raise ObservationError(
                "campaign_initialization_failed", "Created campaign is invalid"
            )
    except Exception:
        for path in (
            temporary,
            campaign_dir / "campaign.json",
            campaign_dir / "events.jsonl",
        ):
            path.unlink(missing_ok=True)
        campaign_dir.rmdir()
        raise


def initialize_campaign(
    adoption_root: Path,
    campaign_id: str,
    repository: str,
    release_tag: str,
    *,
    api: GitHubApi,
    now: Callable[[], datetime],
) -> dict[str, object]:
    if not CAMPAIGN_ID_RE.fullmatch(campaign_id):
        raise ObservationError("invalid_campaign_id", "Campaign ID is invalid")
    adoption_root.mkdir(parents=True, exist_ok=True)
    campaign_dir = adoption_root / campaign_id
    if campaign_dir.exists():
        raise ObservationError("campaign_exists", "Campaign already exists")
    _, release_url = _repository_urls(repository, release_tag)
    release = api.get_json(release_url)
    campaign = _campaign_document(
        campaign_id, repository, release_tag, release.document
    )
    _create_campaign(campaign_dir, campaign)
    return record_observation(campaign_dir, "baseline", api=api, now=now)


def _load_campaign(campaign_dir: Path) -> dict[str, object]:
    report = validate_campaign(campaign_dir)
    if not report["ok"]:
        raise ObservationError("invalid_history", "Campaign history is invalid")
    try:
        campaign = json.loads(
            (campaign_dir / "campaign.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise ObservationError("invalid_history", "Campaign history is invalid") from error
    if not isinstance(campaign, dict):
        raise ObservationError("invalid_history", "Campaign history is invalid")
    return campaign


def append_event(
    campaign_dir: Path, event_values: dict[str, object]
) -> dict[str, object]:
    if set(event_values) != EVENT_VALUE_FIELDS:
        raise ObservationError("invalid_event_values", "Event values are invalid")
    lock = campaign_dir / "events.jsonl.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ObservationError("lock_unavailable", "Campaign is already locked") from error
    try:
        try:
            os.write(descriptor, b"locked\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        report = validate_campaign(campaign_dir)
        if not report["ok"]:
            raise ObservationError("invalid_history", "Campaign history is invalid")
        events_path = campaign_dir / "events.jsonl"
        lines = events_path.read_text(encoding="ascii").splitlines()
        previous = json.loads(lines[-1]) if lines else None
        event = make_event(
            sequence=len(lines) + 1,
            previous_event_sha256=(
                None if previous is None else previous["event_sha256"]
            ),
            **event_values,
        )
        with events_path.open("ab") as handle:
            handle.write(canonical_json(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        report = validate_campaign(campaign_dir)
        if not report["ok"]:
            raise ObservationError(
                "post_append_validation_failed",
                "Appended campaign history is invalid",
            )
        return report
    finally:
        lock.unlink(missing_ok=True)


def _observation_values(
    campaign: dict[str, object],
    phase: str,
    observed_at: str,
    source_url: str,
    result: ApiResult | None,
    error: ObservationError | None,
) -> dict[str, object]:
    failed = error is not None
    count = None if result is None else result.document.get("stargazers_count")
    return {
        "event_type": "observation",
        "phase": phase,
        "recorded_at": observed_at,
        "scheduled_at_value": format_utc(scheduled_at(campaign, phase)),
        "observed_at": observed_at,
        "observation_status": "observation_failed" if failed else "observed",
        "repository_star_count": None if failed else count,
        "source": {
            "api_url": source_url,
            "response_date": None if result is None else result.response_date,
            "etag": None if result is None else result.etag,
        },
        "failure": (
            None
            if error is None
            else {"kind": error.kind, "message": error.safe_message}
        ),
        "supersedes_sequence": None,
        "correction_reason": None,
    }


def record_observation(
    campaign_dir: Path,
    phase: str,
    *,
    api: GitHubApi,
    now: Callable[[], datetime],
) -> dict[str, object]:
    campaign = _load_campaign(campaign_dir)
    if phase not in {"baseline", "t30"}:
        raise ObservationError("invalid_phase", "Observation phase is invalid")
    repository = campaign["repository"]
    assert isinstance(repository, str)
    repository_url, _ = _repository_urls(repository, "unused")
    result: ApiResult | None = None
    failure: ObservationError | None = None
    try:
        result = api.get_json(repository_url)
        full_name = result.document.get("full_name")
        count = result.document.get("stargazers_count")
        if (
            not isinstance(full_name, str)
            or full_name.casefold() != repository.casefold()
            or not _is_count(count)
        ):
            raise ObservationError(
                "repository_mismatch", "Repository count response is invalid"
            )
    except ObservationError as error:
        failure = error
        result = None
    observed_at = format_utc(now())
    return append_event(
        campaign_dir,
        _observation_values(
            campaign, phase, observed_at, repository_url, result, failure
        ),
    )


def record_correction(
    campaign_dir: Path,
    *,
    supersedes_sequence: int,
    observation_status: str,
    repository_star_count: int | None,
    observed_at: str,
    source_url: str,
    failure_kind: str | None,
    failure_message: str | None,
    reason: str,
    now: Callable[[], datetime],
) -> dict[str, object]:
    campaign = _load_campaign(campaign_dir)
    events = [
        json.loads(line)
        for line in (campaign_dir / "events.jsonl").read_text(
            encoding="ascii"
        ).splitlines()
    ]
    target = next(
        (event for event in events if event.get("sequence") == supersedes_sequence),
        None,
    )
    report = validate_campaign(campaign_dir)
    phase = None if target is None else target.get("phase")
    effective = report["effective_sequences"]
    if (
        not isinstance(phase, str)
        or not isinstance(effective, dict)
        or effective.get(phase) != supersedes_sequence
    ):
        raise ObservationError(
            "invalid_correction_target", "Correction target is not effective"
        )
    repository = campaign["repository"]
    if source_url != f"https://api.github.com/repos/{repository}":
        raise ObservationError("invalid_source_url", "Correction source is invalid")
    if parse_utc(observed_at) is None or not _bounded_text(reason, 500):
        raise ObservationError("invalid_correction", "Correction metadata is invalid")
    if observation_status == "observed":
        if not _is_count(repository_star_count) or failure_kind or failure_message:
            raise ObservationError("invalid_correction", "Correction value is invalid")
        failure = None
    elif observation_status == "observation_failed":
        if (
            repository_star_count is not None
            or not _bounded_text(failure_kind, 100)
            or not _bounded_text(failure_message, 500)
        ):
            raise ObservationError("invalid_correction", "Correction failure is invalid")
        failure = {"kind": failure_kind, "message": failure_message}
    else:
        raise ObservationError("invalid_correction", "Correction status is invalid")
    return append_event(
        campaign_dir,
        {
            "event_type": "correction",
            "phase": phase,
            "recorded_at": format_utc(now()),
            "scheduled_at_value": format_utc(scheduled_at(campaign, phase)),
            "observed_at": observed_at,
            "observation_status": observation_status,
            "repository_star_count": repository_star_count,
            "source": {
                "api_url": source_url,
                "response_date": None,
                "etag": None,
            },
            "failure": failure,
            "supersedes_sequence": supersedes_sequence,
            "correction_reason": reason,
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record append-only post-release repository Star counts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    baseline = subparsers.add_parser("baseline")
    baseline.add_argument(
        "--adoption-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs/evidence/adoption",
    )
    baseline.add_argument("--campaign-id", required=True)
    baseline.add_argument("--repository", required=True)
    baseline.add_argument("--release-tag", required=True)
    observe = subparsers.add_parser("observe")
    observe.add_argument("--campaign-dir", required=True, type=Path)
    observe.add_argument("--phase", required=True, choices=("baseline", "t30"))
    correct = subparsers.add_parser("correct")
    correct.add_argument("--campaign-dir", required=True, type=Path)
    correct.add_argument("--supersedes-sequence", required=True, type=int)
    correct.add_argument(
        "--status", required=True, choices=("observed", "observation_failed")
    )
    correct.add_argument("--observed-at", required=True)
    correct.add_argument("--source-url", required=True)
    correct.add_argument("--reason", required=True)
    correct.add_argument("--repository-star-count", type=int)
    correct.add_argument("--failure-kind")
    correct.add_argument("--failure-message")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api = GitHubApi(token=os.environ.get("GITHUB_TOKEN"))
    try:
        if args.command == "baseline":
            report = initialize_campaign(
                args.adoption_root,
                args.campaign_id,
                args.repository,
                args.release_tag,
                api=api,
                now=utc_now,
            )
        elif args.command == "observe":
            report = record_observation(
                args.campaign_dir, args.phase, api=api, now=utc_now
            )
        else:
            report = record_correction(
                args.campaign_dir,
                supersedes_sequence=args.supersedes_sequence,
                observation_status=args.status,
                repository_star_count=args.repository_star_count,
                observed_at=args.observed_at,
                source_url=args.source_url,
                failure_kind=args.failure_kind,
                failure_message=args.failure_message,
                reason=args.reason,
                now=utc_now,
            )
    except ObservationError as error:
        payload = {
            "ok": False,
            "error": {"kind": error.kind, "message": error.safe_message},
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
