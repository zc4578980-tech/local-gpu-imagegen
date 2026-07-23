from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.services import RuntimeServices, build_services  # noqa: E402


class RuntimeServicesTests(unittest.TestCase):
    def test_build_services_composes_one_shared_runtime_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = lambda request: dict(request)  # noqa: E731
            capabilities = lambda: {  # noqa: E731
                "available_backends": ["diffusers"],
                "diffusers_ready": True,
            }
            with patch(
                "local_gpu_imagegen.services.adapters_from_environment",
                return_value=[],
            ):
                services = build_services(
                    ROOT,
                    root / "outputs",
                    root / "state",
                    capabilities,
                    runner,
                )

        self.assertIsInstance(services, RuntimeServices)
        self.assertIs(services.engine.catalog, services.catalog)
        self.assertIs(services.engine.router, services.router)
        self.assertIs(services.engine.compilers, services.router.compilers)
        self.assertIs(services.discovery.adapters, services.backends)
        self.assertIs(
            services.router.layout_capability_provider.__self__,
            services.backends,
        )


if __name__ == "__main__":
    unittest.main()
