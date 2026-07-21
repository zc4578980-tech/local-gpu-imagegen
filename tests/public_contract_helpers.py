from __future__ import annotations

import re
from collections.abc import Iterable


_STALE_ACTIVE_VERSION = re.compile(r"\b(?:v|version\s*)?0\.3(?:\.0)?\b", re.IGNORECASE)
_ASSERTION_BOUNDARY = re.compile(
    r"[:;.!?]+\s*(?:(?:however|nevertheless|nonetheless|still|yet)\s*,?\s*)?"
    r"|,\s*(?:and|but|or|nor|yet|however|though|although|even\s+though)\b\s*"
    r"|\s+(?:but|although|even\s+though|yet)\b\s*",
    re.IGNORECASE,
)
_TERMINAL_NEGATION = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|doesn't|isn't|aren't|wasn't|weren't|"
    r"hasn't|haven't|has not|have not|does not|do not)\b",
    re.IGNORECASE,
)
_NOT_ONLY = re.compile(r"\bnot\s+only\b", re.IGNORECASE)
_DOUBLE_NEGATIVE_PREDICATE = re.compile(
    r"\bnot\s+(?P<predicate>absent|unavailable|unapproved|disabled|unsupported|unverified|unvalidated)\b",
    re.IGNORECASE,
)

_CLAIM_RULES = tuple(
    (category, re.compile(pattern, re.IGNORECASE))
    for category, pattern in (
        ("host", r"\b(?:codex|hosts?|clients?)\b.{0,48}?\b(?:is|are|was|were|has been)\s+(?:not\s+)?(?:a\s+)?(?P<predicate>verified|validated|supported)\s+hosts?\b"),
        ("host", r"\bcodex\s+(?P<predicate>verified|validated|supported)\s+host\b"),
        ("host", r"\b(?P<predicate>verified|validated|supported)\s+(?:on|with|by)\s+codex\b"),
        ("real", r"\breal\s+(?:codex|vision|gpu|backend|generation|image|output|host)(?:\s+(?:generation|output|acceptance|execution|review|host))?.{0,48}?\b(?:is|are|was|were|has been)\s+(?:not\s+)?(?P<predicate>accepted|approved|verified|validated|ready|available|selectable|supported)\b"),
        ("real", r"\bretained\s+real\s+(?:codex|vision|model|gpu|backend|image|real-esrgan).{0,64}?\bevidence\s+(?P<predicate>exists|available)\b"),
        ("model", r"\bproduction\s+model\b.{0,32}?\b(?:is|are|was|were|has been)\s+(?:currently\s+)?(?:not\s+)?(?P<predicate>bundled|included|approved|enabled|ready|available|selectable|verified|validated|supported)\b"),
        ("model", r"\bproduction[- ](?P<predicate>ready|proven|verified)\b"),
        ("model", r"\b(?P<predicate>bundled|included)\b.{0,40}?\b(?:approved|production|ready|enabled)\s+model\b"),
        ("model", r"\b(?P<predicate>approved)\s+(?:catalog\s+)?(?:production\s+)?model\s+(?:selection|available|included|bundled|ready)\b"),
        ("model", r"\blicense(?:\s+(?:record|status))?\s+(?:is|are|was|were|has been)\s+(?:not\s+)?(?P<predicate>approved|ready|verified|available|present|enabled)\b"),
        ("model", r"\b(?:an?\s+)?approved\s+license\s+(?:record|status)\s+(?:is|are|was|were|has been)\s+(?P<predicate>approved|ready|verified|available|present|enabled)\b"),
        ("model", r"\b(?P<predicate>approved)\s+license\s+for\b"),
        ("quality", r"\b(?:quality|performance|vram)\s+(?:is|was|are|has been)\s+(?P<predicate>verified|proven|measured)\b"),
        ("quality", r"\b(?P<predicate>production|professional|high)[- ]quality\b"),
        ("performance", r"\b(?P<predicate>uses?|requires?|needs?)\s+\d+(?:\.\d+)?\s*(?:gb|gib)\s+(?:of\s+)?vram\b"),
        ("performance", r"\b(?P<predicate>\d+(?:\.\d+)?\s*(?:x|%|percent))\s+(?:faster|speedup)\b"),
        ("popularity", r"\b(?P<predicate>five|[1-5])[- ]star(?:s| rating)?\b"),
        ("future", r"\b(?P<predicate>supports|includes|ships|provides)\b.{0,80}?\b(?:masks?|child revisions?|ppt|ui|v0\.5)\b"),
    )
)

