# User-Bound Visual Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current single-agent worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent an Agent from finalizing a visually failed or unconfirmed image by requiring structured full-resolution checks and a user confirmation bound to the retained image bytes.

**Architecture:** A focused `visual_review.py` module owns the exact visual-check contract, eligibility predicate, and deterministic finalization candidate. `RunStore` validates and stores review evidence under its existing atomic mutation boundary, while `AssetRunEngine` derives candidates for review/recovery responses and verifies the exact candidate confirmation before any final artifact is copied. The MCP and Skill surfaces expose this stricter contract without adding tools, models, packages, or workflows.

**Tech Stack:** Python 3.12 standard library, `unittest`, MCP JSON Schema/JSON-RPC over stdio, repository Markdown contracts, existing immutable manifest and PNG validation code.

## Global Constraints

- Keep exactly fifteen MCP tools.
- Add no model, dependency, workflow, custom node, automatic detector, or second vision model.
- Do not install or download anything, modify shared/global Python, or touch `<shared-python-env>`.
- Do not edit, delete, retrofit, or stage `docs/evidence/runs/`.
- Preserve the user's unstaged `subtype` changes in `scripts/mcp_server.py` and `tests/test_mcp_server.py`; use `git add -p` for both files.
- `full_resolution_inspected` must be exactly `true`; check statuses are exactly `pass`, `fail`, `uncertain`, and `not_applicable`; observations are non-empty concise strings.
- A prominent human requires applicable `limb_separation`, `feet_and_contact`, and `hands_and_held_objects`; a non-human requires all three to be `not_applicable`; `text_and_watermarks` is always applicable.
- Any required `fail` or `uncertain` check rejects `next_action: finalize` before manifest mutation and cannot create a finalization candidate.
- The strongest pre-user status is `candidate`, never `accepted`.
- Final confirmation is exactly `finalize:<run_id>:<round_number>:<image_sha256>` and must be checked before publication.
- Keep the successful-round budget on the same run after rejection; never reset the run to recover budget.
- Existing finalized manifests remain readable and are not rewritten; unfinalized legacy reviews without `visual_checks` fail closed for candidate eligibility.
- Do not create a remote, push, tag, release, or publish.

## File Map

- `scripts/local_gpu_imagegen/visual_review.py`: exact visual-check validation, fail-closed eligibility, image-bound candidate derivation, and confirmation verification.
- `tests/test_visual_review.py`: isolated contract tests for malformed/inconsistent checks, candidate bytes, and mismatch failures.
- `scripts/local_gpu_imagegen/run_store.py`: require visual checks on new reviews, reject `finalize` with failed/uncertain checks, and include visual evidence in final quality calculation.
- `tests/test_run_store.py`: prove rejection is pre-mutation and stored legacy evidence cannot bypass final quality.
- `scripts/local_gpu_imagegen/engine.py`: decorate review/recovery responses with derived candidates, restrict recoverable finalization to candidates, and verify confirmation before postprocessing/publication.
- `tests/test_asset_run_engine.py`: reproduce the fused-anatomy failure, budget recovery, restart recovery, stale confirmation, and no-publication behavior.
- `scripts/mcp_server.py`: require/forward `visual_checks`, require `confirmation`, and expose candidate fields while preserving the user's `subtype` hunk.
- `tests/test_mcp_server.py`: exact schema and dispatch tests while preserving the user's `subtype` hunk.
- `skills/local-gpu-imagegen/SKILL.md`: require full-image inspection, explicit anatomy/text checks, candidate display, a later user turn, and exact confirmation.
- `tests/test_skill_contract.py`: enforce the temporal display/confirmation/finalize sequence and forbidden acceptance wording.
- `README.md`, `docs/architecture.md`, `docs/troubleshooting.md`: document the candidate boundary, recovery behavior, and mismatch errors.
- `tests/test_public_docs.py`: pin the public wording and compatibility claims.

---

### Task 1: Structured Visual Review Contract

**Files:**
- Create: `scripts/local_gpu_imagegen/visual_review.py`
- Create: `tests/test_visual_review.py`

