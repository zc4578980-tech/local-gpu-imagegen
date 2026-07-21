from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Collection, Mapping
from typing import Protocol

from ..errors import ArtifactError, AssetEngineError, StateError, ValidationError


DEFAULT_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_REQUEST_BYTES = 2 * 1024 * 1024
PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


class BackendAdapter(Protocol):
    backend_id: str
    endpoint_identity: str

    def probe(self) -> dict[str, object]:
        raise NotImplementedError

    def discover(self) -> list[dict[str, object]]:
        raise NotImplementedError

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError

    def cancel_or_query(
        self,
        job_id: str,
        *,
        cancel: bool = False,
    ) -> dict[str, object]:
        raise NotImplementedError


class EndpointPolicy:
    @staticmethod
    def resolve(
        url: str,
        lan_confirmation: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(url, str) or not url.strip():
            raise ValidationError(
                "invalid_backend_endpoint",
                "Backend endpoint must be a non-empty URL.",
            )
        try:
            parsed = urllib.parse.urlsplit(url.strip())
            port = parsed.port or 80
        except ValueError as error:
            raise ValidationError(
                "invalid_backend_endpoint",
                "Backend endpoint has an invalid port.",
            ) from error
        if (
            parsed.scheme != "http"
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError(
                "invalid_backend_endpoint",
                "Backend endpoint must be credential-free root HTTP.",
            )

        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address("127.0.0.1" if host == "localhost" else host)
        except ValueError as error:
            raise ValidationError(
                "invalid_backend_endpoint",
                "Backend host must be localhost or an IP literal in v1.",
            ) from error
        display_host = f"[{host}]" if address.version == 6 and host != "localhost" else host
        canonical = f"http://{display_host}:{port}"
        if address.is_loopback:
            endpoint_class = "loopback"
        elif any(address in network for network in PRIVATE_NETWORKS):
            expected = f"transmit:{canonical}"
            if lan_confirmation != expected:
                raise ValidationError(
                    "lan_confirmation_required",
                    "LAN use requires exact confirmation that prompts and images will be transmitted.",
                    {"confirmation": expected},
                )
            endpoint_class = "lan"
        else:
            raise ValidationError(
                "public_endpoint_rejected",
                "Public Internet generation endpoints are unsupported in v1.",
            )
        return {
            "base_url": canonical,
            "class": endpoint_class,
            "endpoint_identity": "endpoint:"
            + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }


class _CrossOriginRedirectError(OSError):
    pass


class _FrozenOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        super().__init__()
        self.origin = origin

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        if _origin(newurl) != self.origin:
            close = getattr(fp, "close", None)
            if callable(close):
                close()
            raise _CrossOriginRedirectError("cross-origin redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BoundedJsonClient:
    def __init__(
        self,
        base_url: str,
        *,
        lan_confirmation: str | None = None,
        timeout: float = 10.0,
        max_bytes: int = DEFAULT_RESPONSE_BYTES,
        max_request_bytes: int = DEFAULT_REQUEST_BYTES,
    ) -> None:
        endpoint = EndpointPolicy.resolve(base_url, lan_confirmation)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValidationError("invalid_backend_timeout", "Backend timeout must be positive.")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValidationError("invalid_backend_limit", "Backend response limit must be positive.")
        if type(max_request_bytes) is not int or max_request_bytes <= 0:
            raise ValidationError("invalid_backend_limit", "Backend request limit must be positive.")
        self.base_url = str(endpoint["base_url"])
        self.endpoint_identity = str(endpoint["endpoint_identity"])
        self.endpoint_class = str(endpoint["class"])
        self.timeout = float(timeout)
        self.max_bytes = max_bytes
        self.max_request_bytes = max_request_bytes
        self._origin = _origin(self.base_url)
        self._opener = urllib.request.build_opener(
            _FrozenOriginRedirectHandler(self._origin)
        )

    def get_json(self, path: str) -> object:
        return self._decode_json(self._request(path, None, self.max_bytes))

    def post_json(self, path: str, value: object) -> object:
        try:
            body = json.dumps(
                value,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as error:
            raise ValidationError(
                "invalid_backend_request",
                "Backend request must be JSON serializable.",
            ) from error
        if len(body) > self.max_request_bytes:
            raise ValidationError(
                "backend_request_too_large",
                "Backend request exceeded its byte limit.",
            )
        return self._decode_json(self._request(path, body, self.max_bytes))

    def get_bytes(self, path: str, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValidationError("invalid_backend_limit", "Backend response limit must be positive.")
        return self._request(path, None, max_bytes)

    def _decode_json(self, data: bytes) -> object:
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactError(
                "invalid_backend_json",
                "Backend returned malformed JSON.",
            ) from error

    def _request(
        self,
        path: str,
        body: bytes | None,
        limit: int,
    ) -> bytes:
        request_path = _request_path(path)
        request = urllib.request.Request(
            self.base_url + request_path,
            data=body,
            headers={"Content-Type": "application/json"} if body is not None else {},
            method="POST" if body is not None else "GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if _origin(response.geturl()) != self._origin:
                    raise _CrossOriginRedirectError("cross-origin response")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        advertised = int(content_length)
                    except ValueError as error:
                        raise ArtifactError(
                            "invalid_backend_response",
                            "Backend returned an invalid Content-Length.",
                        ) from error
                    if advertised > limit:
                        raise ArtifactError(
                            "backend_response_too_large",
                            "Backend response exceeded its byte limit.",
                        )
                data = response.read(limit + 1)
        except _CrossOriginRedirectError as error:
            raise StateError(
                "backend_redirect_rejected",
                "Backend redirected outside the frozen origin.",
            ) from error
        except urllib.error.HTTPError as error:
            error.close()
            raise StateError(
                "backend_request_failed",
                "Backend HTTP request failed.",
                {"status": error.code},
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise StateError(
                "backend_request_failed",
                "Backend request failed.",
                {"error_type": type(error).__name__},
            ) from error
        if len(data) > limit:
            raise ArtifactError(
                "backend_response_too_large",
                "Backend response exceeded its byte limit.",
            )
        return data


CompatibilityRunner = Callable[[dict[str, object]], dict[str, object]]


class BackendRegistry:
    def __init__(
        self,
        adapters: Collection[BackendAdapter],
        compatibility_runners: Mapping[str, CompatibilityRunner] | None = None,
    ) -> None:
        self._adapters: dict[str, BackendAdapter] = {}
        for adapter in adapters:
            backend_id = getattr(adapter, "backend_id", None)
            if not isinstance(backend_id, str) or not backend_id:
                raise ValidationError(
                    "invalid_backend_adapter",
                    "Backend adapter must have a non-empty ID.",
                )
            if backend_id in self._adapters:
                raise ValidationError(
                    "duplicate_backend_adapter",
                    "Backend adapter IDs must be unique.",
                    {"backend": backend_id},
                )
            self._adapters[backend_id] = adapter
        self._compatibility_runners = dict(compatibility_runners or {})
        overlap = set(self._adapters) & set(self._compatibility_runners)
        if overlap:
            raise ValidationError(
                "duplicate_backend_adapter",
                "Adapter and compatibility backend IDs must not overlap.",
                {"backends": sorted(overlap)},
            )

    def get(self, backend_id: str) -> BackendAdapter:
        try:
            return self._adapters[backend_id]
        except KeyError as error:
            raise ValidationError(
                "unsupported_backend",
                "Backend adapter is not registered.",
                {"backend": backend_id},
            ) from error

    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def probe_all(self) -> dict[str, dict[str, object]]:
        reports: dict[str, dict[str, object]] = {}
        for backend_id, adapter in sorted(self._adapters.items()):
            try:
                reports[backend_id] = adapter.probe()
            except AssetEngineError as error:
                reports[backend_id] = {
                    "backend": backend_id,
                    "ready": False,
                    "error": error.code,
                }
        return reports

    def discover_all(
        self,
        backend_ids: Collection[str] | None = None,
    ) -> list[dict[str, object]]:
        selected = sorted(self._adapters) if backend_ids is None else sorted(backend_ids)
        records: list[dict[str, object]] = []
        for backend_id in selected:
            records.extend(self.get(backend_id).discover())
        return records

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        backend_id = request.get("backend")
        if not isinstance(backend_id, str):
            raise ValidationError(
                "unsupported_backend",
                "Backend request requires a registered backend ID.",
            )
        adapter = self._adapters.get(backend_id)
        if adapter is not None:
            return adapter.generate(request)
        runner = self._compatibility_runners.get(backend_id)
        if runner is not None:
            return runner(request)
        raise ValidationError(
            "unsupported_backend",
            "Backend is not registered.",
            {"backend": backend_id},
        )


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.hostname:
        raise ValueError("URL has no host")
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or 80


def _request_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "\\" in value:
        raise ValidationError(
            "invalid_backend_path",
            "Backend request path must be a root-relative URL path.",
        )
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment or value.startswith("//"):
        raise ValidationError(
            "invalid_backend_path",
            "Backend request path must stay on the frozen origin.",
        )
    return value
