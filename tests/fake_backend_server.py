from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(slots=True)
class FakeResponse:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, value: object, status: int = 200) -> "FakeResponse":
        return cls(
            status=status,
            body=json.dumps(value).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )


Route = FakeResponse | Callable[[str, str, bytes], FakeResponse]


class FakeBackendServer:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Route] = {}
        self.requests: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self._respond()

            def do_POST(self) -> None:  # noqa: N802
                self._respond()

            def _respond(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                owner.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "headers": dict(self.headers.items()),
                })
                route = owner.routes.get((self.command, self.path))
                if route is None:
                    response = FakeResponse.json({"error": "not found"}, status=404)
                elif callable(route):
                    response = route(self.command, self.path, body)
                else:
                    response = route
                self.send_response(response.status)
                for name, value in response.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                self.wfile.write(response.body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self._server.server_address
        self.url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeBackendServer":
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