**Interfaces:**
- Consumes: `ValidationError` and `ArtifactError` from `scripts/local_gpu_imagegen/errors.py`.
- Produces: `validate_visual_checks(value: object) -> dict[str, object]`, `visual_checks_pass(value: object) -> bool`, `finalization_candidate(manifest: dict[str, object], round_number: int) -> dict[str, object] | None`, and `require_finalization_confirmation(manifest: dict[str, object], round_number: int, confirmation: object) -> dict[str, object]`.
- `finalization_candidate` returns `{run_id, round_number, image_sha256, confirmation, quality_status}` only when the selected round has a stored review whose `next_action` is `finalize`, visual checks pass, hard failures are empty, preservation has no changed/uncertain hard target, and every critical score is at least 3.

- [ ] **Step 1: Write the failing visual-check tests**

```python
# tests/test_visual_review.py
def passing_checks(*, prominent_human: bool = True) -> dict[str, object]:
    anatomy = "pass" if prominent_human else "not_applicable"
    reason = "Independent anatomy is visible." if prominent_human else "No human is present."
    return {
        "full_resolution_inspected": True,
        "prominent_human": prominent_human,
        "limb_separation": {"status": anatomy, "observation": reason},
        "feet_and_contact": {"status": anatomy, "observation": reason},
        "hands_and_held_objects": {"status": anatomy, "observation": reason},
        "text_and_watermarks": {"status": "pass", "observation": "No text or watermark is visible."},
    }

def test_visual_checks_require_exact_fields_and_full_resolution_true(self) -> None:
    for value in ({}, {**passing_checks(), "full_resolution_inspected": False}):
        with self.subTest(value=value), self.assertRaises(ValidationError):
            validate_visual_checks(value)

def test_human_and_non_human_applicability_is_consistent(self) -> None:
    human = passing_checks()
    human["feet_and_contact"] = {"status": "not_applicable", "observation": "Hidden."}
    non_human = passing_checks(prominent_human=False)
    non_human["limb_separation"] = {"status": "pass", "observation": "Not relevant."}
    for value in (human, non_human):
        with self.subTest(value=value), self.assertRaises(ValidationError):
            validate_visual_checks(value)

def test_fail_and_uncertain_are_fail_closed(self) -> None:
    for status in ("fail", "uncertain"):
        checks = passing_checks()
        checks["limb_separation"] = {"status": status, "observation": "Lower legs merge."}
        self.assertFalse(visual_checks_pass(checks))

def test_candidate_binds_run_round_and_retained_sha256(self) -> None:
    manifest = eligible_manifest(image_sha256="a" * 64, visual_checks=passing_checks())
    candidate = finalization_candidate(manifest, 1)
    self.assertEqual(candidate, {
        "run_id": "run-1", "round_number": 1, "image_sha256": "a" * 64,
        "confirmation": f"finalize:run-1:1:{'a' * 64}", "quality_status": "candidate",
    })

def test_missing_legacy_checks_and_wrong_confirmation_fail_closed(self) -> None:
    manifest = eligible_manifest(image_sha256="a" * 64, visual_checks=None)
    self.assertIsNone(finalization_candidate(manifest, 1))
    with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
        require_finalization_confirmation(manifest, 1, f"finalize:run-1:1:{'a' * 64}")
```

`eligible_manifest` must construct one generated round with exact lowercase SHA-256, one review with `next_action: finalize`, empty hard failures, critical score `4`, and no preservation uncertainty. It must omit `visual_checks` when passed `None` so the legacy path is exercised.

- [ ] **Step 2: Run the focused test and verify the missing module failure**

Run: `python -m unittest tests.test_visual_review -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_gpu_imagegen.visual_review'`.

- [ ] **Step 3: Implement the exact validator and fail-closed predicate**

