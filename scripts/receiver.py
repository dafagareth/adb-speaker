"""
Project: adb-speaker
Module: receiver.py
Description: Build, bundle, and verify Android receiver DEX bytecode and source markers.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def source_digest():
    digest = hashlib.sha256()
    for source in sorted((ROOT / "native/android").glob("*.java")):
        digest.update(source.name.encode())
        digest.update(b"\0")
        digest.update(source.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def build():
    source = ROOT / "native/android/AdbSpeaker.java"
    output = ROOT / "build"
    dex = output / "classes.dex"
    candidates = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(Path.home() / "Android/Sdk"),
    ]

    def version(path):
        return tuple(map(int, re.findall(r"\d+", path.parent.name)))

    platforms = compilers = []
    for candidate in candidates:
        if candidate:
            sdk = Path(candidate)
            platforms = sorted(sdk.glob("platforms/*/android.jar"), key=version)
            compilers = sorted(
                sdk.glob("build-tools/*/" + ("d8.bat" if os.name == "nt" else "d8")), key=version
            )
            if platforms and compilers:
                break
    if not platforms or not compilers or not shutil.which("javac"):
        raise RuntimeError(
            "Build needs javac and an Android SDK platform/build-tools. Set ANDROID_SDK_ROOT if necessary."
        )
    output.mkdir(exist_ok=True)
    subprocess.run(
        [
            "javac",
            "--release",
            "11",
            "-classpath",
            str(platforms[-1]),
            "-d",
            str(output),
            *map(str, sorted(source.parent.glob("*.java"))),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(compilers[-1]),
            "--min-api",
            "26",
            "--output",
            str(output),
            *map(str, sorted(output.glob("*.class"))),
        ],
        check=True,
    )
    return dex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "bundle", "check"])
    action = parser.parse_args().action
    assets = ROOT / "src/adb_speaker/assets"
    digest = source_digest()
    if action == "check":
        if (
            not (assets / "receiver.dex").is_file()
            or (assets / "receiver.sha256").read_text().strip() != digest
        ):
            raise SystemExit("Receiver source marker differs. Run make bundle-receiver.")
        print("Receiver source marker matches; this is not a DEX provenance check.")
    else:
        dex = build()
        if action == "bundle":
            shutil.copy2(dex, assets / "receiver.dex")
            (assets / "receiver.sha256").write_text(digest + "\n")
        print(dex)


if __name__ == "__main__":
    main()
