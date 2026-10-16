"""
Project: adb-speaker
Module: build.py (Linux Packaging)
Description: Builds standalone relocatable Linux x86_64 portable bundle.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import hashlib
import importlib.metadata
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile

root = Path(__file__).resolve().parents[2]
if subprocess.check_output(["uname", "-m"], text=True).strip() != "x86_64":
    raise SystemExit("The portable build currently supports x86_64 only.")
subprocess.run(["python3", "scripts/receiver.py", "check"], cwd=root, check=True)
subprocess.run(
    [
        "pyinstaller",
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
        "/usr/bin/adb:bin",
        "--add-binary",
        "/usr/bin/parec:bin",
        "speaker.py",
    ],
    cwd=root,
    check=True,
)
bundle = root / "dist/adb-speaker"
# PyInstaller excludes some system libraries (such as XCB) needed by parec.
# Keep glibc on the host, but copy the helper programs' other linked dependencies.
glibc = {"libc.so.6", "libm.so.6", "libpthread.so.0", "librt.so.1", "libdl.so.2"}
for helper in ("/usr/bin/adb", "/usr/bin/parec"):
    linked = subprocess.check_output(["ldd", helper], text=True)
    if "not found" in linked:
        raise SystemExit("Unresolved library for " + helper)
    for filename in re.findall(r"=> (/\S+)", linked):
        library = Path(filename)
        destination = bundle / "_internal" / library.name
        if library.name not in glibc and not destination.exists():
            shutil.copy2(library, destination)
for name in ("LICENSE", "README.md", "CHANGELOG.md", "SECURITY.md"):
    shutil.copy2(root / name, bundle / name)
shutil.copytree(root / "docs", bundle / "docs", dirs_exist_ok=True)
# Keep upstream redistribution notices beside the binaries and their libraries.
licenses = bundle / "licenses"
licenses.mkdir(exist_ok=True)
shutil.copytree("/usr/share/common-licenses", licenses / "common", dirs_exist_ok=True)
for copyright_file in Path("/usr/share/doc").glob("*/copyright"):
    shutil.copy2(copyright_file, licenses / (copyright_file.parent.name + ".copyright"))
for distribution in ("pyinstaller", "pyinstaller-hooks-contrib"):
    metadata = importlib.metadata.distribution(distribution)
    for item in metadata.files or []:
        if any(word in item.name.lower() for word in ("license", "copying")):
            source = Path(metadata.locate_file(item))
            if source.is_file():
                shutil.copy2(source, licenses / (distribution + "-" + item.name))
(licenses / "packages.txt").write_text(
    subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package} ${Version} ${source:Package} ${source:Version}\n"],
        text=True,
    )
)
subprocess.run([str(bundle / "adb-speaker"), "--help"], check=True, stdout=subprocess.DEVNULL)
env = {**os.environ, "LD_LIBRARY_PATH": str(bundle / "_internal")}
for command in (["adb", "version"], ["parec", "--version"]):
    subprocess.run(
        [str(bundle / "_internal/bin" / command[0]), *command[1:]],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )

with tarfile.open(root / "dist/adb-speaker-linux-x86_64.tar.gz", "w:gz") as archive:
    archive.add(bundle, arcname="adb-speaker")

# Keep the exact project sources and packaging instructions beside the binary.
source_archive = root / "dist/adb-speaker-source.tar.gz"
with tarfile.open(source_archive, "w:gz") as archive:
    for name in (
        "speaker.py",
        "src",
        "native",
        "tests",
        "pyproject.toml",
        "MANIFEST.in",
        "Makefile",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "docs",
        "scripts",
        "packaging",
        ".github",
        ".dockerignore",
        ".gitignore",
    ):
        archive.add(
            root / name,
            arcname="adb-speaker/" + name,
            filter=lambda item: None
            if "__pycache__" in item.name or ".egg-info" in item.name
            else item,
        )
archives = [root / "dist/adb-speaker-linux-x86_64.tar.gz", source_archive]
(root / "dist/SHA256SUMS").write_text(
    "".join(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in archives
    )
)
