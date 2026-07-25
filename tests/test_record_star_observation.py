from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from record_star_observation import (  # noqa: E402
    ApiResult,
    GitHubApi,
    ObservationError,
    _SameHostRedirect,
    initialize_campaign,
    main,
    record_correction,
    record_observation,
)
from validate_star_campaign import canonical_json, validate_campaign  # noqa: E402


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._stream = io.BytesIO(body)
        self._url = url
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url


class FakeApi:
    def __init__(self, responses: dict[str, ApiResult | Exception]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get_json(self, url: str) -> ApiResult:
        self.urls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> FakeResponse:
        self.calls.append((request, timeout))
        return self.response


REPOSITORY_URL = "https://api.github.com/repos/owner/local-gpu-imagegen"
RELEASE_URL = REPOSITORY_URL + "/releases/tags/v0.8.0"
BASELINE_NOW = datetime(2026, 7, 25, 12, 1, tzinfo=timezone.utc)
T30_NOW = datetime(2026, 8, 24, 12, 10, tzinfo=timezone.utc)


def release_result(**overrides: object) -> ApiResult:
    document: dict[str, object] = {
        "id": 123456,
        "tag_name": "v0.8.0",
        "html_url": (
            "https://github.com/owner/local-gpu-imagegen/releases/tag/v0.8.0"
        ),
        "published_at": "2026-07-25T12:00:00Z",
        "draft": False,
    }
    document.update(overrides)
    return ApiResult(
        document,
        "2026-07-25T12:00:30Z",
        '"release-etag"',
    )


def repository_result(count: int = 10) -> ApiResult:
    return ApiResult(
        {
            "full_name": "owner/local-gpu-imagegen",
            "stargazers_count": count,
        },
        "2026-07-25T12:01:00Z",
        '"repository-etag"',
    )


def initialize(root: Path, api: FakeApi | None = None) -> tuple[Path, FakeApi]:
    fake = api or FakeApi(
        {
            RELEASE_URL: release_result(),
            REPOSITORY_URL: repository_result(),
        }
    )
    report = initialize_campaign(
        root,
        "v0.8.0-release-123456",
        "owner/local-gpu-imagegen",
        "v0.8.0",
        api=fake,
        now=lambda: BASELINE_NOW,
    )
    if not report["ok"]:
        raise AssertionError(report)
    return root / "v0.8.0-release-123456", fake


class StarObservationRecorderTests(unittest.TestCase):
    def test_baseline_binds_published_release_and_appends_repository_count(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory, api = initialize(Path(temporary))
            campaign = json.loads(
                (directory / "campaign.json").read_text(encoding="utf-8")
            )
            stored = (directory / "events.jsonl").read_text(encoding="ascii")
            lines = stored.splitlines()
            report = validate_campaign(directory)
        release = campaign["release"]
        goal = campaign["goal"]
        assert isinstance(release, dict)
        assert isinstance(goal, dict)
        self.assertEqual(release["published_at"], "2026-07-25T12:00:00Z")
        self.assertEqual(goal["target"], 100)
        self.assertEqual(api.urls, [RELEASE_URL, REPOSITORY_URL])
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            lines[0],
            canonical_json(json.loads(lines[0])).decode("ascii"),
        )
        self.assertEqual(report["baseline_count"], 10)
        self.assertEqual(report["baseline_quality"], "on_time")
        for forbidden in ("stargazer_login", "account_id", "email", "token"):
            self.assertNotIn(forbidden, stored.casefold())

    def test_baseline_rejects_draft_missing_publication_and_reuse(self) -> None:
        for result in (
            release_result(draft=True),
            release_result(published_at=None),
        ):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                api = FakeApi({RELEASE_URL: result})
                with self.assertRaises(ObservationError):
                    initialize_campaign(
                        root,
                        "v0.8.0-release-123456",
                        "owner/local-gpu-imagegen",
                        "v0.8.0",
                        api=api,
                        now=lambda: BASELINE_NOW,
                    )
                self.assertFalse((root / "v0.8.0-release-123456").exists())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, api = initialize(root)
            original = (directory / "campaign.json").read_bytes()
            with self.assertRaises(ObservationError) as caught:
                initialize_campaign(
                    root,
                    directory.name,
                    "owner/local-gpu-imagegen",
                    "v0.8.0",
                    api=api,
                    now=lambda: BASELINE_NOW,
                )
            self.assertEqual(caught.exception.kind, "campaign_exists")
            self.assertEqual((directory / "campaign.json").read_bytes(), original)

    def test_repository_failure_after_campaign_creation_is_appended(self) -> None:
        failures = (
            ObservationError("http_error", "GitHub returned HTTP 503"),
            ObservationError(
                "repository_mismatch",
                "Repository identity did not match",
            ),
        )
        for failure in failures:
            with self.subTest(kind=failure.kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                api = FakeApi(
                    {
                        RELEASE_URL: release_result(),
                        REPOSITORY_URL: failure,
                    }
                )
                report = initialize_campaign(
                    root,
                    "v0.8.0-release-123456",
                    "owner/local-gpu-imagegen",
                    "v0.8.0",
                    api=api,
                    now=lambda: BASELINE_NOW,
                )
                directory = root / "v0.8.0-release-123456"
                event = json.loads(
                    (directory / "events.jsonl").read_text(encoding="ascii")
                )
                self.assertTrue(report["ok"])
                self.assertEqual(report["outcome"], "measurement_incomplete")
                self.assertEqual(
                    event["observation_status"],
                    "observation_failed",
                )
                self.assertEqual(event["failure"]["kind"], failure.kind)
                self.assertIsNone(event["repository_star_count"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = FakeApi(
                {
                    RELEASE_URL: release_result(),
                    REPOSITORY_URL: ApiResult(
                        {
                            "full_name": "other/repository",
                            "stargazers_count": True,
                        },
                        None,
                        None,
                    ),
                }
            )
            report = initialize_campaign(
                root,
                "v0.8.0-release-123456",
                "owner/local-gpu-imagegen",
                "v0.8.0",
                api=api,
                now=lambda: BASELINE_NOW,
            )
            directory = root / "v0.8.0-release-123456"
            event = json.loads(
                (directory / "events.jsonl").read_text(encoding="ascii")
            )
            self.assertTrue(report["ok"])
            self.assertEqual(event["failure"]["kind"], "repository_mismatch")

    def test_observe_appends_t30_without_rewriting_prior_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory, _ = initialize(Path(temporary))
            campaign_before = (directory / "campaign.json").read_bytes()
            events_before = (directory / "events.jsonl").read_bytes()
            report = record_observation(
                directory,
                "t30",
                api=FakeApi({REPOSITORY_URL: repository_result(115)}),
                now=lambda: T30_NOW,
            )
            campaign_after = (directory / "campaign.json").read_bytes()
            events_after = (directory / "events.jsonl").read_bytes()
        self.assertEqual(campaign_after, campaign_before)
        self.assertTrue(events_after.startswith(events_before))
        self.assertEqual(len(events_after.splitlines()), 2)
        self.assertEqual(report["net_new_stars"], 105)
        self.assertEqual(report["outcome"], "goal_met")

    def test_correction_appends_and_rejects_stale_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory, _ = initialize(Path(temporary))
            report = record_correction(
                directory,
                supersedes_sequence=1,
                observation_status="observed",
                repository_star_count=11,
                observed_at="2026-07-25T12:01:00Z",
                source_url=REPOSITORY_URL,
                failure_kind=None,
                failure_message=None,
                reason=(
                    "Corrected a transcription error against the retained "
                    "API response."
                ),
                now=lambda: BASELINE_NOW,
            )
            effective = report["effective_sequences"]
            assert isinstance(effective, dict)
            self.assertEqual(effective["baseline"], 2)
            before = (directory / "events.jsonl").read_bytes()
            with self.assertRaises(ObservationError) as caught:
                record_correction(
                    directory,
                    supersedes_sequence=1,
                    observation_status="observed",
                    repository_star_count=12,
                    observed_at="2026-07-25T12:01:00Z",
                    source_url=REPOSITORY_URL,
                    failure_kind=None,
                    failure_message=None,
                    reason="Stale target.",
                    now=lambda: BASELINE_NOW,
                )
            self.assertEqual(
                caught.exception.kind,
                "invalid_correction_target",
            )
            self.assertEqual((directory / "events.jsonl").read_bytes(), before)

    def test_correction_rejects_invalid_metadata_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory, _ = initialize(Path(temporary))
            before = (directory / "events.jsonl").read_bytes()
            with self.assertRaises(ObservationError) as caught:
                record_correction(
                    directory,
                    supersedes_sequence=1,
                    observation_status="observed",
                    repository_star_count=11,
                    observed_at="2026-07-25T12:01:00Z",
                    source_url=REPOSITORY_URL,
                    failure_kind=None,
                    failure_message=None,
                    reason="Invalid\nmultiline reason.",
                    now=lambda: BASELINE_NOW,
                )
            self.assertEqual(caught.exception.kind, "invalid_correction")
            self.assertEqual((directory / "events.jsonl").read_bytes(), before)

    def test_append_refuses_invalid_history_and_lock_contention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory, _ = initialize(Path(temporary))
            events = directory / "events.jsonl"
            events.write_text(
                events.read_text(encoding="ascii").replace(
                    '"repository_star_count":10',
                    '"repository_star_count":11',
                ),
                encoding="ascii",
            )
            before = events.read_bytes()
            with self.assertRaises(ObservationError) as caught:
                record_observation(
                    directory,
                    "t30",
                    api=FakeApi({REPOSITORY_URL: repository_result(115)}),
                    now=lambda: T30_NOW,
                )
            self.assertEqual(caught.exception.kind, "invalid_history")
            self.assertEqual(events.read_bytes(), before)

        with tempfile.TemporaryDirectory() as temporary:
            directory, _ = initialize(Path(temporary))
            lock = directory / "events.jsonl.lock"
            lock.write_text("held", encoding="ascii")
            before = (directory / "events.jsonl").read_bytes()
            with self.assertRaises(ObservationError) as caught:
                record_observation(
                    directory,
                    "t30",
                    api=FakeApi({REPOSITORY_URL: repository_result(115)}),
                    now=lambda: T30_NOW,
                )
            self.assertEqual(caught.exception.kind, "lock_unavailable")
            self.assertEqual((directory / "events.jsonl").read_bytes(), before)
            self.assertEqual(lock.read_text(encoding="ascii"), "held")

        with tempfile.TemporaryDirectory() as temporary:
            directory, _ = initialize(Path(temporary))
            lock = directory / "events.jsonl.lock"
            with mock.patch(
                "record_star_observation.os.write",
                side_effect=OSError("simulated lock write failure"),
            ), self.assertRaises(OSError):
                record_observation(
                    directory,
                    "t30",
                    api=FakeApi({REPOSITORY_URL: repository_result(115)}),
                    now=lambda: T30_NOW,
                )
            self.assertFalse(lock.exists())

    def test_github_api_is_get_only_bounded_and_rejects_redirect_hosts(
        self,
    ) -> None:
        payload = json.dumps(
            {
                "full_name": "owner/local-gpu-imagegen",
                "stargazers_count": 10,
            }
        ).encode()
        response = FakeResponse(
            payload,
            url=REPOSITORY_URL,
            headers={
                "Date": "Sat, 25 Jul 2026 12:01:00 GMT",
                "ETag": '"etag"',
            },
        )
        opener = FakeOpener(response)
        with mock.patch("urllib.request.build_opener", return_value=opener):
            result = GitHubApi().get_json(REPOSITORY_URL)
        request = opener.calls[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request.get_header("Accept"),
            "application/vnd.github+json",
        )
        self.assertEqual(
            request.get_header("User-agent"),
            "local-gpu-imagegen-star-recorder/1.0",
        )
        self.assertEqual(
            request.get_header("X-github-api-version"),
            "2022-11-28",
        )
        self.assertEqual(result.document["stargazers_count"], 10)

        opener = FakeOpener(
            FakeResponse(
                payload,
                url="https://example.com/repos/owner/repo",
            )
        )
        with mock.patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ObservationError) as caught:
                GitHubApi().get_json(REPOSITORY_URL)
            self.assertEqual(caught.exception.kind, "redirect_host_rejected")

        opener = FakeOpener(FakeResponse(b"x" * 9, url=REPOSITORY_URL))
        with mock.patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ObservationError) as caught:
                GitHubApi(max_response_bytes=8).get_json(REPOSITORY_URL)
            self.assertEqual(caught.exception.kind, "response_too_large")

        opener = FakeOpener(
            FakeResponse(
                b"{}",
                url=REPOSITORY_URL,
                headers={"Content-Length": "9"},
            )
        )
        with mock.patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ObservationError) as caught:
                GitHubApi(max_response_bytes=8).get_json(REPOSITORY_URL)
            self.assertEqual(caught.exception.kind, "response_too_large")

        for body, kind in (
            (b"{", "invalid_json"),
            (b"[]", "invalid_json_object"),
        ):
            opener = FakeOpener(FakeResponse(body, url=REPOSITORY_URL))
            with self.subTest(kind=kind), mock.patch(
                "urllib.request.build_opener", return_value=opener
            ):
                with self.assertRaises(ObservationError) as caught:
                    GitHubApi().get_json(REPOSITORY_URL)
                self.assertEqual(caught.exception.kind, kind)

        redirect = _SameHostRedirect()
        original = urllib.request.Request(
            REPOSITORY_URL,
            headers={"Authorization": "Bearer sentinel"},
        )
        with self.assertRaises(ObservationError) as caught:
            redirect.redirect_request(
                original,
                None,
                302,
                "Found",
                {},
                "https://example.com/repos/owner/repository",
            )
        self.assertEqual(caught.exception.kind, "redirect_host_rejected")

    def test_environment_token_is_authorization_only_and_never_persisted_or_printed(
        self,
    ) -> None:
        token = "sentinel-secret-token"
        payload = json.dumps({"ok": True}).encode()
        opener = FakeOpener(FakeResponse(payload, url=REPOSITORY_URL))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": token}), mock.patch(
            "urllib.request.build_opener", return_value=opener
        ):
            GitHubApi(token=token).get_json(REPOSITORY_URL)
            error = ObservationError(
                "http_error",
                f"request failed with {token}",
            )
        request = opener.calls[0][0]
        self.assertEqual(
            request.get_header("Authorization"),
            f"Bearer {token}",
        )
        self.assertNotIn(token, error.safe_message)
        self.assertNotIn(token, repr(error))

    def test_cli_baseline_observe_and_correct_emit_json_without_committing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = FakeApi(
                {
                    RELEASE_URL: release_result(),
                    REPOSITORY_URL: repository_result(),
                }
            )
            with mock.patch(
                "record_star_observation.GitHubApi",
                return_value=fake,
            ), mock.patch(
                "record_star_observation.utc_now",
                return_value=BASELINE_NOW,
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = main(
                    [
                        "baseline",
                        "--adoption-root",
                        str(root),
                        "--campaign-id",
                        "v0.8.0-release-123456",
                        "--repository",
                        "owner/local-gpu-imagegen",
                        "--release-tag",
                        "v0.8.0",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(stdout.getvalue())["ok"])
            directory = root / "v0.8.0-release-123456"

            with mock.patch(
                "record_star_observation.GitHubApi",
                return_value=FakeApi(
                    {REPOSITORY_URL: repository_result(115)}
                ),
            ), mock.patch(
                "record_star_observation.utc_now",
                return_value=T30_NOW,
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = main(
                    [
                        "observe",
                        "--campaign-dir",
                        str(directory),
                        "--phase",
                        "t30",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(stdout.getvalue())["outcome"],
                "goal_met",
            )

            with mock.patch(
                "record_star_observation.utc_now",
                return_value=BASELINE_NOW,
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = main(
                    [
                        "correct",
                        "--campaign-dir",
                        str(directory),
                        "--supersedes-sequence",
                        "1",
                        "--status",
                        "observed",
                        "--observed-at",
                        "2026-07-25T12:01:00Z",
                        "--source-url",
                        REPOSITORY_URL,
                        "--reason",
                        "Corrected transcription.",
                        "--repository-star-count",
                        "11",
                    ]
                )
            self.assertEqual(code, 0)
            effective = json.loads(stdout.getvalue())["effective_sequences"]
            self.assertEqual(effective["baseline"], 3)
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {directory.name},
            )
            self.assertFalse(any(path.name == ".git" for path in root.rglob("*")))


if __name__ == "__main__":
    unittest.main()