```python
# scripts/local_gpu_imagegen/visual_review.py
CHECK_NAMES = (
    "limb_separation", "feet_and_contact", "hands_and_held_objects", "text_and_watermarks",
)
ANATOMY_CHECKS = CHECK_NAMES[:3]
STATUSES = frozenset({"pass", "fail", "uncertain", "not_applicable"})

def validate_visual_checks(value: object) -> dict[str, object]:
    expected = {"full_resolution_inspected", "prominent_human", *CHECK_NAMES}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("invalid_visual_checks", "Visual checks do not match the required structure.")
    if value["full_resolution_inspected"] is not True or not isinstance(value["prominent_human"], bool):
        raise ValidationError("invalid_visual_checks", "Full-resolution inspection and human presence must be explicit.")
    prominent_human = value["prominent_human"]
    result = copy.deepcopy(value)
    for name in CHECK_NAMES:
        check = value[name]
        if not isinstance(check, dict) or set(check) != {"status", "observation"}:
            raise ValidationError("invalid_visual_checks", f"{name} must contain status and observation.")
        status = check.get("status")
        observation = check.get("observation")
        if status not in STATUSES or not isinstance(observation, str) or not observation.strip() or len(observation.strip()) > 500:
            raise ValidationError("invalid_visual_checks", f"{name} has invalid evidence.")
        if name in ANATOMY_CHECKS and (prominent_human and status == "not_applicable" or not prominent_human and status != "not_applicable"):
            raise ValidationError("inconsistent_visual_checks", "Anatomy applicability conflicts with prominent_human.")
        if name == "text_and_watermarks" and status == "not_applicable":
            raise ValidationError("inconsistent_visual_checks", "Text and watermark inspection is always applicable.")
    return result

def visual_checks_pass(value: object) -> bool:
    try:
        checks = validate_visual_checks(value)
    except ValidationError:
        return False
    required = CHECK_NAMES if checks["prominent_human"] else ("text_and_watermarks",)
    return all(checks[name]["status"] == "pass" for name in required)
```

- [ ] **Step 4: Implement byte-bound candidate and confirmation functions**

```python
def finalization_candidate(manifest: dict[str, object], round_number: int) -> dict[str, object] | None:
    # Locate one exact round/review, fail closed on legacy or malformed eligibility evidence,
    # require next_action=finalize, and reuse visual_checks_pass before constructing authority.
    image_sha256 = selected_round["image"]["sha256"]
    confirmation = f"finalize:{manifest['run_id']}:{round_number}:{image_sha256}"
    return {
        "run_id": manifest["run_id"], "round_number": round_number,
        "image_sha256": image_sha256, "confirmation": confirmation,
        "quality_status": "candidate",
    }

def require_finalization_confirmation(manifest: dict[str, object], round_number: int, confirmation: object) -> dict[str, object]:
    candidate = finalization_candidate(manifest, round_number)
    if candidate is None or not isinstance(confirmation, str) or confirmation != candidate["confirmation"]:
        raise ValidationError(
            "finalization_confirmation_mismatch",
            "Finalization confirmation does not match an eligible retained image candidate.",
        )
    return candidate
```

The candidate predicate must duplicate no rubric policy: implement private helpers that read critical dimensions and hard preservation results once, and call the same exported predicate from engine and store integration.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_visual_review -v`

Expected: PASS, including malformed, human/non-human, legacy, image-hash, and wrong-confirmation cases.

- [ ] **Step 6: Commit the isolated contract**

```powershell
git add scripts/local_gpu_imagegen/visual_review.py tests/test_visual_review.py
git commit -m "feat: define user-bound visual review contract"
```

### Task 2: RunStore Review Gate and Budget Recovery

**Files:**
- Modify: `scripts/local_gpu_imagegen/run_store.py:1075`
- Modify: `scripts/local_gpu_imagegen/run_store.py:1403`
- Modify: `tests/test_run_store.py:500`
- Modify: `tests/test_run_store.py:846`

**Interfaces:**
- Consumes: Task 1 `validate_visual_checks`, `visual_checks_pass`, and the shared eligibility predicate.
- Produces: every newly stored review contains validated `visual_checks`; failed/uncertain checks can be stored only with `next_action` `refine` or `explore`; `_quality_status` remains `accepted` only for a fully eligible stored review.

- [ ] **Step 1: Add visual checks to the shared RunStore review fixture and write red regressions**

```python
def visual_checks(self, *, status: str = "pass", prominent_human: bool = True) -> dict[str, object]:
    anatomy_status = status if prominent_human else "not_applicable"
    return {
        "full_resolution_inspected": True,
        "prominent_human": prominent_human,
        "limb_separation": {"status": anatomy_status, "observation": "Observed at full resolution."},
        "feet_and_contact": {"status": anatomy_status, "observation": "Observed at full resolution."},
        "hands_and_held_objects": {"status": anatomy_status, "observation": "Observed at full resolution."},
        "text_and_watermarks": {"status": "pass", "observation": "No text or watermark."},
    }

