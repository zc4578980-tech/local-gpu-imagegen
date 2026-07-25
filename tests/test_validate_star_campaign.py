from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_star_campaign import (  # noqa: E402
    CAMPAIGN_FIELDS,
    EVENT_FIELDS,
    canonical_json,
    event_sha256,
    make_event,
    validate_campaign,
)


PUBLISHED = "2026-07-25T12:00:00Z"
T30 = "2026-08-24T12:00:00Z"


def campaign_document(
    campaign_id: str = "v0.8.0-release-123456",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "repository": "owner/local-gpu-imagegen",
        "release": {
            "id": 123456,
            "tag_name": "v0.8.0",
            "html_url": (
                "https://github.com/owner/local-gpu-imagegen/"
                "releases/tag/v0.8.0"
            ),
            "published_at": PUBLISHED,
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


def source() -> dict[str, object]:
    return {
        "api_url": "https://api.github.com/repos/owner/local-gpu-imagegen",
        "response_date": "2026-07-25T12:01:00Z",
        "etag": '"fixture-etag"',
    }


def write_campaign(root: Path) -> Path:
    directory = root / "v0.8.0-release-123456"
    directory.mkdir()
    (directory / "campaign.json").write_text(
        json.dumps(campaign_document(), indent=2) + "\n",
        encoding="utf-8",
    )
    (directory / "events.jsonl").write_text("", encoding="ascii")
    return directory


def append_event(directory: Path, **overrides: object) -> dict[str, object]:
    lines = (directory / "events.jsonl").read_text(
        encoding="ascii"
    ).splitlines()
    prior = json.loads(lines[-1]) if lines else None
    values: dict[str, object] = {
        "sequence": len(lines) + 1,
        "event_type": "observation",
        "phase": "baseline" if not lines else "t30",
        "recorded_at": (
            "2026-07-25T12:01:00Z" if not lines else "2026-08-24T12:10:00Z"
        ),
        "scheduled_at_value": PUBLISHED if not lines else T30,
        "observed_at": (
            "2026-07-25T12:01:00Z" if not lines else "2026-08-24T12:10:00Z"
        ),
        "observation_status": "observed",
        "repository_star_count": 10 if not lines else 110,
        "source": source(),
        "failure": None,
        "supersedes_sequence": None,
        "correction_reason": None,
        "previous_event_sha256": (
            None if prior is None else prior["event_sha256"]
        ),
    }
    values.update(overrides)
    event = make_event(**values)
    with (directory / "events.jsonl").open(
        "a", encoding="ascii", newline="\n"
    ) as handle:
        handle.write(canonical_json(event).decode("ascii") + "\n")
    return event


class StarCampaignValidationTests(unittest.TestCase):
    def test_empty_valid_campaign_is_measurement_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = validate_campaign(write_campaign(Path(temporary)))
        self.assertTrue(report["ok"])
        self.assertEqual(report["outcome"], "measurement_incomplete")
        self.assertIsNone(report["net_new_stars"])

    def test_reports_goal_met_and_goal_missed_for_non_monotonic_counts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            met = write_campaign(Path(temporary))
            append_event(met)
            append_event(met)
            met_report = validate_campaign(met)
        self.assertEqual(met_report["outcome"], "goal_met")
        self.assertEqual(met_report["net_new_stars"], 100)

        with tempfile.TemporaryDirectory() as temporary:
            missed = write_campaign(Path(temporary))
            append_event(missed)
            append_event(missed, repository_star_count=7)
            missed_report = validate_campaign(missed)
        self.assertEqual(missed_report["outcome"], "goal_missed")
        self.assertEqual(missed_report["net_new_stars"], -3)

    def test_baseline_after_five_minutes_is_degraded_but_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(directory, observed_at="2026-07-25T12:05:01Z")
            append_event(directory)
            report = validate_campaign(directory)
        self.assertTrue(report["ok"])
        self.assertEqual(report["baseline_quality"], "degraded")
        self.assertEqual(report["outcome"], "goal_met")

    def test_early_and_late_t30_are_retained_but_incomplete(self) -> None:
        cases = (
            ("2026-08-24T11:59:59Z", "early"),
            ("2026-08-25T12:00:01Z", "late"),
        )
        for observed_at, quality in cases:
            with self.subTest(quality=quality), tempfile.TemporaryDirectory() as tmp:
                directory = write_campaign(Path(tmp))
                append_event(directory)
                append_event(directory, observed_at=observed_at)
                report = validate_campaign(directory)
                self.assertTrue(report["ok"])
                self.assertEqual(report["t30_quality"], quality)
                self.assertEqual(report["outcome"], "measurement_incomplete")
                self.assertIsNone(report["t30_count"])

    def test_failed_observation_is_valid_history_but_not_a_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(
                directory,
                observation_status="observation_failed",
                repository_star_count=None,
                failure={
                    "kind": "http_error",
                    "message": "GitHub returned HTTP 503",
                },
            )
            report = validate_campaign(directory)
        self.assertTrue(report["ok"])
        self.assertEqual(report["baseline_quality"], "failed")
        self.assertEqual(report["outcome"], "measurement_incomplete")

    def test_correction_must_supersede_current_effective_same_phase_event(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(directory)
            append_event(
                directory,
                event_type="correction",
                phase="baseline",
                scheduled_at_value=PUBLISHED,
                observed_at="2026-07-25T12:02:00Z",
                repository_star_count=11,
                supersedes_sequence=1,
                correction_reason=(
                    "Corrected transcription from the same API response."
                ),
            )
            self.assertTrue(validate_campaign(directory)["ok"])
            append_event(
                directory,
                event_type="correction",
                phase="baseline",
                scheduled_at_value=PUBLISHED,
                supersedes_sequence=1,
                correction_reason="Stale correction target.",
            )
            self.assertIn(
                "invalid_correction_target",
                validate_campaign(directory)["findings"],
            )

        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(directory)
            append_event(
                directory,
                event_type="correction",
                phase="t30",
                supersedes_sequence=1,
                correction_reason="Wrong phase.",
            )
            self.assertIn(
                "correction_phase_mismatch",
                validate_campaign(directory)["findings"],
            )

    def test_rejects_tamper_noncanonical_line_broken_hash_and_bad_sequence(
        self,
    ) -> None:
        def count_tamper(
            events: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            events[0]["repository_star_count"] = 99
            return events

        def broken_link(
            events: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            events[1]["previous_event_sha256"] = "0" * 64
            events[1]["event_sha256"] = event_sha256(events[1])
            return events

        def bad_sequence(
            events: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            events[1]["sequence"] = 3
            events[1]["event_sha256"] = event_sha256(events[1])
            return events

        cases: tuple[
            tuple[
                Callable[
                    [list[dict[str, object]]],
                    list[dict[str, object]],
                ],
                str,
            ],
            ...,
        ] = (
            (count_tamper, "event_sha256_mismatch"),
            (broken_link, "previous_event_sha256_mismatch"),
            (bad_sequence, "invalid_event_sequence"),
        )
        for mutate, finding in cases:
            with self.subTest(finding=finding), tempfile.TemporaryDirectory() as tmp:
                directory = write_campaign(Path(tmp))
                append_event(directory)
                append_event(directory)
                path = directory / "events.jsonl"
                events = [
                    json.loads(line)
                    for line in path.read_text(encoding="ascii").splitlines()
                ]
                path.write_text(
                    "".join(
                        canonical_json(event).decode("ascii") + "\n"
                        for event in mutate(events)
                    ),
                    encoding="ascii",
                    newline="\n",
                )
                self.assertIn(finding, validate_campaign(directory)["findings"])

        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            append_event(directory)
            path = directory / "events.jsonl"
            path.write_text(
                path.read_text(encoding="ascii").rstrip("\n") + " \n",
                encoding="ascii",
            )
            self.assertIn(
                "noncanonical_event_line",
                validate_campaign(directory)["findings"],
            )

    def test_rejects_unknown_fields_identity_keys_bad_campaign_policy_and_path(
        self,
    ) -> None:
        def add_unknown(document: dict[str, object]) -> None:
            document["unexpected"] = True

        def change_goal(document: dict[str, object]) -> None:
            goal = document["goal"]
            assert isinstance(goal, dict)
            goal["target"] = 99

        def change_grace(document: dict[str, object]) -> None:
            goal = document["goal"]
            assert isinstance(goal, dict)
            goal["baseline_grace_seconds"] = 301

        def change_events_file(document: dict[str, object]) -> None:
            document["events_file"] = "other.jsonl"

        def change_id(document: dict[str, object]) -> None:
            document["campaign_id"] = "other"

        mutations = (
            (add_unknown, "invalid_campaign_fields"),
            (change_goal, "invalid_goal_policy"),
            (change_grace, "invalid_goal_policy"),
            (change_events_file, "invalid_events_file"),
            (change_id, "campaign_id_path_mismatch"),
        )
        for mutate, finding in mutations:
            with self.subTest(finding=finding), tempfile.TemporaryDirectory() as tmp:
                directory = write_campaign(Path(tmp))
                document = campaign_document()
                mutate(document)
                (directory / "campaign.json").write_text(
                    json.dumps(document) + "\n",
                    encoding="utf-8",
                )
                self.assertIn(
                    finding,
                    validate_campaign(directory)["findings"],
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            event = append_event(directory)
            event["stargazer_login"] = "forbidden"
            event["event_sha256"] = event_sha256(event)
            (directory / "events.jsonl").write_text(
                canonical_json(event).decode("ascii") + "\n",
                encoding="ascii",
            )
            self.assertIn(
                "identity_field_forbidden",
                validate_campaign(directory)["findings"],
            )

    def test_schema_documents_are_closed_and_parse_as_strict_json(self) -> None:
        schemas = ROOT / "docs" / "evidence" / "schemas"
        for name in ("star-campaign.schema.json", "star-event.schema.json"):
            with self.subTest(name=name):
                schema = json.loads(
                    (schemas / name).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    schema["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )
                self.assertFalse(schema["additionalProperties"])
        campaign_schema = json.loads(
            (schemas / "star-campaign.schema.json").read_text(encoding="utf-8")
        )
        event_schema = json.loads(
            (schemas / "star-event.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(campaign_schema["required"]), CAMPAIGN_FIELDS)
        self.assertEqual(set(event_schema["required"]), EVENT_FIELDS)
        self.assertFalse(
            campaign_schema["properties"]["release"]["additionalProperties"]
        )
        self.assertFalse(
            campaign_schema["properties"]["goal"]["additionalProperties"]
        )
        self.assertFalse(
            event_schema["properties"]["source"]["additionalProperties"]
        )
        self.assertFalse(
            event_schema["properties"]["failure"]["additionalProperties"]
        )
        self.assertEqual(
            campaign_schema["properties"]["release"]["properties"]
            ["published_at"]["pattern"],
            "Z$",
        )
        for field in ("recorded_at", "scheduled_at", "observed_at"):
            self.assertEqual(
                event_schema["properties"][field]["pattern"],
                "Z$",
            )
        self.assertEqual(
            event_schema["properties"]["source"]["properties"]
            ["response_date"]["pattern"],
            "Z$",
        )

    def test_strict_loaders_reject_ambiguous_or_noncanonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            campaign_path = directory / "campaign.json"
            campaign_path.write_text(
                '{"campaign_id":"first","campaign_id":"second"}\n',
                encoding="utf-8",
            )
            self.assertIn(
                "duplicate_json_key",
                validate_campaign(directory)["findings"],
            )

        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            campaign_path = directory / "campaign.json"
            campaign_path.write_bytes(
                b"\xef\xbb\xbf" + campaign_path.read_bytes()
            )
            self.assertIn(
                "invalid_campaign_json",
                validate_campaign(directory)["findings"],
            )

        cases = (
            (b"\xff\n", "invalid_event_encoding"),
            (b"\n", "blank_event_line"),
            (b"[]\n", "invalid_event_json"),
            (b'{"sequence":1,"sequence":2}\n', "duplicate_json_key"),
            (b"{}", "noncanonical_event_line"),
        )
        for encoded, finding in cases:
            with self.subTest(finding=finding), tempfile.TemporaryDirectory() as tmp:
                directory = write_campaign(Path(tmp))
                (directory / "events.jsonl").write_bytes(encoded)
                self.assertIn(
                    finding,
                    validate_campaign(directory)["findings"],
                )

    def test_cli_returns_zero_for_incomplete_valid_history_and_nonzero_for_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_campaign(Path(temporary))
            valid = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_star_campaign.py"),
                    str(directory),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(
                json.loads(valid.stdout)["outcome"],
                "measurement_incomplete",
            )
            append_event(directory)
            path = directory / "events.jsonl"
            path.write_text(
                path.read_text(encoding="ascii").replace(
                    '"repository_star_count":10',
                    '"repository_star_count":11',
                ),
                encoding="ascii",
            )
            invalid = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_star_campaign.py"),
                    str(directory),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(invalid.returncode, 1)
            self.assertFalse(json.loads(invalid.stderr)["ok"])


if __name__ == "__main__":
    unittest.main()
