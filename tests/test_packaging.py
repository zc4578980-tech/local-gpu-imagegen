from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import venv
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.temp = Path(cls.temporary_directory.name)
        cls.wheel_dir = cls.temp / "wheel"
        cls.wheel_dir.mkdir()
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--wheel-dir",
                str(cls.wheel_dir),
                "--no-deps",
                "--no-build-isolation",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise AssertionError(f"wheel build failed:\n{completed.stdout}\n{completed.stderr}")
        wheels = list(cls.wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise AssertionError(f"expected one wheel, found: {wheels}")
        cls.wheel = wheels[0]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_metadata_defines_preview_cli(self) -> None:
        document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = document["project"]
        self.assertEqual(project["version"], "0.6.0")
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(
            project["scripts"]["local-gpu-imagegen"],
            "local_gpu_imagegen.cli:main",
        )

    def test_wheel_contains_runtime_modules_and_immutable_assets(self) -> None:
        with zipfile.ZipFile(self.wheel) as archive:
            names = set(archive.namelist())
        required_suffixes = {
            "mcp_server.py",
            "verify_mcp.py",
            "check_gpu.py",
            "generate_image.py",
            "share/local-gpu-imagegen/profiles/base.json",
            "share/local-gpu-imagegen/profiles/use-cases/standalone-illustration.json",
            "share/local-gpu-imagegen/workflows/comfyui/sdxl-txt2img-v1.json",
            "share/local-gpu-imagegen/skills/local-gpu-imagegen/SKILL.md",
        }
        for suffix in required_suffixes:
            with self.subTest(suffix=suffix):
                self.assertTrue(any(name.endswith(suffix) for name in names), suffix)
        self.assertFalse(any("outputs/" in name or name.endswith(".safetensors") for name in names))

    def test_installed_wheel_verifies_from_outside_checkout(self) -> None:
        environment_dir = self.temp / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_dir)
        python = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = environment_dir / ("Scripts/local-gpu-imagegen.exe" if os.name == "nt" else "bin/local-gpu-imagegen")
        subprocess.run(
            [str(python), "-m", "pip", "install", str(self.wheel), "--no-deps"],
            cwd=self.temp,
            capture_output=True,
            text=True,
            check=True,
        )
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [str(cli), "verify"],
            cwd=self.temp,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["tools"]), 15)


if __name__ == "__main__":
    unittest.main()
