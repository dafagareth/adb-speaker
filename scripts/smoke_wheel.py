"""
Project: adb-speaker
Module: smoke_wheel.py
Description: Install the built wheel into a fresh venv and run CLI smoke tests.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import os
from pathlib import Path
import subprocess
import tempfile
import venv

root = Path(__file__).resolve().parents[1]
wheels = list((root / "dist").glob("adb_speaker-*.whl"))
if len(wheels) != 1:
    raise SystemExit("Expected exactly one wheel in dist/. Remove stale wheels first.")
with tempfile.TemporaryDirectory() as temp:
    env_dir = Path(temp) / "env"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    executable = bindir / ("adb-speaker.exe" if os.name == "nt" else "adb-speaker")
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])], check=True)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PATH"] = ""
    for args in ([str(executable), "--help"], [str(python), "-m", "adb_speaker", "--version"]):
        subprocess.run(args, cwd=temp, env=env, check=True)
    subprocess.run(
        [
            str(python),
            "-c",
            "from adb_speaker.session import receiver_path; "
            'assert receiver_path().read_bytes().startswith(b"dex\\n")',
        ],
        cwd=temp,
        env=env,
        check=True,
    )
    result = subprocess.run(
        [str(executable), "tone"], cwd=temp, env=env, capture_output=True, text=True
    )
    if result.returncode != 1 or "Required command is missing: adb" not in result.stderr:
        raise SystemExit("Missing-dependency smoke check failed: " + result.stderr)
