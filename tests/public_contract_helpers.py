from __future__ import annotations

import re
from collections.abc import Iterable


_STALE_ACTIVE_VERSION = re.compile(r"\b(?:v|version\s*)?0\.3(?:\.0)?\b", re.IGNORECASE)
_CLAUSE_BOUNDARY = re.compile(
    r"[:,;.!?]|,?\s+\b(?:and|but|or|nor|yet|however|though)\b\s*",
    re.IGNORECASE,
)
_LOCAL_NEGATION = re.compile(
    r"\b(?:no|not|never|without|neither|cannot|can't|doesn't|isn't|aren't|"
    r"wasn't|weren't|hasn't|haven't|has not|have not|does not|do not)\b",
    re.IGNORECASE,
)
_DOUBLE_NEGATION = re.compile(
    r"\bnot\s+(?:unverified|unvalidated|disabled|unapproved|unsupported|unavailable)\b|\bnot\s+only\b",
    re.IGNORECASE,
)

_RELEASE_CLAIM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bcodex\b[^\n.]{0,80}\b(?:verified|validated|supported)\s+host\b",
        r"\bverified\s+(?:on|with|by)\s+codex\b",
        r"\breal\s+(?:codex|vision|gpu|generation|image)[^\n.]{0,80}\b(?:accepted|approved|verified|validated)\b",
        r"\bretained\s+real\s+(?:codex|vision|model|gpu|image|real-esrgan)[^\n.]{0,80}\bevidence\s+exists\b",
        r"\bproduction[- ](?:ready|proven|verified)\b",
        r"\bproduction\s+model[^\n.]{0,80}\b(?:bundled|included|approved|enabled|ready)\b",
        r"\b(?:bundles?|bundled|includes?|ships with|comes with)[^\n.]{0,40}\b(?:approved|production|ready|enabled)\s+model\b",
        r"\bapproved\s+(?:catalog\s+)?(?:production\s+)?model\s+(?:selection|available|included|bundled|ready)\b",
        r"\b(?:sd-turbo|model)[^\n.]{0,40}\blicense\s+(?:is\s+)?approved\b",
        r"\blicense\s+(?:is\s+)?approved\b",
        r"\bapproved\s+license\s+(?:record|status|for)\b",
        r"\b(?:production\s+)?model\b[^\n.]{0,24}\bnot\s+disabled\b",
        r"\blicense\b[^\n.]{0,16}\bnot\s+unapproved\b",
        r"\breal\s+(?:codex|vision|gpu|generation|image)[^\n.]{0,60}\bnot\s+(?:unverified|unvalidated|unsupported)\b",
        r"\b(?:quality|performance|vram)\s+(?:is|was|are|has been)\s+(?:verified|proven|measured)\b",
        r"\b(?:production|professional|high)[- ]quality\b",
        r"\b(?:uses?|requires?|needs?)\s+\d+(?:\.\d+)?\s*(?:gb|gib)\s+(?:of\s+)?vram\b",
        r"\b\d+(?:\.\d+)?\s*(?:x|%|percent)\s+(?:faster|speedup)\b",
        r"\b(?:five|[1-5])[- ]star(?:s| rating)?\b",
        r"\b(?:supports|includes|ships|provides)\b[^\n.]{0,80}\b(?:masks?|child revisions?|ppt|ui|v0\.5)\b",
    )
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


def _local_clause(text: str, start: int, end: int) -> str:
    left = 0
    right = len(text)
    for boundary in _CLAUSE_BOUNDARY.finditer(text):
        if boundary.end() <= start:
            left = boundary.end()
        elif boundary.start() >= end:
            right = boundary.start()
            break
    return text[left:right].strip()


def _is_locally_negated(clause: str) -> bool:
    without_double_negation = _DOUBLE_NEGATION.sub("", clause)
    return _LOCAL_NEGATION.search(without_double_negation) is not None


def unsupported_release_claims(public_copy: str) -> list[str]:
    findings: list[str] = []
    for line in public_copy.splitlines():
        for pattern in _RELEASE_CLAIM_PATTERNS:
            for match in pattern.finditer(line):
                clause = _local_clause(line, match.start(), match.end())
                if _is_locally_negated(clause):
                    continue
                if clause and clause not in findings:
                    findings.append(clause)
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