def test_review_requires_visual_checks_without_manifest_mutation(self) -> None:
    self.complete_initial()
    before = self.store.get(self.manifest["run_id"])
    review = self.review_value()
    review.pop("visual_checks")
    with self.assertRaisesRegex(ValidationError, "invalid_review"):
        self.store.record_review(self.manifest["run_id"], 1, review)
    self.assertEqual(self.store.get(self.manifest["run_id"]), before)

def test_failed_or_uncertain_visual_check_rejects_finalize_without_mutation(self) -> None:
    for status in ("fail", "uncertain"):
        with self.subTest(status=status):
            manifest = self.new_completed_run()
            review = self.review_value(next_action="finalize", visual_status=status)
            with self.assertRaisesRegex(ValidationError, "visual_checks_require_revision"):
                self.store.record_review(manifest["run_id"], 1, review)
            self.assertEqual(self.store.get(manifest["run_id"])["reviews"], [])

def test_failed_visual_check_can_request_refine_and_preserves_round_budget(self) -> None:
    self.complete_initial()
    reviewed = self.store.record_review(
        self.manifest["run_id"], 1,
        self.review_value(next_action="refine", visual_status="fail"),
    )
    self.assertEqual(reviewed["state"], "reviewed")
    self.assertEqual(len(reviewed["rounds"]), 1)
    self.assertEqual(reviewed["request"]["max_rounds"], 3)
```

- [ ] **Step 2: Run RunStore review tests and verify the old exact-field contract fails**

Run: `python -m unittest tests.test_run_store.RunStoreTransitionTests -v`

Expected: FAIL because `visual_checks` is not yet a required field and failed anatomy still accepts `next_action: finalize`.

- [ ] **Step 3: Integrate visual checks before any review mutation**

```python
# run_store.py inside _validate_review
required_fields = {
    "scores", "hard_failures", "critique", "constraint_results", "visual_checks", "next_action",
}
visual_checks = validate_visual_checks(review.get("visual_checks"))
if review.get("next_action") == "finalize" and not visual_checks_pass(visual_checks):
    raise ValidationError(
        "visual_checks_require_revision",
        "Failed or uncertain visual checks cannot request finalization.",
    )
```

Keep this inside the existing `update` callback before `_reviews(manifest).append(...)`, so all validation failures leave the manifest byte-for-byte unchanged.

- [ ] **Step 4: Make stored final quality fail closed on visual evidence**

```python
# run_store.py inside _quality_status
eligible = review_is_eligible(manifest, review)
return "accepted" if eligible else "needs_user_review"
```

Use Task 1's shared eligibility helper so missing legacy checks, hard failures, critical scores, and preservation uncertainty cannot diverge between `RunStore` and `Engine`.

- [ ] **Step 5: Run focused RunStore tests**

Run: `python -m unittest tests.test_run_store -v`

Expected: PASS; new review rejection is pre-mutation and existing finalized-manifest read tests remain green.

- [ ] **Step 6: Commit the storage gate**

```powershell
git add scripts/local_gpu_imagegen/run_store.py tests/test_run_store.py
git commit -m "feat: enforce visual checks before review storage"
```

### Task 3: Candidate Recovery and Pre-Publication Confirmation

**Files:**
- Modify: `scripts/local_gpu_imagegen/engine.py:130`
- Modify: `scripts/local_gpu_imagegen/engine.py:372`
- Modify: `scripts/local_gpu_imagegen/engine.py:380`
- Modify: `scripts/local_gpu_imagegen/engine.py:694`
- Modify: `scripts/local_gpu_imagegen/engine.py:1298`
- Modify: `tests/test_asset_run_engine.py:436`
- Modify: `tests/test_asset_run_engine.py:1735`

**Interfaces:**
- Consumes: Task 1 `finalization_candidate`, `require_finalization_confirmation`, and shared review eligibility.
- Produces: `_review_response(manifest) -> dict[str, object]` with optional `finalization_candidate`; `finalize_run` requires `confirmation`; recovery exposes the same derived candidate after restart; no ineligible round can reach `publish`.

- [ ] **Step 1: Update the engine review helper and write candidate/recovery red tests**

```python
def candidate_confirmation(reviewed: dict[str, object]) -> str:
    return str(reviewed["finalization_candidate"]["confirmation"])

