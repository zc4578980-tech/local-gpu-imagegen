from __future__ import annotations

import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backends.comfyui import ComfyUIAdapter  # noqa: E402
from local_gpu_imagegen.errors import (  # noqa: E402
    ArtifactError,
    ConflictError,
    StateError,
    ValidationError,
)
from local_gpu_imagegen.workflow_templates import WorkflowTemplateRegistry  # noqa: E402
from tests.fake_backend_server import FakeBackendServer, FakeResponse  # noqa: E402


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
MODEL = "anything-v5.safetensors"
UNET_MODEL = "z_image_turbo_nvfp4.safetensors"


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class ComfyUIAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary_directory.name) / "output.png"
        self.server_context = FakeBackendServer()
        self.server = self.server_context.__enter__()
        self.server.routes[("GET", "/system_stats")] = FakeResponse.json({
            "system": {"comfyui_version": "0.3.50"},
            "devices": [],
        })
        self.server.routes[("GET", "/object_info/CheckpointLoaderSimple")] = FakeResponse.json({
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {
                        "ckpt_name": [[MODEL], {"tooltip": "models"}],
                    }
                }
            }
        })
        self.server.routes[("GET", "/object_info/UNETLoader")] = FakeResponse.json({
            "UNETLoader": {
                "input": {
                    "required": {
                        "unet_name": [[UNET_MODEL], {"tooltip": "models"}],
                    }
                }
            }
        })
        self.server.routes[("POST", "/prompt")] = FakeResponse.json({
            "prompt_id": "prompt-1",
            "number": 1,
            "node_errors": {},
        })
        self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json(
            self.completed_history()
        )
        self.server.routes[("GET", "/queue")] = FakeResponse.json({
            "queue_running": [],
            "queue_pending": [],
        })
        self.server.routes[(
            "GET",
            "/view?filename=result.png&subfolder=&type=output",
        )] = FakeResponse(body=PNG_BYTES, headers={"Content-Type": "image/png"})
        self.server.routes[("POST", "/queue")] = FakeResponse.json({})
        self.adapter = ComfyUIAdapter(
            self.server.url,
            poll_interval=0,
            timeout=5,
            sleep=lambda _seconds: None,
        )
        registry = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            Path(self.temporary_directory.name) / "state",
        )
        self.workflow = registry.resolve(
            "sd15-txt2img",
            MODEL,
            "txt2img",
            {
                "positive_prompt": "calm sea",
                "negative_prompt": "artifacts",
                "seed": 42,
                "steps": 20,
                "guidance_scale": 7.0,
                "sampler": "euler",
                "scheduler": "normal",
                "width": 512,
                "height": 512,
            },
        )
        discovered = self.adapter.discover()
        self.model = discovered[0]
        self.unet_model = discovered[1]
        self.server.requests.clear()

    def tearDown(self) -> None:
        self.server_context.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    @staticmethod
    def completed_history(
        *,
        filename: str = "result.png",
        subfolder: str = "",
        output_type: str = "output",
        output_node: str = "9",
    ) -> dict[str, object]:
        return {
            "prompt-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    output_node: {
                        "images": [{
                            "filename": filename,
                            "subfolder": subfolder,
                            "type": output_type,
                        }]
                    }
                },
            }
        }

    def request(self, **changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "backend": "comfyui",
            "idempotency_key": "test-attempt",
            "mode": "txt2img",
            "model": copy.deepcopy(self.model),
            "workflow": copy.deepcopy(self.workflow),
            "positive_prompt": "calm sea",
            "negative_prompt": "artifacts",
            "width": 512,
            "height": 512,
            "steps": 20,
            "guidance_scale": 7.0,
            "sampler": "euler",
            "scheduler": "normal",
            "seed": 42,
            "output_path": str(self.output),
            "prompt_compiler_id": "sd15-tags-v1",
            "prompt_compiler_version": 1,
        }
        value.update(changes)
        return value

    def test_probe_reports_version_and_frozen_endpoint(self) -> None:
        report = self.adapter.probe()

        self.assertEqual(report["backend"], "comfyui")
        self.assertEqual(report["implementation"], "ComfyUI")
        self.assertEqual(report["version"], "0.3.50")
        self.assertEqual(report["endpoint_identity"], self.adapter.endpoint_identity)
        self.assertTrue(report["ready"])

    def test_discovery_uses_checkpoint_choices_without_mutation(self) -> None:
        records = self.adapter.discover()

        self.assertEqual([item["backend_model_id"] for item in records], [MODEL, UNET_MODEL])
        self.assertEqual(records[0]["identity_strength"], "backend_binding")
        self.assertEqual(records[0]["metadata"], {
            "loader_class": "CheckpointLoaderSimple",
            "loader_input": "ckpt_name",
        })
        self.assertEqual(records[1]["metadata"], {
            "loader_class": "UNETLoader",
            "loader_input": "unet_name",
        })
        self.assertFalse(any(item["method"] == "POST" for item in self.server.requests))

    def test_discovery_accepts_split_model_only_installation(self) -> None:
        self.server.routes[("GET", "/object_info/CheckpointLoaderSimple")] = FakeResponse.json({
            "CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [[]]}},
            }
        })

        records = self.adapter.discover()

        self.assertEqual([item["backend_model_id"] for item in records], [UNET_MODEL])
        self.assertEqual(records[0]["metadata"]["loader_class"], "UNETLoader")

    def test_generate_accepts_reviewed_unet_workflow(self) -> None:
        registry = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            Path(self.temporary_directory.name) / "z-state",
        )
        settings = {
            "positive_prompt": "cinematic observatory at dawn",
            "negative_prompt": "anatomy errors",
            "seed": 42,
            "steps": 8,
            "guidance_scale": 1.0,
            "sampler": "res_multistep",
            "scheduler": "simple",
            "width": 768,
            "height": 768,
        }
        workflow = registry.resolve(
            "z-image-turbo-txt2img",
            UNET_MODEL,
            "txt2img",
            settings,
        )
        self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json(
            self.completed_history(output_node="11")
        )

        result = self.adapter.generate(self.request(
            model=copy.deepcopy(self.unet_model),
            workflow=workflow,
            **settings,
        ))

        self.assertEqual(result["model"], UNET_MODEL)
        self.assertEqual(result["workflow_template_id"], "z-image-turbo-txt2img")
        submitted = json.loads(self.server.requests[0]["body"].decode("utf-8"))
        self.assertEqual(submitted["prompt"]["1"]["class_type"], "UNETLoader")

    def test_generate_submits_polls_and_retrieves_named_output(self) -> None:
        result = self.adapter.generate(self.request())

        self.assertEqual(result["backend"], "comfyui")
        self.assertEqual(result["workflow_job_id"], "prompt-1")
        self.assertEqual(result["model_identity_token"], self.model["identity_token"])
        self.assertEqual(Path(result["path"]).read_bytes(), PNG_BYTES)
        self.assertEqual(
            [item["path"] for item in self.server.requests],
            [
                "/prompt",
                "/history/prompt-1",
                "/view?filename=result.png&subfolder=&type=output",
            ],
        )
        submitted = json.loads(self.server.requests[0]["body"].decode("utf-8"))
        self.assertEqual(submitted["client_id"], "test-attempt")
        self.assertEqual(submitted["prompt"], self.workflow["graph"])

    def test_changed_model_or_unsafe_workflow_fails_before_submission(self) -> None:
        changed_model = copy.deepcopy(self.model)
        changed_model["identity_token"] = "model:" + "f" * 64
        unsafe_workflow = copy.deepcopy(self.workflow)
        unsafe_workflow["graph"]["10"] = {
            "class_type": "PythonScript",
            "inputs": {"code": "print(1)"},
        }
        invalid = (
            self.request(model=changed_model),
            self.request(workflow=unsafe_workflow),
        )
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(
                (ConflictError, ValidationError)
            ):
                self.adapter.generate(request)
            self.assertFalse(any(item["method"] == "POST" for item in self.server.requests))

    def test_submission_rejection_has_no_job_to_retry(self) -> None:
        self.server.routes[("POST", "/prompt")] = FakeResponse.json({
            "prompt_id": None,
            "node_errors": {"3": {"errors": ["invalid"]}},
        })

        with self.assertRaisesRegex(StateError, "comfyui_submission_rejected"):
            self.adapter.generate(self.request())

        self.assertEqual([item["path"] for item in self.server.requests], ["/prompt"])

    def test_timeout_queries_known_job_before_structured_failure(self) -> None:
        self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json({})
        self.server.routes[("GET", "/queue")] = FakeResponse.json({
            "queue_running": [],
            "queue_pending": [[1, "prompt-1", {}, {}, []]],
        })
        adapter = ComfyUIAdapter(
            self.server.url,
            poll_interval=0,
            timeout=0,
            clock=FakeClock([0, 1]),
            sleep=lambda _seconds: None,
        )

        with self.assertRaisesRegex(StateError, "comfyui_job_timed_out") as raised:
            adapter.generate(self.request())

        self.assertEqual(raised.exception.details["job_id"], "prompt-1")
        self.assertIn("/history/prompt-1", [item["path"] for item in self.server.requests])
        self.assertIn("/queue", [item["path"] for item in self.server.requests])
        self.assertEqual(
            len([item for item in self.server.requests if item["path"] == "/prompt"]),
            1,
        )

    def test_poll_tolerates_history_visibility_race_after_queue_clears(self) -> None:
        histories = iter(({}, self.completed_history()))

        def delayed_history(_method: str, _path: str, _body: bytes) -> FakeResponse:
            return FakeResponse.json(next(histories))

        self.server.routes[("GET", "/history/prompt-1")] = delayed_history

        result = self.adapter.generate(self.request())

        self.assertEqual(result["workflow_job_id"], "prompt-1")
        self.assertEqual(Path(result["path"]).read_bytes(), PNG_BYTES)
        self.assertEqual(
            [item["path"] for item in self.server.requests],
            [
                "/prompt",
                "/history/prompt-1",
                "/queue",
                "/history/prompt-1",
                "/view?filename=result.png&subfolder=&type=output",
            ],
        )

    def test_poll_still_rejects_a_job_absent_beyond_the_grace_window(self) -> None:
        self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json({})

        with self.assertRaisesRegex(StateError, "comfyui_job_disappeared"):
            self.adapter.generate(self.request())

        self.assertEqual(
            len([item for item in self.server.requests if item["path"] == "/prompt"]),
            1,
        )
        self.assertEqual(
            len([item for item in self.server.requests if item["path"] == "/history/prompt-1"]),
            5,
        )

    def test_query_and_cancel_only_delete_exact_queued_job(self) -> None:
        self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json({})
        self.server.routes[("GET", "/queue")] = FakeResponse.json({
            "queue_running": [],
            "queue_pending": [[1, "prompt-1", {}, {}, []]],
        })

        result = self.adapter.cancel_or_query("prompt-1", cancel=True)

        self.assertEqual(result["state"], "cancel_requested")
        posted = json.loads(self.server.requests[-1]["body"].decode("utf-8"))
        self.assertEqual(posted, {"delete": ["prompt-1"]})
        self.assertNotIn("/interrupt", [item["path"] for item in self.server.requests])

    def test_running_job_is_never_globally_interrupted(self) -> None:
        self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json({})
        self.server.routes[("GET", "/queue")] = FakeResponse.json({
            "queue_running": [[1, "prompt-1", {}, {}, []]],
            "queue_pending": [],
        })

        result = self.adapter.cancel_or_query("prompt-1", cancel=True)

        self.assertEqual(result["state"], "running")
        self.assertFalse(result["cancel_supported"])
        self.assertFalse(any(item["method"] == "POST" for item in self.server.requests))

    def test_disappeared_rejected_and_canceled_jobs_are_distinct(self) -> None:
        statuses = {
            "disappeared": {},
            "rejected": {
                "prompt-1": {"status": {"status_str": "error", "completed": True}}
            },
            "canceled": {
                "prompt-1": {"status": {"status_str": "canceled", "completed": True}}
            },
        }
        for expected, history in statuses.items():
            self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json(history)
            self.server.requests.clear()
            result = self.adapter.cancel_or_query("prompt-1")
            self.assertEqual(result["state"], expected)

    def test_wrong_output_node_or_traversal_metadata_never_writes_output(self) -> None:
        invalid = (
            self.completed_history(output_node="8"),
            self.completed_history(filename="../result.png"),
            self.completed_history(subfolder="../../private"),
            self.completed_history(output_type="temp"),
        )
        for history in invalid:
            self.server.routes[("GET", "/history/prompt-1")] = FakeResponse.json(history)
            self.server.requests.clear()
            with self.subTest(history=history), self.assertRaises(ArtifactError):
                self.adapter.generate(self.request())
            self.assertFalse(self.output.exists())

    def test_malformed_or_oversized_output_never_becomes_success(self) -> None:
        invalid = (b"not-a-png", b"x" * (32 * 1024 * 1024 + 1))
        for image in invalid:
            self.server.routes[(
                "GET",
                "/view?filename=result.png&subfolder=&type=output",
            )] = FakeResponse(body=image)
            self.server.requests.clear()
            with self.subTest(size=len(image)), self.assertRaises(ArtifactError):
                self.adapter.generate(self.request())
            self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
