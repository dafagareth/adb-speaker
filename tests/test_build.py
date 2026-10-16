"""
Project: adb-speaker
Module: test_build.py
Description: Unit tests for receiver compilation, SDK lookup, and source marker verification.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import receiver as speaker


class Tests(unittest.TestCase):
    def test_build_requires_sdk_and_javac(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "native/android").mkdir(parents=True)
            (root / "native/android/AdbSpeaker.java").write_text("// fixture")
            with (
                patch.object(speaker, "ROOT", root),
                patch.object(speaker.Path, "home", return_value=root),
                patch.dict(os.environ, {"ANDROID_HOME": "", "ANDROID_SDK_ROOT": ""}),
                patch.object(speaker.shutil, "which", return_value=None),
            ):
                with self.assertRaisesRegex(RuntimeError, "Build needs javac"):
                    speaker.build()

    def test_build_falls_back_from_stale_sdk_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            (project / "native/android").mkdir(parents=True)
            (project / "native/android/AdbSpeaker.java").write_text("// fixture")
            sdk = root / "Android/Sdk"
            for item in [
                "platforms/android-37/android.jar",
                "build-tools/36.0.0/" + ("d8.bat" if os.name == "nt" else "d8"),
            ]:
                target = sdk / item
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            with (
                patch.dict(
                    os.environ,
                    {"ANDROID_SDK_ROOT": "/not-installed", "ANDROID_HOME": "/not-installed"},
                ),
                patch.object(speaker, "ROOT", project),
                patch.object(speaker.Path, "home", return_value=root),
                patch.object(speaker.shutil, "which", return_value="/usr/bin/javac"),
                patch.object(speaker.subprocess, "run") as run,
            ):
                dex = speaker.build()
                self.assertEqual(dex, project / "build/classes.dex")
                self.assertEqual(run.call_count, 2)
                self.assertIn(
                    str(sdk / "platforms/android-37/android.jar"), run.call_args_list[0].args[0]
                )
                self.assertEqual(
                    run.call_args_list[1].args[0][0],
                    str(sdk / "build-tools/36.0.0" / ("d8.bat" if os.name == "nt" else "d8")),
                )

    def test_source_digest_normalizes_crlf_and_orders_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src_dir = root / "native/android"
            src_dir.mkdir(parents=True)
            (src_dir / "AdbSpeaker.java").write_bytes(b"public class AdbSpeaker {\r\n}\r\n")
            with patch.object(speaker, "ROOT", root):
                digest_crlf = speaker.source_digest()
            (src_dir / "AdbSpeaker.java").write_bytes(b"public class AdbSpeaker {\n}\n")
            with patch.object(speaker, "ROOT", root):
                digest_lf = speaker.source_digest()
            self.assertEqual(digest_crlf, digest_lf)

    def test_check_action_verifies_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src_dir = root / "native/android"
            src_dir.mkdir(parents=True)
            (src_dir / "AdbSpeaker.java").write_text("// test")
            assets = root / "src/adb_speaker/assets"
            assets.mkdir(parents=True)
            (assets / "receiver.dex").write_bytes(b"dex")
            digest = hashlib.sha256(b"AdbSpeaker.java\0// test").hexdigest()
            (assets / "receiver.sha256").write_text(digest + "\n")
            with (
                patch.object(speaker, "ROOT", root),
                patch.object(sys, "argv", ["receiver.py", "check"]),
            ):
                speaker.main()

                # Mismatched digest should raise SystemExit
                (assets / "receiver.sha256").write_text("mismatched\n")
                with self.assertRaises(SystemExit):
                    speaker.main()

                # Missing dex should raise SystemExit
                (assets / "receiver.sha256").write_text(digest + "\n")
                (assets / "receiver.dex").unlink()
                with self.assertRaises(SystemExit):
                    speaker.main()
