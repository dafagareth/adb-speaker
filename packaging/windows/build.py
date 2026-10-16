"""
Project: adb-speaker
Module: build.py (Windows Packaging)
Description: Builds standalone portable Windows ZIP archive with WASAPI helper.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
if os.name != "nt":
    raise SystemExit("Build this package on Windows with MSVC and CMake installed.")

PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools_r35.0.0-windows.zip"
PLATFORM_TOOLS_SHA256 = "7ab78a8f8b305ae4d0de647d99c43599744de61a0838d3a47bda0cdffefee87e"


def get_platform_tools():
    downloads = root / "build/downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / "platform-tools_r35.0.0-windows.zip"
    if (
        not archive.is_file()
        or hashlib.sha256(archive.read_bytes()).hexdigest() != PLATFORM_TOOLS_SHA256
    ):
        import urllib.request

        urllib.request.urlretrieve(PLATFORM_TOOLS_URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != PLATFORM_TOOLS_SHA256:
        raise SystemExit(f"Checksum mismatch for platform-tools: {digest}")
    tools_dir = root / "build/windows/platform-tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    import zipfile

    with zipfile.ZipFile(archive) as zf:
        for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt"):
            (tools_dir / name).write_bytes(zf.read("platform-tools/" + name))
    return tools_dir


subprocess.run([sys.executable, "scripts/receiver.py", "check"], cwd=root, check=True)
subprocess.run(
    ["cmake", "-S", "native/windows", "-B", "build/windows", "-A", "x64"], cwd=root, check=True
)
subprocess.run(["cmake", "--build", "build/windows", "--config", "Release"], cwd=root, check=True)
subprocess.run(
    ["ctest", "--test-dir", "build/windows", "-C", "Release", "--output-on-failure"],
    cwd=root,
    check=True,
)
tools_dir = get_platform_tools()
subprocess.run(
    [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "adb-speaker",
        "--paths",
        "src",
        "--collect-data",
        "adb_speaker",
        "--add-binary",
        "build/windows/Release/wasapi_capture.exe:bin",
        "--add-binary",
        f"{tools_dir / 'adb.exe'}:bin",
        "--add-binary",
        f"{tools_dir / 'AdbWinApi.dll'}:bin",
        "--add-binary",
        f"{tools_dir / 'AdbWinUsbApi.dll'}:bin",
        "speaker.py",
    ],
    cwd=root,
    check=True,
)
bundle = root / "dist/adb-speaker"
bin_dir = bundle / "_internal/bin"
bin_dir.mkdir(parents=True, exist_ok=True)
for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"):
    dest = bin_dir / name
    if not dest.is_file():
        shutil.copy2(tools_dir / name, dest)

for name in ("README.md", "LICENSE", "CHANGELOG.md"):
    shutil.copy2(root / name, bundle / name)
shutil.copytree(root / "docs", bundle / "docs", dirs_exist_ok=True)
licenses = bundle / "licenses"
licenses.mkdir(exist_ok=True)
shutil.copy2(tools_dir / "NOTICE.txt", licenses / "Android-Platform-Tools-NOTICE.txt")
for name in ("pyinstaller", "pyinstaller-hooks-contrib"):
    dist = importlib.metadata.distribution(name)
    for file in dist.files or []:
        if "license" in file.name.lower() or "copying" in file.name.lower():
            source = Path(dist.locate_file(file))
            if source.is_file():
                shutil.copy2(source, licenses / (name + "-" + file.name))
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if not python_license.is_file():
    raise SystemExit("Python LICENSE.txt is missing; cannot package without its notice.")
shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
(licenses / "packages.txt").write_text(
    subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
)
# Run outside the checkout with no Python, ADB, or capture helper on PATH.
# Isolate from attached phones and inherited device serials.
env = {k: v for k, v in os.environ.items() if k not in ("PATH", "ANDROID_SERIAL")}
env["PATH"] = ""
subprocess.run(
    [str(bundle / "adb-speaker.exe"), "--help"], cwd=bundle, env=env, check=True, timeout=15
)
subprocess.run(
    [str(bin_dir / "adb.exe"), "version"],
    cwd=bundle,
    env=env,
    check=True,
    stdout=subprocess.DEVNULL,
    timeout=15,
)
result = subprocess.run(
    [str(bundle / "adb-speaker.exe"), "tone", "--serial", "nonexistent-smoke-device"],
    cwd=bundle,
    env=env,
    capture_output=True,
    text=True,
    timeout=15,
)
if result.returncode != 1 or "device 'nonexistent-smoke-device' not found" not in result.stderr:
    raise SystemExit("Portable self-contained check failed: " + result.stderr)
archive = Path(
    shutil.make_archive(
        str(root / "dist/adb-speaker-windows-x86_64"), "zip", root / "dist", "adb-speaker"
    )
)
(root / "dist/SHA256SUMS").write_text(
    hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n"
)