_CATEGORY_HINTS = (
    ("model", re.compile(r"\b(?:production\s+model|model|license|sd-turbo)\b", re.IGNORECASE)),
    ("real", re.compile(r"\breal\s+(?:codex|vision|gpu|backend|generation|image|output|host)\b", re.IGNORECASE)),
    ("host", re.compile(r"\b(?:codex|hosts?|clients?)\b", re.IGNORECASE)),
    ("quality", re.compile(r"\b(?:quality|performance|vram)\b", re.IGNORECASE)),
)
_INHERITED_TAIL = re.compile(
    r"^\s*(?:(?:it|they|this|that|the result|the output|the model)\s+"
    r"(?:is|are|was|were|has been|remains?)\s+(?:(?:currently|now|already|also)\s+)?(?:not\s+)?\s*)?"
    r"(?P<predicate>accepted|approved|verified|validated|ready|available|selectable|enabled|supported)\b",
    re.IGNORECASE,
)

_PLUGIN_EDIT_SCOPE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bimage[- ]to[- ]image\b",
        r"\bimg2img\b",
        r"\binpaint(?:ing)?\b",
        r"\bmasks?\b",
    )
)

PLUGIN_REQUIRED_BOUNDARIES = (
    "catalog-gated model resolution",
    "no production model is bundled or currently approved",
    "real host/gpu output acceptance remains unverified",
)


def user_facing_strings(value: object, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        result: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            result.extend(user_facing_strings(item, f"{path}[{index}]"))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            result.extend(user_facing_strings(item, f"{path}.{key}"))
        return result
    return []


def _assertion_clauses(text: str) -> list[str]:
    return [clause.strip() for clause in _ASSERTION_BOUNDARY.split(text) if clause.strip()]


def _claim_category(clause: str) -> str | None:
    for category, pattern in _CATEGORY_HINTS:
        if pattern.search(clause):
            return category
    return None


def _terminal_is_negated(clause: str, match: re.Match[str]) -> bool:
    predicate_start = match.start("predicate")
    scope_start = max(0, match.start() - 12)
    predicate_scope = _NOT_ONLY.sub("", clause[scope_start:predicate_start])
    return _TERMINAL_NEGATION.search(predicate_scope) is not None


def _append_finding(findings: list[str], clause: str) -> None:
    if clause not in findings:
        findings.append(clause)


def unsupported_release_claims(public_copy: str) -> list[str]:
    findings: list[str] = []
    for line in public_copy.splitlines():
        inherited_category: str | None = None
        for clause in _assertion_clauses(line):
            explicit_category = _claim_category(clause)
            effective_category = explicit_category or inherited_category
            for _, pattern in _CLAIM_RULES:
                for match in pattern.finditer(clause):
                    if not _terminal_is_negated(clause, match):
                        _append_finding(findings, clause)
            if effective_category in {"host", "real", "model"}:
                double_negative = _DOUBLE_NEGATIVE_PREDICATE.search(clause)
                if double_negative is not None:
                    _append_finding(findings, clause)
                inherited_tail = _INHERITED_TAIL.search(clause) if explicit_category is None else None
                if inherited_tail is not None and not _terminal_is_negated(clause, inherited_tail):
                    _append_finding(findings, clause)
            if explicit_category is not None:
                inherited_category = explicit_category
    return findings


def plugin_discovery_findings(plugin: dict[str, object]) -> list[str]:
    strings = user_facing_strings(plugin)
    combined = "\n".join(value for _, value in strings).lower()
    findings = [
        f"Missing discovery boundary: {required}"
        for required in PLUGIN_REQUIRED_BOUNDARIES
        if required not in combined
    ]
    for path, value in strings:
        for claim in unsupported_release_claims(value):
            findings.append(f"Unsupported discovery claim at {path}: {claim}")
        for pattern in _PLUGIN_EDIT_SCOPE:
            if pattern.search(value):
                findings.append(f"Low-level edit scope in discovery at {path}: {value}")
                break
    return findings


def active_version_findings(documents: Iterable[tuple[str, str]]) -> list[str]:
    findings: list[str] = []
    for name, content in documents:
        for line_number, line in enumerate(content.splitlines(), start=1):
            if _STALE_ACTIVE_VERSION.search(line):
                findings.append(f"{name}:{line_number}: {line.strip()}")
    return findings