def test_eligible_review_returns_candidate_not_acceptance(self) -> None:
    run_id = self.generated_run()
    reviewed = self.review(run_id, 1)
    self.assertEqual(reviewed["finalization_candidate"]["quality_status"], "candidate")
    self.assertEqual(reviewed["finalization_candidate"]["image_sha256"], reviewed["rounds"][0]["image"]["sha256"])
    self.assertNotIn("accepted", json.dumps(reviewed["finalization_candidate"]))

def test_get_run_recovers_same_candidate_after_restart(self) -> None:
    run_id = self.generated_run()
    reviewed = self.review(run_id, 1)
    restarted = self.new_engine_for_existing_output()
    recovered = restarted.get_run({"run_id": run_id})
    self.assertEqual(recovered["finalization_candidate"], reviewed["finalization_candidate"])

def test_fused_anatomy_rejection_keeps_same_run_budget_and_has_no_candidate(self) -> None:
    run_id = self.generated_run(max_rounds=2)
    reviewed = self.review(
        run_id, 1, score=2, hard_failures=["severe_anatomy"],
        next_action="refine", visual_status="fail",
    )
    self.assertNotIn("finalization_candidate", reviewed)
    self.assertEqual(reviewed["recoverable_next_actions"], ["generate_round:refine", "generate_round:explore"])
    self.assertEqual(reviewed["request"]["max_rounds"], 2)
    self.assertEqual(len(reviewed["rounds"]), 1)
```

- [ ] **Step 2: Write confirmation and no-publication red tests**

```python
def test_finalize_requires_exact_candidate_confirmation_before_copy(self) -> None:
    run_id = self.generated_run()
    reviewed = self.review(run_id, 1)
    run_root = self.output_root / "runs" / run_id
    before = (run_root / "manifest.json").read_bytes()
    for confirmation in (None, "wrong", reviewed["finalization_candidate"]["confirmation"].replace(":1:", ":2:")):
        arguments = {"run_id": run_id, "round_number": 1, "summary": "Selected."}
        if confirmation is not None:
            arguments["confirmation"] = confirmation
        with self.subTest(confirmation=confirmation), self.assertRaisesRegex(
            ValidationError, "finalization_confirmation_mismatch|missing_argument"
        ):
            self.engine.finalize_run(arguments)
        self.assertEqual((run_root / "manifest.json").read_bytes(), before)
        self.assertFalse((run_root / "final.png").exists())

def test_image_byte_change_invalidates_candidate_before_publication(self) -> None:
    run_id = self.generated_run()
    reviewed = self.review(run_id, 1)
    image_path = self.output_root / "runs" / run_id / "round-01.png"
    image_path.write_bytes(b"changed")
    with self.assertRaises(AssetEngineError):
        self.engine.finalize_run({
            "run_id": run_id, "round_number": 1, "summary": "Selected.",
            "confirmation": candidate_confirmation(reviewed),
        })
    self.assertFalse((self.output_root / "runs" / run_id / "final.png").exists())
```

- [ ] **Step 3: Run the engine regressions and verify missing candidate/confirmation failures**

Run: `python -m unittest tests.test_asset_run_engine.AssetRunEngineTests -v`

Expected: FAIL because review/recovery responses have no candidate and finalization accepts no confirmation.

- [ ] **Step 4: Decorate review and recovery responses from retained manifest data**

```python
def _review_response(manifest: dict[str, object]) -> dict[str, object]:
    response = {**manifest, "recoverable_next_actions": recoverable_next_actions(manifest)}
    candidates = [
        candidate for round_value in manifest.get("rounds", [])
        if isinstance(round_value, dict)
        and isinstance(round_value.get("round_number"), int)
        and (candidate := finalization_candidate(manifest, round_value["round_number"])) is not None
    ]
    if candidates:
        response["finalization_candidate"] = candidates[-1]
    return response
