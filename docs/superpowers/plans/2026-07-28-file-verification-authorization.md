# Fresh-Process File Verification Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a fresh MCP process restore one workflow-referenced model's cryptographic filesystem identity from a separately approved exact-path authorization without broad scanning or weakening trust.

**Architecture:** A user-local `FileVerificationRegistry` persists only exact path, backend model name, last approved digest/stat, status, and timestamps. `DiscoveryService` owns stat-only planning and bounded full-file verification, while runtime composition injects the registry and the existing `local_gpu_discover_models` tool exposes the new mode without increasing the 17-tool surface. Workflow trust, registration, route approval, and generation remain separate existing gates.

**Tech Stack:** Python 3.11/3.12 standard library, `unittest`, existing `atomic_write_json`, `fingerprint_selected_file`, MCP JSON schemas, Markdown contract tests.

## Global Constraints

- Start from `main@3fb45163ec61189c2d2c89a7c183612a55cb6058` only through worktree `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\.worktrees\codex-first-workflow-runner` on branch `codex/codex-first-workflow-runner`; do not touch root `main`'s unrelated untracked `.codex/`.
- Preserve cryptographic filesystem identity; never downgrade this path to `backend_binding` or private backend-only authority.
- Keep exactly 17 MCP tools. Add no tool, model, workflow, backend, downloader, GPU behavior, retry, fallback, or image-quality claim.
- The only production owners in this slice are `scripts/local_gpu_imagegen/file_verification.py`, `scripts/local_gpu_imagegen/discovery.py`, `scripts/local_gpu_imagegen/services.py`, and `scripts/mcp_server.py`.
- The new slice has a hard ceiling of 330 net production lines across those four files, approved after Task 1 review. Stop for design review before weakening validation or adding another owner if the ceiling is exceeded.
- Exact-file planning performs stat and path-safety checks only. Full SHA-256 happens only during exact-file verification execution.
- Never hash authorized files at process startup. Revalidate only the exact file referenced by the workflow currently requested.
- Accept exactly one local root and one explicit file when an active authorization cannot be uniquely resolved. Reject UNC/network paths, escapes, links, junctions, reparse points, directories, ambiguity, and model-name mismatch.
- A failed first hash writes no authorization. Drift never restores inventory; changed SHA-256 marks the old record `drifted` while retaining its last approved digest.
- Revocation only changes the selected authorization to `revoked`; it never deletes model bytes, workflow state, trust state, routes, or run evidence.
- Do not start ComfyUI, submit a prompt, use a GPU, download a model, or reuse run `20260728T075905Z-723ec652c855` or route `route:a6a27319ad83b7ed9f32c5f58197b43e19edf4ecdf58a0eea95f380f5fec50bf` during Tasks 1-5.
- Model-free tests must precede production changes. Run `python -m unittest discover -s tests -v` after relevant changes.

---

## File Structure

- Create `scripts/local_gpu_imagegen/file_verification.py`: strict registry schema, atomic persistence, exact authorization lookup, verified upsert, drift status, and revocation status.
- Modify `scripts/local_gpu_imagegen/discovery.py`: `exact_file/verify` and `exact_file/revoke` planning/execution, path/stat freezing, existing fingerprint reuse, inventory insertion only after success.
- Modify `scripts/local_gpu_imagegen/services.py`: construct one registry from `state_dir` and inject it into the shared `DiscoveryService`.
- Modify `scripts/mcp_server.py`: extend the existing discovery schema, forward exact-file fields, and allow confirmation omission only when the retained plan says a current active authorization permits it.
- Create `tests/test_file_verification.py`: registry schema, lookup, drift/revoke, corruption, credential, and atomic-write tests.
- Modify `tests/test_discovery.py`: exact-file plan/execute, safety, reuse, drift, revocation, and no-mutation tests.
- Modify `tests/test_runtime_services.py`: shared registry composition and a two-process restoration test.
- Modify `tests/test_mcp_server.py`: strict schema/dispatch/confirmation behavior and exactly-17 assertion.
- Modify `tests/test_skill_contract.py`, `tests/test_public_docs.py`: exact three-decision first-use and reduced later-use contracts.
- Modify `skills/local-gpu-imagegen/SKILL.md`, `docs/quickstart.md`, `docs/troubleshooting.md`, `docs/architecture.md`: user-visible sequence, cost, drift, recovery, and non-claims.
- Modify root continuity files only after verification: `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\PROJECT_NODES.md` and `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\NEXT_SESSION.md`.

---

### Task 1: FileVerificationRegistry

**Files:**
- Create: `scripts/local_gpu_imagegen/file_verification.py`
- Create: `tests/test_file_verification.py`
- Force-add: `docs/superpowers/plans/2026-07-28-file-verification-authorization.md`

**Interfaces:**
- Produces: `FileVerificationRegistry(state_dir: Path, *, now: Callable[[], str] | None = None)`.
- Produces: `resolve(*, backend_model_id: str | None = None, authorization_id: str | None = None, active_only: bool = True) -> dict[str, object] | None`; normal verification resolves only `active` records, revocation may resolve a named `drifted` record with `active_only=False`, zero matches returns `None`, and multiple matches raise `ambiguous_file_verification`.
- Produces: `record_verified(*, local_path: Path, resolved_root: Path, backend_model_id: str, fingerprint: dict[str, object]) -> dict[str, object]`; creates or refreshes one deterministic `verification:<24 lowercase hex>` authorization.
- Produces: `set_status(authorization_id: str, status: str) -> dict[str, object]`; accepts only `drifted` or `revoked` and retains the approved digest.
- Persists: `file-verifications.json` under the supplied user-local state directory with exactly the approved schema fields.

- [ ] **Step 1: Write registry RED tests**

Create `tests/test_file_verification.py` with these concrete cases:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ArtifactError, ValidationError  # noqa: E402
from local_gpu_imagegen.file_verification import FileVerificationRegistry  # noqa: E402


class FileVerificationRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temporary_directory.name) / "state"
        self.root = Path(self.temporary_directory.name) / "models"
        self.root.mkdir()
        self.model = self.root / "model.safetensors"
        self.model.write_bytes(b"model-bytes")
        self.registry = FileVerificationRegistry(
            self.state_dir,
            now=lambda: "2026-07-28T08:00:00Z",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def authorize(self, path: Path | None = None, model_id: str = "model.safetensors") -> dict[str, object]:
        selected = path or self.model
        file_stat = selected.stat()
        return self.registry.record_verified(
            local_path=selected,
            resolved_root=self.root,
            backend_model_id=model_id,
            fingerprint={
                "sha256": "a" * 64,
                "byte_size": file_stat.st_size,
                "modified_ns": file_stat.st_mtime_ns,
            },
        )

    def test_verified_record_round_trips_with_exact_schema(self) -> None:
        record = self.authorize()
        self.assertRegex(str(record["authorization_id"]), r"^verification:[0-9a-f]{24}$")
        self.assertEqual(record["status"], "active")
        self.assertEqual(
            set(record),
            {
                "authorization_id", "local_path", "resolved_root",
                "backend_model_id", "sha256", "byte_size", "modified_ns",
                "status", "created_at", "last_verified_at",
            },
        )
        self.assertEqual(
            FileVerificationRegistry(self.state_dir).resolve(
                backend_model_id="model.safetensors"
            ),
            record,
        )

    def test_resolve_fails_closed_on_ambiguous_model_name(self) -> None:
        self.authorize()
        second = self.root / "nested" / "model.safetensors"
        second.parent.mkdir()
        second.write_bytes(b"second")
        self.authorize(second)
        with self.assertRaisesRegex(ValidationError, "ambiguous_file_verification"):
            self.registry.resolve(backend_model_id="model.safetensors")

    def test_status_change_retains_digest_and_removes_active_resolution(self) -> None:
        record = self.authorize()
        changed = self.registry.set_status(str(record["authorization_id"]), "drifted")
        self.assertEqual(changed["sha256"], "a" * 64)
        self.assertEqual(changed["status"], "drifted")
        self.assertIsNone(self.registry.resolve(backend_model_id="model.safetensors"))
        self.assertEqual(
            self.registry.resolve(
                authorization_id=str(record["authorization_id"]), active_only=False
            ),
            changed,
        )
        revoked = self.registry.set_status(str(record["authorization_id"]), "revoked")
        self.assertEqual(revoked["status"], "revoked")

    def test_record_verified_refreshes_same_authorization_without_duplicate(self) -> None:
        first = self.authorize()
        refreshed = self.registry.record_verified(
            local_path=self.model,
            resolved_root=self.root,
            backend_model_id="model.safetensors",
            fingerprint={
                "sha256": "a" * 64,
                "byte_size": self.model.stat().st_size,
                "modified_ns": self.model.stat().st_mtime_ns,
            },
        )
        document = json.loads((self.state_dir / "file-verifications.json").read_text(encoding="utf-8"))
        self.assertEqual(refreshed["authorization_id"], first["authorization_id"])
        self.assertEqual(refreshed["created_at"], first["created_at"])
        self.assertEqual(len(document["records"]), 1)

    def test_corrupt_unknown_duplicate_credential_and_nonlocal_state_fail_closed(self) -> None:
        record = self.authorize()
        path = self.state_dir / "file-verifications.json"
        valid = json.loads(path.read_text(encoding="utf-8"))
        cases = (
            {**valid, "unknown": True},
            {**valid, "records": [record, record]},
            {**valid, "api_key": "secret"},
            {**valid, "records": [{**record, "sha256": "A" * 64}]},
            {**valid, "records": [{**record, "local_path": str(self.root / "other.safetensors")}]},
            {**valid, "records": [{**record, "local_path": r"\\server\share\model.safetensors"}]},
        )
        for document in cases:
            with self.subTest(document=document):
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ArtifactError, "corrupt_file_verification_registry"):
                    self.registry.resolve(authorization_id=str(record["authorization_id"]))

    def test_atomic_replace_failure_preserves_existing_document(self) -> None:
        record = self.authorize()
        path = self.state_dir / "file-verifications.json"
        original = path.read_bytes()
        with patch("local_gpu_imagegen.artifacts.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.registry.set_status(str(record["authorization_id"]), "revoked")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the registry tests and verify RED**

```powershell
python -m unittest tests.test_file_verification -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.file_verification'`. No state is written outside the temporary directory.

- [ ] **Step 3: Implement the strict registry**

Create `scripts/local_gpu_imagegen/file_verification.py`. Keep the public surface exactly to the three methods above. Use these imports, constants, record construction, and status transition; validate the complete schema before returning any record:

```python
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import atomic_write_json
from .errors import ArtifactError, ValidationError


class FileVerificationRegistry:
    def __init__(self, state_dir: Path, *, now: Callable[[], str] | None = None) -> None:
        self.path = Path(state_dir) / "file-verifications.json"
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    def resolve(
        self,
        *,
        backend_model_id: str | None = None,
        authorization_id: str | None = None,
        active_only: bool = True,
    ) -> dict[str, object] | None:
        if not backend_model_id and not authorization_id:
            raise ValidationError("invalid_file_verification_lookup", "An authorization ID or backend model ID is required.")
        matches = [
            record for record in self._read()["records"]
            if (not active_only or record["status"] == "active")
            and (authorization_id is None or record["authorization_id"] == authorization_id)
            and (backend_model_id is None or record["backend_model_id"] == backend_model_id)
        ]
        if len(matches) > 1:
            raise ValidationError("ambiguous_file_verification", "Multiple exact files match this backend model name.")
        return copy.deepcopy(matches[0]) if matches else None

    def record_verified(
        self,
        *,
        local_path: Path,
        resolved_root: Path,
        backend_model_id: str,
        fingerprint: dict[str, object],
    ) -> dict[str, object]:
        boundary = {
            "local_path": str(Path(local_path).resolve()),
            "resolved_root": str(Path(resolved_root).resolve()),
            "backend_model_id": backend_model_id,
        }
        authorization_id = "verification:" + _canonical_hash(boundary)[:24]
        document = self._read()
        prior = next((item for item in document["records"] if item["authorization_id"] == authorization_id), None)
        timestamp = self.now()
        record = _validate_record({
            "authorization_id": authorization_id,
            **boundary,
            "sha256": fingerprint.get("sha256"),
            "byte_size": fingerprint.get("byte_size"),
            "modified_ns": fingerprint.get("modified_ns"),
            "status": "active",
            "created_at": prior["created_at"] if prior else timestamp,
            "last_verified_at": timestamp,
        })
        document["records"] = [item for item in document["records"] if item["authorization_id"] != authorization_id] + [record]
        self._write(document)
        return copy.deepcopy(record)

    def set_status(self, authorization_id: str, status: str) -> dict[str, object]:
        if status not in {"drifted", "revoked"}:
            raise ValidationError("invalid_file_verification_status", "File verification status is unsupported.")
        document = self._read()
        matches = [item for item in document["records"] if item["authorization_id"] == authorization_id]
        if len(matches) != 1:
            raise ValidationError("file_verification_not_found", "File verification authorization does not exist.")
        matches[0]["status"] = status
        self._write(document)
        return copy.deepcopy(matches[0])
```

Implement the private validation and persistence helpers with this behavior:

```python
DOCUMENT_FIELDS = {"schema_version", "records"}
RECORD_FIELDS = {
    "authorization_id", "local_path", "resolved_root", "backend_model_id",
    "sha256", "byte_size", "modified_ns", "status", "created_at", "last_verified_at",
}
STATUSES = {"active", "drifted", "revoked"}
CREDENTIAL_KEYS = {
    "api_key", "apikey", "token", "password", "secret",
    "authorization", "credential", "credentials",
}

def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    file_stat = os.lstat(path)
    attributes = getattr(file_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)

def _reject_credentials(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in CREDENTIAL_KEYS:
                raise ValueError("credential field")
            _reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_credentials(item)

def _validate_record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != RECORD_FIELDS:
        raise ValueError("record fields")
    _reject_credentials(value)
    if re.fullmatch(r"verification:[0-9a-f]{24}", str(value["authorization_id"])) is None:
        raise ValueError("authorization ID")
    local_path = Path(str(value["local_path"]))
    root = Path(str(value["resolved_root"]))
    if not local_path.is_absolute() or not root.is_absolute() or local_path != local_path.resolve() or root != root.resolve() or str(local_path).startswith("\\\\") or str(root).startswith("\\\\") or not _within(local_path, root):
        raise ValueError("non-local path")
    if not isinstance(value["backend_model_id"], str) or not value["backend_model_id"].strip():
        raise ValueError("backend model ID")
    boundary = {
        "local_path": str(local_path), "resolved_root": str(root),
        "backend_model_id": value["backend_model_id"],
    }
    if value["authorization_id"] != "verification:" + _canonical_hash(boundary)[:24]:
        raise ValueError("authorization boundary")
    if re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])) is None:
        raise ValueError("SHA-256")
    if any(type(value[field]) is not int or value[field] < 0 for field in ("byte_size", "modified_ns")):
        raise ValueError("stat boundary")
    if value["status"] not in STATUSES:
        raise ValueError("status")
    if any(re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+Z", str(value[field])) is None for field in ("created_at", "last_verified_at")):
        raise ValueError("timestamp")
    return copy.deepcopy(value)

def _validate_document(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != DOCUMENT_FIELDS or value.get("schema_version") != 1 or not isinstance(value.get("records"), list):
        raise ValueError("document shape")
    records = [_validate_record(item) for item in value["records"]]
    identifiers = [str(item["authorization_id"]) for item in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate authorization ID")
    return {"schema_version": 1, "records": records}

    def _read(self) -> dict[str, object]:
        if not os.path.lexists(self.path):
            return {"schema_version": 1, "records": []}
        try:
            file_stat = os.stat(self.path, follow_symlinks=False)
            if _link_like(self.path) or not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > 4 * 1024 * 1024:
                raise ValueError("unsafe registry file")
            return _validate_document(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ArtifactError(
                "corrupt_file_verification_registry",
                "File verification registry is corrupt.",
            ) from error

    def _write(self, document: dict[str, object]) -> None:
        atomic_write_json(self.path, _validate_document(document))
```

Place `_read` and `_write` inside `FileVerificationRegistry`; keep the other helpers at module scope. These helpers do not stat or open an authorized model file.

Do not export a delete method, accept arbitrary metadata, or infer trust.

- [ ] **Step 4: Run registry tests and verify GREEN**

```powershell
python -m unittest tests.test_file_verification -v
```

Expected: 6 tests PASS. No GPU, backend, model download, or repository state path is touched.

- [ ] **Step 5: Record the first production line count**

```powershell
git diff --numstat -- scripts/local_gpu_imagegen/file_verification.py
git diff --check
```

Expected: record the registry's exact net production increase and subtract it from the slice-wide 330-line ceiling; `git diff --check` emits no output. Do not trim schema checks to create room for later integration.

- [ ] **Step 6: Commit the registry boundary**

```powershell
git add scripts/local_gpu_imagegen/file_verification.py tests/test_file_verification.py
git add -f docs/superpowers/plans/2026-07-28-file-verification-authorization.md
git commit -m "feat: persist exact file verification authorization"
```

### Task 2: Discovery Exact-File Verify And Revoke

**Files:**
- Modify: `scripts/local_gpu_imagegen/discovery.py`
- Modify: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `FileVerificationRegistry.resolve`, `record_verified`, and `set_status` from Task 1.
- Extends: `DISCOVERY_MODES` with `exact_file`; extends `DISCOVERY_STAGES` with `verify` and `revoke` without changing existing mode/stage combinations.
- Extends: `DiscoveryService.__init__(adapters: BackendRegistry, file_verifications: FileVerificationRegistry, *, clock: Callable[[], float] = time.time, ttl_seconds: float = 300, common_roots_provider: RootsProvider | None = None, network_root_detector: RootPredicate | None = None, drive_root_validator: RootPredicate | None = None)` and the existing `execute` signature with `confirmation: str | None = None`.
- Produces: exact-file plans with `authorization_id`, `expected_backend_model_id`, `confirmation_required`, `byte_size`, `modified_ns`, and full-read `cost_warning`.
- Preserves: all old API-only, selected-folder, common-location, and full-drive behavior.

- [ ] **Step 1: Inject a temporary registry into existing discovery tests**

In `tests/test_discovery.py`, import `FileVerificationRegistry`, create `self.file_verifications = FileVerificationRegistry(Path(self.temporary_directory.name) / "state")`, and pass it as the second argument to every `DiscoveryService` constructed in this file. Add:

```python
def exact_plan(self, **changes: object) -> dict[str, object]:
    request: dict[str, object] = {
        "mode": "exact_file",
        "stage": "verify",
        "roots": [str(self.root)],
        "explicit_includes": [str(self.root / "model.safetensors")],
        "expected_backend_model_id": "model.safetensors",
    }
    request.update(changes)
    return self.service.plan(request)
```

- [ ] **Step 2: Add RED plan and execution tests**

Add these tests to `DiscoveryTests`:

```python
def test_exact_file_first_plan_is_stat_only_and_confirmation_bound(self) -> None:
    model = self.root / "model.safetensors"
    model.write_bytes(safetensors_bytes({}, b"weights"))
    with patch(
        "local_gpu_imagegen.discovery.fingerprint_selected_file",
        side_effect=AssertionError("plan hashed model bytes"),
    ):
        plan = self.exact_plan()
    self.assertTrue(plan["confirmation_required"])
    self.assertEqual(plan["roots"], [str(self.root.resolve())])
    self.assertEqual(plan["explicit_includes"], [str(model.resolve())])
    self.assertEqual(plan["expected_backend_model_id"], "model.safetensors")
    self.assertEqual(plan["byte_size"], model.stat().st_size)
    self.assertIn("complete contents", str(plan["cost_warning"]))

def test_exact_file_execution_hashes_persists_then_inserts_inventory(self) -> None:
    model = self.root / "model.safetensors"
    model.write_bytes(safetensors_bytes({}, b"weights"))
    plan = self.exact_plan()
    result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
    candidate = result["candidates"][0]
    self.assertEqual(candidate["backend"], "filesystem")
    self.assertEqual(candidate["backend_model_id"], "model.safetensors")
    self.assertEqual(candidate["identity_strength"], "cryptographic")
    self.assertEqual(candidate["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
    stored = self.file_verifications.resolve(backend_model_id="model.safetensors")
    self.assertEqual(stored["sha256"], candidate["sha256"])
    self.assertEqual(self.service.inventory(), [candidate])

def test_active_authorization_rehashes_in_fresh_service_without_confirmation(self) -> None:
    model = self.root / "model.safetensors"
    model.write_bytes(safetensors_bytes({}, b"weights"))
    first = self.exact_plan()
    self.service.execute(str(first["plan_id"]), str(first["confirmation"]))
    fresh = DiscoveryService(
        BackendRegistry([self.adapter]), self.file_verifications,
        clock=self.clock, network_root_detector=lambda _path: False,
    )
    plan = fresh.plan({
        "mode": "exact_file", "stage": "verify",
        "expected_backend_model_id": "model.safetensors",
    })
    self.assertFalse(plan["confirmation_required"])
    result = fresh.execute(str(plan["plan_id"]), None)
    self.assertEqual(result["candidates"][0]["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())

def test_changed_bytes_mark_authorization_drifted_without_inventory_restore(self) -> None:
    model = self.root / "model.safetensors"
    model.write_bytes(b"first")
    first = self.exact_plan()
    self.service.execute(str(first["plan_id"]), str(first["confirmation"]))
    authorization = self.file_verifications.resolve(backend_model_id="model.safetensors")
    model.write_bytes(b"changed")
    fresh = DiscoveryService(BackendRegistry([self.adapter]), self.file_verifications)
    plan = fresh.plan({
        "mode": "exact_file", "stage": "verify",
        "roots": [str(self.root)], "explicit_includes": [str(model)],
        "expected_backend_model_id": "model.safetensors",
        "authorization_id": authorization["authorization_id"],
    })
    with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
        fresh.execute(str(plan["plan_id"]), str(plan["confirmation"]))
    self.assertEqual(fresh.inventory(), [])
    self.assertIsNone(self.file_verifications.resolve(authorization_id=authorization["authorization_id"]))
    self.assertEqual(
        self.file_verifications.resolve(
            authorization_id=authorization["authorization_id"], active_only=False
        )["status"],
        "drifted",
    )

def test_exact_file_revoke_requires_confirmation_and_never_reads_model(self) -> None:
    model = self.root / "model.safetensors"
    model.write_bytes(b"weights")
    verified = self.exact_plan()
    self.service.execute(str(verified["plan_id"]), str(verified["confirmation"]))
    authorization = self.file_verifications.resolve(backend_model_id="model.safetensors")
    plan = self.service.plan({
        "mode": "exact_file", "stage": "revoke",
        "authorization_id": authorization["authorization_id"],
    })
    with patch.object(Path, "open", side_effect=AssertionError("revoke opened model bytes")):
        result = self.service.execute(str(plan["plan_id"]), str(plan["confirmation"]))
    self.assertEqual(result["authorization"]["status"], "revoked")
    self.assertEqual(result["candidates"], [])
```

- [ ] **Step 3: Add RED safety and no-mutation table tests**

Add one table-driven test covering zero/two roots, zero/two includes, include escape, active-authorization path mismatch, directory include, unsupported extension, expected-name mismatch, UNC root, link-like file where supported, unknown/revoked authorization, ambiguous model-name resolution, missing confirmation on first verification, wrong confirmation, and expired exact-file plan. Add a separate mid-read mutation test by patching `local_gpu_imagegen.model_identity.sha256_file` to rewrite the selected file after reading it; assert `model_identity_drifted`, the old authorization becomes `drifted`, and inventory stays empty. For every failure assert both `service.inventory() == []` and registry bytes are unchanged except for the explicit `drifted` transition. Also patch `fingerprint_selected_file` during all plan-only calls to prove no model hash occurs.

- [ ] **Step 4: Run focused discovery tests and verify RED**

```powershell
python -m unittest tests.test_discovery -v
```

Expected: FAIL because `DiscoveryService` does not accept a registry and `exact_file`, `verify`, and `revoke` are unsupported. All old discovery tests before the new cases remain behaviorally unchanged.

- [ ] **Step 5: Implement exact-file normalization and planning**

In `discovery.py`, add the registry dependency and keep the branch isolated before existing filesystem scan normalization:

```python
DISCOVERY_MODES = frozenset({
    "api_only", "selected_folders", "common_locations", "full_drive", "exact_file",
})
DISCOVERY_STAGES = frozenset({"index", "fingerprint", "verify", "revoke"})

def __init__(
    self,
    adapters: BackendRegistry,
    file_verifications: FileVerificationRegistry,
    *,
    clock: Callable[[], float] = time.time,
    ttl_seconds: float = 300,
    common_roots_provider: RootsProvider | None = None,
    network_root_detector: RootPredicate | None = None,
    drive_root_validator: RootPredicate | None = None,
) -> None:
    if not isinstance(adapters, BackendRegistry):
        raise ValidationError("invalid_discovery_registry", "Discovery requires a backend registry.")
    if not isinstance(file_verifications, FileVerificationRegistry):
        raise ValidationError("invalid_file_verification_registry", "Discovery requires a file verification registry.")
    if not callable(clock):
        raise ValidationError("invalid_discovery_clock", "Discovery clock must be callable.")
    if not isinstance(ttl_seconds, (int, float)) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise ValidationError("invalid_discovery_ttl", "Discovery plan lifetime must be positive.")
    self.adapters = adapters
    self.file_verifications = file_verifications
    self.clock = clock
    self.ttl_seconds = float(ttl_seconds)
    self.common_roots_provider = common_roots_provider or _common_model_roots
    self.network_root_detector = network_root_detector or _network_root
    self.drive_root_validator = drive_root_validator or _drive_root
    self._plans: dict[str, dict[str, object]] = {}
    self._inventory: list[dict[str, object]] = []
    self.file_verifications = file_verifications

def _normalize_exact_file(self, request: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    stage = request.get("stage")
    authorization = self.file_verifications.resolve(
        backend_model_id=request.get("expected_backend_model_id"),
        authorization_id=request.get("authorization_id"),
        active_only=stage != "revoke",
    )
    if stage == "revoke":
        if authorization is None or authorization["status"] == "revoked":
            raise ValidationError("file_verification_not_found", "Revocable file verification authorization does not exist.")
        return _revoke_scope(authorization), []
    root, path, confirmation_required = _resolve_exact_boundary(request, authorization)
    indexed = _stat_exact_file(root, path, request.get("expected_backend_model_id"))
    return {
        "mode": "exact_file", "scan_mode": "exact_file", "stage": "verify",
        "backends": [], "endpoints": [], "roots": [str(root)], "network_roots": [],
        "selected_candidates": [], "extensions": list(MODEL_EXTENSIONS), "exclusions": [],
        "explicit_includes": [str(path)],
        "expected_backend_model_id": indexed["backend_model_id"],
        "authorization_id": authorization["authorization_id"] if authorization else None,
        "confirmation_required": confirmation_required,
        "byte_size": indexed["byte_size"], "modified_ns": indexed["modified_ns"],
        "cost_warning": "Verification hashes this exact model file and may read its complete contents.",
    }, [indexed]
```

`_resolve_exact_boundary` must use the active authorization's exact path/root when reusable; otherwise require exactly one resolved root and include. `_stat_exact_file` must use `os.stat(path, follow_symlinks=False)`, `_link_like`, `stat.S_ISREG`, `_within`, `network_root_detector`, suffix membership in `MODEL_EXTENSIONS`, and exact `expected_backend_model_id`; it must not open the file.

Set `confirmation_required` to `False` only when path, root, model name, byte size, and modified-nanoseconds equal an active authorization. All other verify and every revoke plan gets a digest-bound confirmation.

- [ ] **Step 6: Implement exact-file execution**

Before the existing API/index/fingerprint dispatch in `execute`, use this branch:

```python
if plan["mode"] == "exact_file" and plan["stage"] == "revoke":
    authorization = self.file_verifications.set_status(str(plan["authorization_id"]), "revoked")
    return {"plan_id": plan_id, "scope_hash": plan["scope_hash"], "incomplete": False,
            "candidates": [], "authorization": authorization, "trusted": False}
if plan["mode"] == "exact_file":
    indexed = plan["_frozen_candidates"][0]
    try:
        fingerprint = fingerprint_selected_file(Path(str(indexed["local_path"])), indexed)
    except ConflictError:
        if plan.get("authorization_id"):
            self.file_verifications.set_status(str(plan["authorization_id"]), "drifted")
        raise
    authorization = self.file_verifications.resolve(authorization_id=plan.get("authorization_id")) if plan.get("authorization_id") else None
    if authorization and fingerprint["sha256"] != authorization["sha256"]:
        self.file_verifications.set_status(str(authorization["authorization_id"]), "drifted")
        raise ConflictError("model_identity_drifted", "Authorized model bytes changed after the last approved verification.")
    stored = self.file_verifications.record_verified(
        local_path=Path(str(indexed["local_path"])),
        resolved_root=Path(str(indexed["resolved_root"])),
        backend_model_id=str(indexed["backend_model_id"]),
        fingerprint=fingerprint,
    )
    candidates = [_exact_discovery_record(indexed, fingerprint, stored)]
    incomplete = False
```

`_exact_discovery_record` must call `validate_discovery_record` with backend `filesystem`, a canonical `filesystem:<root hash>` endpoint, the exact backend model name, cryptographic strength, empty metadata, and fingerprint values; then add only the existing inventory fields (`candidate_id`, `identity_token`, `source_type`, `resolved_root`, `local_path`, `relative_path`, `filename`, `trusted`). Merge into inventory only after registry write and every validation succeeds.

Update `_current_plan` so `confirmation: str | None` is accepted only when stored `confirmation_required is False`; all old plans, first verification plans, drifted plans, and revoke plans still raise `discovery_confirmation_mismatch` when the exact token is absent or changed.

- [ ] **Step 7: Run focused discovery tests and verify GREEN**

```powershell
python -m unittest tests.test_discovery tests.test_file_verification -v
```

Expected: PASS, with only the existing platform-dependent link skip. Plan-only tests perform no full-file hash; failed executions leave inventory empty and preserve the last approved registry digest.

- [ ] **Step 8: Check cumulative production trajectory and commit**

```powershell
git diff --numstat 484285c -- scripts/local_gpu_imagegen/file_verification.py scripts/local_gpu_imagegen/discovery.py
git diff --check
git add scripts/local_gpu_imagegen/discovery.py tests/test_discovery.py
git commit -m "feat: verify one authorized model file"
```

Expected: record the cumulative new production net lines and the exact remainder under the 330-line ceiling. If the remaining lines cannot fit the already specified runtime and MCP edits, stop before Task 3 for design review.

### Task 3: Runtime, MCP, And Fresh-Process Composition

**Files:**
- Modify: `scripts/local_gpu_imagegen/services.py`
- Modify: `scripts/mcp_server.py`
- Modify: `tests/test_runtime_services.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: exact-file DiscoveryService contract from Task 2.
- Produces: one shared `RuntimeServices.file_verifications` instance injected into `RuntimeServices.discovery`.
- Extends: `local_gpu_discover_models` properties with `expected_backend_model_id` and `authorization_id`; enum values only, no 18th tool.
- Produces: a fresh-process proof that API identity plus exact reverified filesystem identity reaches the existing workflow trust proposal, while API-only inventory still fails closed.

- [ ] **Step 1: Add runtime composition RED tests**

In `tests/test_runtime_services.py`, assert:

```python
self.assertIs(services.discovery.file_verifications, services.file_verifications)
self.assertEqual(services.file_verifications.path, root / "state" / "file-verifications.json")
```

Add a fresh-process test that performs this exact sequence using a temporary model file named by the shipped `sd15-txt2img-v1.json` checkpoint loader and a fake ComfyUI adapter:

```text
process 1: exact_file/verify plan -> confirmed execute -> authorization persisted
process 2: api_only/index plan -> execute -> exact_file/verify by backend model name
           -> execute with confirmation omitted -> inventory has one API binding and
              one cryptographic filesystem identity -> inspect workflow is registerable
              -> existing inspect_workflow_binding returns approve_private confirmation
control:  process 3 API-only inventory without exact-file restore returns
          component_primary_identity_required or invalid_component_bundle
```

Patch only `adapters_from_environment`; do not patch `FileVerificationRegistry`, `DiscoveryService`, hashing, onboarding, or `_workflow_component_bundle`. Assert process 2 performs exactly one `fingerprint_selected_file` call and no generation method call.

- [ ] **Step 2: Add MCP schema, validation, and dispatch RED tests**

Update the exact discovery property expectation in `test_every_high_level_tool_has_closed_exact_schema` to include:

```python
"expected_backend_model_id", "authorization_id"
```

Add:

```python
def test_exact_file_extends_discovery_without_an_eighteenth_tool(self) -> None:
    tools = mcp_server.tool_schema()
    self.assertEqual(len(tools), 17)
    discovery = next(item for item in tools if item["name"] == "local_gpu_discover_models")
    properties = discovery["inputSchema"]["properties"]
    self.assertIn("exact_file", properties["mode"]["enum"])
    self.assertEqual(set(properties["stage"]["enum"]), {"index", "fingerprint", "verify", "revoke"})
    self.assertEqual(properties["expected_backend_model_id"], {"type": "string", "minLength": 1})
    self.assertEqual(properties["authorization_id"]["pattern"], r"^verification:[0-9a-f]{24}$")

def test_exact_file_dispatch_forwards_identity_fields_and_optional_confirmation(self) -> None:
    services = Mock()
    services.discovery.execute.return_value = {"candidates": [], "trusted": False}
    arguments = {
        "phase": "execute", "plan_id": "plan-1",
        "expected_backend_model_id": "model.safetensors",
        "authorization_id": "verification:" + "a" * 24,
    }
    with patch.object(mcp_server, "get_runtime_services", return_value=services):
        result = mcp_server.handle_tool_call({"name": "local_gpu_discover_models", "arguments": arguments})
    self.assertFalse(result["isError"])
    services.discovery.execute.assert_called_once_with("plan-1", None, network_confirmation=None)
```

Retain a test proving missing confirmation on an ordinary retained plan returns `discovery_confirmation_mismatch` and does not call any adapter.

- [ ] **Step 3: Run runtime and MCP tests and verify RED**

```powershell
python -m unittest tests.test_runtime_services tests.test_mcp_server -v
```

Expected: FAIL because runtime does not expose/inject the registry, the MCP enums/fields are absent, and execute validation still requires `confirmation` unconditionally.

- [ ] **Step 4: Wire the registry into the runtime graph**

Make only these ownership changes in `services.py`:

```python
from .file_verification import FileVerificationRegistry

class RuntimeServices:
    discovery: DiscoveryService
    file_verifications: FileVerificationRegistry
    trust: TrustRegistry
    catalog: ModelCatalog
    router: CapabilityRouter
    workflows: WorkflowTemplateRegistry
    onboarding: WorkflowOnboarding
    backends: BackendRegistry
    engine: AssetRunEngine

file_verifications = FileVerificationRegistry(state_dir)
discovery = DiscoveryService(backends, file_verifications)

return RuntimeServices(
    discovery=discovery,
    file_verifications=file_verifications,
    trust=trust,
    catalog=catalog,
    router=router,
    workflows=workflows,
    onboarding=onboarding,
    backends=backends,
    engine=engine,
)
```

- [ ] **Step 5: Extend the existing MCP schema and thin dispatch**

In the existing discovery schema only:

```python
"mode": {"type": "string", "enum": ["api_only", "selected_folders", "common_locations", "full_drive", "exact_file"]},
"stage": {"type": "string", "enum": ["index", "fingerprint", "verify", "revoke"]},
"expected_backend_model_id": {"type": "string", "minLength": 1},
"authorization_id": {"type": "string", "pattern": "^verification:[0-9a-f]{24}$"},
```

Extend the existing discovery success output schema with these optional properties so strict structured results remain valid:

```python
"confirmation_required": {"type": "boolean"},
"expected_backend_model_id": {"type": "string"},
"authorization_id": {"type": ["string", "null"]},
"byte_size": {"type": "integer", "minimum": 0},
"modified_ns": {"type": "integer", "minimum": 0},
"authorization": json_object,
```

Add both names to `_discovery_call`'s plan-field allowlist. Pass `arguments.get("confirmation")` on execute. Change the phase validator to require `plan_id` only; `DiscoveryService._current_plan` remains the server-side authority that permits omission solely for a retained unchanged active authorization. Do not hash, read registry JSON, or duplicate path rules in `mcp_server.py`.

- [ ] **Step 6: Run composition and contract tests**

```powershell
python -m unittest tests.test_runtime_services tests.test_mcp_server tests.test_workflow_onboarding -v
python scripts/verify_mcp.py
```

Expected: PASS; verifier returns `"ok": true`, `"tool_count": 17`, and the exact existing tool names. Fresh-process control fails closed without filesystem restoration, while the restored process reaches the existing trust proposal.

- [ ] **Step 7: Enforce final production ceiling and commit**

```powershell
git diff --numstat 484285c -- scripts/local_gpu_imagegen/file_verification.py scripts/local_gpu_imagegen/discovery.py scripts/local_gpu_imagegen/services.py scripts/mcp_server.py
git diff --check
git add scripts/local_gpu_imagegen/services.py scripts/mcp_server.py tests/test_runtime_services.py tests/test_mcp_server.py
git commit -m "feat: restore authorized identity in fresh processes"
```

Expected: the four production owners total at most 330 net new lines for this slice. Stop before commit if the ceiling is exceeded; tests and docs do not count toward that production ceiling.

### Task 4: Agent And Public Recovery Contract

**Files:**
- Modify: `skills/local-gpu-imagegen/SKILL.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/troubleshooting.md`
- Modify: `docs/architecture.md`
- Modify: `tests/test_skill_contract.py`
- Modify: `tests/test_public_docs.py`

**Interfaces:**
- Consumes: exact-file MCP contract from Task 3.
- Produces: three explicit first-use decisions (file verification, registration/private trust, execution), two later decisions for a new workflow on an unchanged model, and one execution decision for an already trusted unchanged workflow.
- Preserves: no hidden download, no route reuse, no image-quality claim, exact workflow defaults, one successful round, and all current unsupported-topology boundaries.

- [ ] **Step 1: Add RED Skill contract tests**

Add to `SkillContractTests`:

```python
def test_codex_first_runner_has_three_first_use_decisions_and_exact_revalidation(self) -> None:
    section = _section(self.text, "## Codex-First Workflow Runner", "## Workflow Onboarding")
    _assert_ordered(section, (
        "File verification decision",
        "`exact_file` / `verify`",
        "stop and wait for a later user message",
        "Preparation decision",
        "`local_gpu_register_workflow`",
        "`approve_private`",
        "Execution decision",
        "`local_gpu_start_run`",
    ))
    for required in (
        "one exact local model path", "complete contents", "same SHA-256",
        "new workflow on the same verified model requires two decisions",
        "already trusted unchanged workflow requires only the execution decision",
        "Never reuse a route token, prompt ID, or run ID",
    ):
        self.assertIn(required, section)

def test_codex_first_runner_never_treats_authorization_as_trust(self) -> None:
    section = _section(self.text, "## Codex-First Workflow Runner", "## Workflow Onboarding")
    for boundary in (
        "does not grant model trust", "does not register a workflow",
        "does not approve a route", "does not submit a prompt",
        "Do not downgrade to `backend_binding`",
    ):
        self.assertIn(boundary, section)
```

- [ ] **Step 2: Add RED public-document tests**

Add to `PublicDocumentationTests`:

```python
def test_docs_define_exact_file_first_and_later_use_decision_counts(self) -> None:
    quickstart = QUICKSTART.read_text(encoding="utf-8")
    for required in (
        "File verification decision", "one exact local model path",
        "reads the complete model file", "three first-use decisions",
        "two decisions", "one execution decision", "exactly 17 tools",
    ):
        self.assertIn(required, quickstart)

def test_recovery_docs_replace_manual_two_scan_fresh_process_path(self) -> None:
    troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    section = troubleshooting[
        troubleshooting.index("## A Fresh Process Cannot Recover A Public Route"):
        troubleshooting.index("## ComfyUI Workflow Is Rejected")
    ]
    for required in (
        "`exact_file`", "`verify`", "full SHA-256", "same SHA-256",
        "`model_identity_drifted`", "new file-verification decision",
    ):
        self.assertIn(required, section)
    self.assertNotIn("`selected_folders` `index`", section)
    self.assertIn("never uses a broader scan", section.lower())

def test_architecture_assigns_registry_and_exact_file_owners(self) -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    for required in (
        "`FileVerificationRegistry`", "`file-verifications.json`",
        "stat-only plan", "full-file SHA-256", "active", "drifted", "revoked",
        "exactly 17 MCP tools", "does not improve image quality",
    ):
        self.assertIn(required, architecture)
```

- [ ] **Step 3: Run docs contracts and verify RED**

```powershell
python -m unittest tests.test_skill_contract tests.test_public_docs -v
```

Expected: FAIL on the missing file-verification decision, later-use counts, and registry architecture text.

- [ ] **Step 4: Rewrite the Codex-first Skill sequence**

In `skills/local-gpu-imagegen/SKILL.md`, retain the existing workflow/default/registration/route/run details but prepend this exact decision state machine inside `## Codex-First Workflow Runner`:

```text
First use:
read-only API discovery + workflow inspection
-> File verification decision
-> `exact_file` / `verify` for one exact local model path
-> stop and wait for a later user message
-> full-file SHA-256 and cryptographic inventory restore
-> Preparation decision
-> immutable registration + `approve_private`
-> Execution decision
-> `local_gpu_start_run` + one successful round

Later new workflow, same verified model:
automatic exact-file revalidation with full SHA-256
-> Preparation decision
-> Execution decision

Already trusted unchanged workflow:
automatic exact-file revalidation with full SHA-256
-> Execution decision
```

State literally that verification authorization covers one exact local model path and a future complete-contents read; it does not grant model trust, register a workflow, approve a route, or submit a prompt. Display byte size and full-read cost before every full hash, even when an unchanged active authorization makes a new confirmation unnecessary. Same SHA-256 restores cryptographic inventory; path/stat/SHA drift stops with a new file-verification decision. Do not downgrade to `backend_binding`, broaden scanning, guess between same-name authorizations, or retry. Never reuse a route token, prompt ID, or run ID.

- [ ] **Step 5: Update quickstart, recovery, and architecture**

In `docs/quickstart.md`, place `### File verification decision` before the current preparation and execution decisions. Explain the exact path, displayed byte size/cost, later full read, and three/two/one decision counts. Keep the copy-ready Codex request and explicitly say the MCP surface remains exactly 17 tools.

Replace the manual two-scan fresh-process recipe in `docs/troubleshooting.md` with:

```markdown
1. Run API-only discovery and inspect the requested workflow to obtain its exact loader model name.
2. Plan `exact_file` / `verify`. A first use displays one exact root/file, byte size, full-read cost, expiry, and confirmation. An unchanged active authorization resolves the same path without a new confirmation.
3. Execute one full SHA-256. The same SHA-256 restores the cryptographic filesystem identity in this process; `model_identity_drifted`, ambiguity, path drift, or registry corruption stops before trust or routing and requires a new file-verification decision.
4. Continue registration/private trust and route approval only after both filesystem and current ComfyUI API identities are present.
```

State that recovery never uses a broader scan or backend-bound downgrade.

In `docs/architecture.md`, add `FileVerificationRegistry` to the ownership table, replace the old selected-folder recovery flow, list `active`/`drifted`/`revoked`, and state: the MCP layer remains exactly 17 tools; this feature restores identity and does not improve image quality.

- [ ] **Step 6: Run contract tests and commit**

```powershell
python -m unittest tests.test_skill_contract tests.test_public_docs -v
git diff --check
git add skills/local-gpu-imagegen/SKILL.md docs/quickstart.md docs/troubleshooting.md docs/architecture.md tests/test_skill_contract.py tests/test_public_docs.py
git commit -m "docs: teach exact file verification decisions"
```

Expected: PASS; no public document claims generated-image, image-quality, production-readiness, or live-gate evidence.

### Task 5: Model-Free Verification, Review, Continuity, And Live-Gate Handoff

**Files:**
- Modify after verification: `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\PROJECT_NODES.md`
- Modify after verification: `D:\CodexWorkspace\projects\plugins\local-gpu-imagegen\NEXT_SESSION.md`
- No production or test code changes in this task unless a failing gate is first reproduced with a RED test.

**Interfaces:**
- Consumes: four reviewed commits from Tasks 1-4.
- Produces: model-free evidence, exact line ownership, a clean branch, continuity records, and a separate live-gate approval boundary.

- [ ] **Step 1: Run the focused authorization slice**

```powershell
python -m unittest tests.test_file_verification tests.test_discovery tests.test_runtime_services tests.test_mcp_server tests.test_workflow_onboarding tests.test_skill_contract tests.test_public_docs tests.test_verify_mcp -v
```

Expected: PASS with only documented Windows link/permission skips. No backend endpoint, GPU, model download, prompt, route, or run is used.

- [ ] **Step 2: Run the complete model-free repository gate**

```powershell
python -m unittest discover -s tests -v
python -m compileall scripts
python scripts/verify_mcp.py
git diff --check
```

Expected:

- all tests pass with only existing documented Windows permission/link skips;
- `compileall` succeeds;
- MCP verification returns `ok: true` and exactly 17 tools;
- `git diff --check` emits no output.

- [ ] **Step 3: Verify frozen workflows and owner boundary**

```powershell
python -m unittest tests.test_workflow_templates.WorkflowTemplateTests.test_existing_sdxl_workflow_files_remain_byte_identical -v
git diff --name-only 484285c..HEAD
git diff --numstat 484285c..HEAD -- scripts/local_gpu_imagegen/file_verification.py scripts/local_gpu_imagegen/discovery.py scripts/local_gpu_imagegen/services.py scripts/mcp_server.py
```

Expected: frozen workflow bytes PASS; no new production owner exists; the new four-owner slice is at most 150 net lines. Existing branch production ownership from `3fb4516` remains separately accounted as 113 net lines across the previously approved four owners.

- [ ] **Step 4: Review failure atomicity and branch history**

```powershell
git status --short --branch
git log --oneline main@3fb45163ec61189c2d2c89a7c183612a55cb6058..HEAD
git diff --check main@3fb45163ec61189c2d2c89a7c183612a55cb6058..HEAD
```

Review every exact-file error test against these invariants: no registry write after a failed first hash; last approved digest retained after drift; no inventory restoration after drift; plan-only calls never hash; revoke never opens or deletes model bytes; missing confirmation remains rejected except for an unchanged active authorization.

- [ ] **Step 5: Perform final branch review**

Review the complete diff from `484285c` for severity-ordered bugs, security boundary regressions, missing tests, stale docs, line-budget violations, and accidental route/run reuse. Fix only reproduced issues under TDD. Re-run the focused and full gates after any fix.

- [ ] **Step 6: Update root continuity records truthfully**

Append to root `PROJECT_NODES.md`:

- control flow: workflow reference -> stat-only exact-file plan -> separate first authorization when required -> full rehash -> cryptographic inventory -> registration/trust -> route -> one round;
- failure modes and exact structured errors for unsafe path, ambiguity, corrupt registry, expired plan, confirmation mismatch, stat/SHA drift, revoked authorization, component bundle drift, and route drift;
- exact commands, pass/skip counts, four production owners, and net production line count;
- open limitation: later-process verification rereads the complete model file and no image-quality improvement is claimed;
- live evidence limitation: no new ComfyUI prompt ID or image was produced by this model-free slice;
- authority boundary: no push, merge, release, publication, model download, GPU, or remote mutation was authorized.

Rewrite root `NEXT_SESSION.md` with the worktree, final commit, exact verification counts, remaining limitations, stopped ComfyUI state, and a fresh live-gate checklist. Remove the now-obsolete manual selected-folder/fingerprint recovery instructions.

- [ ] **Step 7: Commit continuity inside the feature branch only if those files are branch-owned**

The root continuity files are outside the isolated worktree and may be intentionally uncommitted coordination state. Do not copy them into the branch or commit unrelated root state. Commit only branch-local docs changed by a reproduced review fix; otherwise leave the verified four implementation commits as the branch tip and report the root continuity edits separately.

- [ ] **Step 8: Stop and request a separate live-gate route display**

Do not start ComfyUI or reuse old approvals. Present a fresh cost boundary before the live gate:

- at most one newly authorized installed model full-file hash;
- one fresh route approval, one accepted ComfyUI prompt ID, and one successful image maximum;
- no retry, recovery generation, comparison, model switch, CPU fallback, workflow fallback, or download;
- identity-bound shutdown only for a ComfyUI process started by that gate;
- stop after two consecutive infrastructure failures; a third attempt requires new approval.

The live gate begins only after a newly displayed exact verification proposal and, later, a newly displayed route receive their own approvals.
