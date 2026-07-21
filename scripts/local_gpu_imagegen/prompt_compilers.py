from __future__ import annotations

from .errors import ValidationError


COMPILER_VERSIONS = {
    "natural-v1": 1,
    "sd15-tags-v1": 1,
}


class PromptCompilerRegistry:
    def compile(
        self,
        compiler_id: str,
        positive: str,
        negative: str,
    ) -> dict[str, object]:
        if compiler_id not in COMPILER_VERSIONS:
            raise ValidationError(
                "unknown_prompt_compiler",
                "Prompt compiler is not registered.",
            )
        if not isinstance(positive, str) or not isinstance(negative, str):
            raise ValidationError(
                "invalid_prompt",
                "Prompts must be strings.",
            )
        if compiler_id == "natural-v1":
            compiled_positive = " ".join(positive.split())
            compiled_negative = " ".join(negative.split())
        else:
            compiled_positive = _tags(positive)
            compiled_negative = _tags(negative)
        if not compiled_positive:
            raise ValidationError(
                "invalid_prompt",
                "Positive prompt cannot be empty after compilation.",
            )
        return {
            "compiler_id": compiler_id,
            "compiler_version": COMPILER_VERSIONS[compiler_id],
            "positive_prompt": compiled_positive,
            "negative_prompt": compiled_negative,
        }

    def version(self, compiler_id: str) -> int:
        try:
            return COMPILER_VERSIONS[compiler_id]
        except KeyError as error:
            raise ValidationError(
                "unknown_prompt_compiler",
                "Prompt compiler is not registered.",
            ) from error


def _tags(value: str) -> str:
    return ", ".join(part.strip() for part in value.split(",") if part.strip())