```

Call `_review_response` from both `get_run` and `record_review`. Do not persist `finalization_candidate`; recovery must derive it from retained round image metadata and stored review evidence.

- [ ] **Step 5: Verify confirmation before all postprocess and publication side effects**

```python
# engine.py at the start of finalize_run, before postprocess checks and path preparation
confirmation = _required(arguments, "confirmation", str)
manifest = self.store.get(run_id)
require_finalization_confirmation(manifest, round_number, confirmation)
```

Keep the existing run-lock verification in `RunStore.finalize_round_published`; immediately before its `publish` callback, verify the candidate again against the locked manifest and pass the expected confirmation into the store call. Extend `finalize_round_published(..., confirmation: str, ...)` so a race, manifest replacement, or byte-boundary change between engine preflight and lock acquisition cannot publish.

- [ ] **Step 6: Restrict recovery actions to actual candidates**

```python
if _eligible_candidates(manifest):
    actions.append("finalize_run")
if len(rounds) < max_rounds:
    actions.extend(("generate_round:refine", "generate_round:explore"))
return actions or ["get_run"]
```

Remove the exhausted-budget fallback that offered `finalize_run` for an ineligible round. `_eligible_candidates` must use the shared Task 1 predicate, including `next_action: finalize` and visual checks.

- [ ] **Step 7: Update all engine finalization calls to supply the returned candidate confirmation and run focused tests**

Run: `python -m unittest tests.test_asset_run_engine tests.test_anime_vertical_slice tests.test_profile_acceptance_matrix tests.test_revisions -v`

Expected: PASS; eligible finals publish only with exact confirmation, fused anatomy stays reviewed, and child preservation gates still work.

- [ ] **Step 8: Commit the engine authority boundary**

```powershell
git add scripts/local_gpu_imagegen/engine.py scripts/local_gpu_imagegen/run_store.py tests/test_asset_run_engine.py tests/test_anime_vertical_slice.py tests/test_profile_acceptance_matrix.py tests/test_revisions.py
git commit -m "feat: bind finalization to reviewed image bytes"
```

### Task 4: MCP and Skill Temporal Contract

**Files:**
- Modify: `scripts/mcp_server.py:391`
- Modify: `scripts/mcp_server.py:610`
- Modify: `scripts/mcp_server.py:625`
- Modify: `scripts/mcp_server.py:1240`
- Modify: `tests/test_mcp_server.py:85`
- Modify: `tests/test_mcp_server.py:371`
- Modify: `tests/test_mcp_server.py:555`
- Modify: `skills/local-gpu-imagegen/SKILL.md:63`
- Modify: `skills/local-gpu-imagegen/SKILL.md:106`
- Modify: `tests/test_skill_contract.py:149`

**Interfaces:**
- Consumes: Task 3 engine `visual_checks`, `finalization_candidate`, and `confirmation` fields.
- Produces: exact MCP schemas for the nested visual checks and required confirmation; Skill temporal order that stops after candidate display and waits for a later user message.

- [ ] **Step 1: Write MCP exact-schema and forwarding red tests**

```python
def test_review_visual_checks_schema_is_required_and_exact(self) -> None:
    schema = self.tools()["local_gpu_record_review"]["inputSchema"]
    self.assertIn("visual_checks", schema["required"])
    checks = schema["properties"]["visual_checks"]
    self.assertFalse(checks["additionalProperties"])
    self.assertEqual(set(checks["required"]), {
        "full_resolution_inspected", "prominent_human", "limb_separation",
        "feet_and_contact", "hands_and_held_objects", "text_and_watermarks",
    })
    for name in ("limb_separation", "feet_and_contact", "hands_and_held_objects", "text_and_watermarks"):
        self.assertEqual(checks["properties"][name]["properties"]["status"]["enum"], [
            "pass", "fail", "uncertain", "not_applicable",
        ])

def test_finalize_confirmation_is_required(self) -> None:
    schema = self.tools()["local_gpu_finalize_run"]["inputSchema"]
    self.assertIn("confirmation", schema["required"])

