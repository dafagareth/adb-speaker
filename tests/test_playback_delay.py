"""
Project: adb-speaker
Module: test_playback_delay.py
Description: Host unit test runner for receiver presentation delay estimation without Android SDK stubs.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

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
