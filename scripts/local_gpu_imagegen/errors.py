from __future__ import annotations


class AssetEngineError(Exception):
    def __init__(self, code: str, message: str, category: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.details = details or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.args[0]}"


class ValidationError(AssetEngineError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "validation", details)


class StateError(AssetEngineError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "state", details)


class ConflictError(AssetEngineError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "conflict", details)


class ArtifactError(AssetEngineError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "artifact", details)