def test_review_forwards_visual_checks_unchanged(self) -> None:
    arguments = valid_review_arguments()
    self.call("local_gpu_record_review", arguments)
    self.assertIs(engine.record_review.call_args.args[0]["review"]["visual_checks"], arguments["visual_checks"])
```

- [ ] **Step 2: Run MCP tests and verify missing schema/forwarding failures**

Run: `python -m unittest tests.test_mcp_server -v`

Expected: FAIL because `visual_checks` and finalization `confirmation` are absent from the schemas and dispatch.

- [ ] **Step 3: Add exact nested schemas and dispatch fields**

```python
visual_check = _object_schema({
    "status": {"type": "string", "enum": ["pass", "fail", "uncertain", "not_applicable"]},
    "observation": {"type": "string", "minLength": 1, "maxLength": 500},
}, ["status", "observation"])
visual_checks = _object_schema({
    "full_resolution_inspected": {"type": "boolean", "const": True},
    "prominent_human": {"type": "boolean"},
    "limb_separation": visual_check,
    "feet_and_contact": visual_check,
    "hands_and_held_objects": visual_check,
    "text_and_watermarks": visual_check,
}, [
    "full_resolution_inspected", "prominent_human", "limb_separation",
    "feet_and_contact", "hands_and_held_objects", "text_and_watermarks",
])
```

Add required `visual_checks` to `local_gpu_record_review`, required non-empty `confirmation` to `local_gpu_finalize_run`, `finalization_candidate` to review/get output schemas, and `visual_checks` to the review dispatch tuple.

- [ ] **Step 4: Stage only the new MCP hunks and commit**

```powershell
git add -p scripts/mcp_server.py
git add -p tests/test_mcp_server.py
git diff --cached --check
git diff --cached
git commit -m "feat: expose visual acceptance gates over mcp"
```

At each prompt, leave the pre-existing `subtype` hunks unstaged. Confirm after commit with `git diff -- scripts/mcp_server.py tests/test_mcp_server.py` that those user hunks remain present.

- [ ] **Step 5: Write Skill temporal-order red tests**

```python
def test_visual_acceptance_requires_later_user_turn(self) -> None:
    required = (
        "display the original full-resolution image",
        "quality_status: candidate",
        "wait for a later user message",
        "finalize:<run_id>:<round_number>:<image_sha256>",
    )
    for phrase in required:
        self.assertIn(phrase, self.text)
    self.assertLess(self.text.index("display the original full-resolution image"), self.text.index("wait for a later user message"))
    self.assertLess(self.text.index("wait for a later user message"), self.text.index("`local_gpu_finalize_run`"))

def test_skill_forbids_agent_self_acceptance(self) -> None:
    self.assertIn("A candidate is not accepted until the later user confirmation is verified", self.text)
```

- [ ] **Step 6: Update the Skill review sequence**

```text
generate -> display the original full-resolution image -> inspect required regions
-> local_gpu_record_review with visual_checks
-> display quality_status: candidate, limitations, image SHA-256, and exact
   finalize:<run_id>:<round_number>:<image_sha256>
-> stop and wait for a later user message
-> local_gpu_finalize_run with that exact confirmation
```

State explicitly that preview-only inspection is insufficient, human anatomy cannot be `not_applicable`, uncertainty requires refine/explore, an Agent cannot call a candidate accepted, and an exhausted budget does not permit finalizing an ineligible image.

- [ ] **Step 7: Run MCP and Skill contract tests**

Run: `python -m unittest tests.test_mcp_server tests.test_skill_contract tests.test_verify_mcp -v`

Expected: PASS and the verifier expectation remains exactly fifteen tool names.

- [ ] **Step 8: Commit Skill contract changes**

```powershell
git add skills/local-gpu-imagegen/SKILL.md tests/test_skill_contract.py
git commit -m "docs: require later user visual acceptance"
```

### Task 5: Public Documentation and Complete Verification

**Files:**
- Modify: `README.md:113`
- Modify: `README.md:185`
- Modify: `README.md:189`
- Modify: `docs/architecture.md:44`
- Modify: `docs/architecture.md:58`
- Modify: `docs/architecture.md:64`
- Modify: `docs/troubleshooting.md:121`
- Modify: `tests/test_public_docs.py`
- Modify: `<project-root>\PROJECT_NODES.md`
- Modify: `<project-root>\NEXT_SESSION.md`
- Modify: `<workspace-root>\obsidian\Codex Logs\2026-07-22.md`

**Interfaces:**
- Consumes: verified behavior and exact errors from Tasks 1-4.
- Produces: truthful public workflow wording, recovery instructions, milestone verification record, and next-session boundary.

- [ ] **Step 1: Write public-doc red assertions**

```python
def test_docs_describe_candidate_and_user_bound_confirmation(self) -> None:
    for text in (self.readme, self.architecture):
        self.assertIn("quality status `candidate`", text)
        self.assertIn("finalize:<run_id>:<round_number>:<image_sha256>", text)
        self.assertIn("later user message", text)
    self.assertIn("finalization_confirmation_mismatch", self.troubleshooting)
    self.assertNotIn("An ineligible nomination receives `needs_user_review`", self.readme)
