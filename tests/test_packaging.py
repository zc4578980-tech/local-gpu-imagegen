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


def write_fake_client(directory: Path, name: str, marker: Path) -> None:
    if os.name == "nt":
        script = directory / f"{name}.cmd"
        script.write_text(
            "@echo off\n"
            "if \"%1\"==\"--version\" (echo codex-cli test& exit /b 0)\n"
            "if \"%1\"==\"mcp\" if \"%2\"==\"get\" exit /b 1\n"
            f"if \"%1\"==\"mcp\" if \"%2\"==\"add\" (echo called>\"{marker}\"& exit /b 0)\n"
            "exit /b 2\n",
            encoding="utf-8",
        )
        return

    script = directory / name
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'codex-cli test'; exit 0; fi\n"
        "if [ \"$1\" = \"mcp\" ] && [ \"$2\" = \"get\" ]; then exit 1; fi\n"
        f"if [ \"$1\" = \"mcp\" ] && [ \"$2\" = \"add\" ]; then echo called > '{marker}'; exit 0; fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


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
        cls.environment_dir = cls.temp / "venv"
        venv.EnvBuilder(with_pip=True).create(cls.environment_dir)
        cls.python = cls.environment_dir / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        cls.cli = cls.environment_dir / (
            "Scripts/local-gpu-imagegen.exe"
            if os.name == "nt"
            else "bin/local-gpu-imagegen"
        )
        subprocess.run(
            [str(cls.python), "-m", "pip", "install", str(cls.wheel), "--no-deps"],
            cwd=cls.temp,
            capture_output=True,
            text=True,
            check=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_metadata_defines_preview_cli(self) -> None:
        document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = document["project"]
        self.assertEqual(project["version"], "0.6.1")
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(
            project["scripts"]["local-gpu-imagegen"],
            "local_gpu_imagegen.cli:main",
        )

    def test_wheel_contains_runtime_modules_and_immutable_assets(self) -> None:
        with zipfile.ZipFile(self.wheel) as archive:
            names = set(archive.namelist())
        self.assertIn("local_gpu_imagegen/regional_layout.py", names)
        required_suffixes = {
            "mcp_server.py",
            "verify_mcp.py",
            "build_showcase.py",
            "export_real_demo.py",
            "validate_client_sessions.py",
            "validate_real_demo.py",
            "check_gpu.py",
            "generate_image.py",
            "share/local-gpu-imagegen/profiles/base.json",
            "share/local-gpu-imagegen/profiles/use-cases/standalone-illustration.json",
            "share/local-gpu-imagegen/workflows/comfyui/sdxl-txt2img-v1.json",
            "share/local-gpu-imagegen/workflows/comfyui/sdxl-regional-txt2img-v1.json",
            "share/local-gpu-imagegen/skills/local-gpu-imagegen/SKILL.md",
            "share/local-gpu-imagegen/evidence/schemas/client-session.schema.json",
            "share/local-gpu-imagegen/evidence/schemas/real-demo.schema.json",
        }
        for suffix in required_suffixes:
            with self.subTest(suffix=suffix):
                self.assertTrue(any(name.endswith(suffix) for name in names), suffix)
        self.assertFalse(any("outputs/" in name or name.endswith(".safetensors") for name in names))

    def test_installed_wheel_verifies_from_outside_checkout(self) -> None:
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [str(self.cli), "verify"],
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

    def test_installed_wheel_exposes_read_only_setup_outside_checkout(self) -> None:
        fake_bin = self.temp / "fake-bin"
        fake_bin.mkdir(exist_ok=True)
        marker = fake_bin / "add-called"
        write_fake_client(fake_bin, "codex", marker)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")

        completed = subprocess.run(
            [str(self.cli), "setup", "codex"],
            cwd=self.temp,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "planned")
        self.assertFalse(report["applied"])
        self.assertEqual(
            report["server"]["command"],
            ["local-gpu-imagegen", "serve"],
        )
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
