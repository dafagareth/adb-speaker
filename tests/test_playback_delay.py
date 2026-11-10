"""Compile PlaybackDelay and its Java test into a temporary directory.
Run the test with java and fail if compilation or execution fails. Skip when the
JDK is missing, and remove the temporary files when finished.
"""

# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "requires a JDK")
class PlaybackDelayTest(unittest.TestCase):
    def test_timestamp_validation_and_frame_wrap(self):
        with tempfile.TemporaryDirectory() as output:
            subprocess.run(
                [
                    "javac",
                    "--release",
                    "11",
                    "-d",
                    output,
                    str(ROOT / "native/android/PlaybackDelay.java"),
                    str(ROOT / "tests/native/TestPlaybackDelay.java"),
                ],
                check=True,
                timeout=30,
            )
            subprocess.run(["java", "-cp", output, "TestPlaybackDelay"], check=True, timeout=15)