```

- [ ] **Step 2: Update public documentation**

Document the structured checks, derived candidate, exact confirmation, fail-closed recovery, and compatibility boundary. Replace the prior claim that an ineligible nominated round may be finalized; state that it remains a reviewed artifact with refine/explore actions when budget remains and otherwise requires a new user decision without publication.

- [ ] **Step 3: Run focused documentation and contract tests**

Run: `python -m unittest tests.test_public_docs tests.test_skill_contract tests.test_mcp_server tests.test_visual_review -v`

Expected: PASS with candidate wording and exactly fifteen MCP tools.

- [ ] **Step 4: Run the complete model-free gate once**

```powershell
python -m unittest discover -s tests -v
$files = rg --files -g '*.py' scripts tests
python -m py_compile $files
python .\scripts\verify_mcp.py
```

Expected: all tests pass with only the known Windows link-privilege skips; compilation exits `0`; verifier returns `ok: true`, protocol `2024-11-05`, and exactly `15` tools. Do not run a GPU generation because the design requires the mechanism fix before new acceptance work and this change is fully covered model-free.

- [ ] **Step 5: Inspect repository hygiene and preserved user work**

```powershell
git diff --check
git status --short
git diff -- scripts/mcp_server.py tests/test_mcp_server.py
git diff --cached --name-only
```

Expected: no whitespace errors; only the user's `subtype` hunks and `docs/evidence/runs/` remain outside this feature's commits; no evidence run is staged.

- [ ] **Step 6: Update continuity nodes and daily log with measured results**

Record the new control flow, `visual_checks_require_revision` and `finalization_confirmation_mismatch` failure modes, exact test/compile/verifier results, zero GPU generation, preserved `subtype` changes, and next step of restarting `illustration-character` only after a new exact route confirmation.

- [ ] **Step 7: Commit public docs and tracked continuity updates**

```powershell
git add README.md docs/architecture.md docs/troubleshooting.md tests/test_public_docs.py
git commit -m "docs: explain user-bound visual finalization"
```

`PROJECT_NODES.md`, `NEXT_SESSION.md`, and the Obsidian daily log live outside this worktree's tracked surface; update them but do not force them into the feature commit.

- [ ] **Step 8: Commit this ignored implementation plan separately**

```powershell
git add -f docs/superpowers/plans/2026-07-22-user-bound-visual-acceptance.md
git commit -m "docs: plan user-bound visual acceptance"
```

## Self-Review

- Spec coverage: Tasks 1-4 cover every structured field/status/applicability rule, pre-mutation rejection, candidate semantics, byte-bound authority, later-user temporal contract, budget preservation, restart recovery, compatibility, and exact fifteen-tool constraint. Task 5 covers public wording and measured verification.
- Placeholder scan: no deferred implementation markers or unspecified error-handling steps remain; each production change names its interface, red test, expected failure, minimal implementation, focused test, and commit.
- Type consistency: `visual_checks`, `finalization_candidate`, and `confirmation` use the same names and shapes in module, store, engine, MCP, Skill, tests, and docs. The confirmation string always uses the retained round image SHA-256.
- User-work isolation: the only overlapping files require interactive hunk staging, and the plan explicitly leaves `subtype` and `docs/evidence/runs/` untouched.
