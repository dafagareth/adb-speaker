"""
Project: adb-speaker
Module: test_cli.py
Description: Unit tests for CLI arguments, options, platform checks, and frozen path setup.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from adb_speaker import cli as speaker

HERE = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def test_help_and_empty_command_work_without_adb(self):
        for arguments in ([], ["--help"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(HERE / "speaker.py"), *arguments],
                    env={**os.environ, "PATH": ""},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                self.assertIn("stream: forward desktop audio", result.stdout)
                self.assertIn("Advanced options:", result.stdout)
                self.assertIn("python3 speaker.py stream", result.stdout)

    def test_cli_gain_defaults_and_overrides(self):
        for arguments, expected_gain in [
            (["stream"], 1.0),
            (["tone"], 0.25),
            (["stream", "--gain", "0.5"], 0.5),
            (["tone", "--gain", "1"], 1.0),
        ]:
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["speaker.py", *arguments]),
                patch.object(speaker.shutil, "which", return_value="/fake/tool"),
                patch.object(speaker, "choose_device", return_value=["adb", "-s", "test-phone"]),
                patch.object(speaker, "receive") as receive,
            ):
                speaker.main()
                receive.assert_called_once_with(
                    ["adb", "-s", "test-phone"],
                    arguments[0],
                    None,
                    expected_gain,
                    False,
                    "wasapi" if os.name == "nt" else "pulse",
                )

    def test_windows_cli_defaults_to_wasapi(self):
        with (
            patch.object(speaker, "IS_WINDOWS", True),
            patch.object(sys, "argv", ["adb-speaker", "stream"]),
            patch.object(speaker.shutil, "which", return_value="/fake/adb"),
            patch.object(speaker, "capture_command", return_value=["wasapi_capture.exe"]),
            patch.object(speaker, "choose_device", return_value=["adb", "-s", "phone"]),
            patch.object(speaker, "receive") as receive,
        ):
            speaker.main()
            receive.assert_called_once_with(
                ["adb", "-s", "phone"], "stream", None, 1.0, False, "wasapi"
            )

    def test_capture_is_rejected_for_tone(self):
        result = subprocess.run(
            [sys.executable, str(HERE / "speaker.py"), "tone", "--capture", "pulse"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--capture is available only for stream", result.stderr)

    def test_watch_is_rejected_for_tone(self):
        result = subprocess.run(
            [sys.executable, str(HERE / "speaker.py"), "tone", "--watch"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--watch is available only for stream", result.stderr)

    def test_watch_is_rejected_on_windows(self):
        with (
            patch.object(speaker, "IS_WINDOWS", True),
            patch.object(sys, "argv", ["adb-speaker", "stream", "--watch"]),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            with self.assertRaises(SystemExit):
                speaker.main()
            self.assertIn("--watch is not supported on Windows", stderr.getvalue())

    def test_invalid_numeric_arguments_fail_before_connecting(self):
        for option, value in [
            ("--gain", "nan"),
            ("--gain", "2"),
            ("--seconds", "0"),
            ("--seconds", "inf"),
        ]:
            with (
                self.subTest(option=option, value=value),
                patch.object(sys, "argv", ["speaker.py", "stream", option, value]),
                patch.object(speaker, "receive") as receive,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as error:
                    speaker.main()
                self.assertEqual(error.exception.code, 2)
                receive.assert_not_called()

    def test_windows_tone_uses_no_capture(self):
        with (
            patch.object(speaker, "IS_WINDOWS", True),
            patch.object(sys, "argv", ["adb-speaker", "tone"]),
            patch.object(speaker.shutil, "which", return_value="/fake/adb"),
            patch.object(speaker, "choose_device", return_value=["adb"]),
            patch.object(speaker, "capture_command") as capture,
            patch.object(speaker, "receive") as receive,
        ):
            speaker.main()
            capture.assert_not_called()
            self.assertEqual(receive.call_args.args[1], "tone")

    def test_wrong_platform_backend_rejected(self):
        for windows, backend in [(True, "pulse"), (False, "wasapi")]:
            with (
                self.subTest(backend=backend),
                patch.object(speaker, "IS_WINDOWS", windows),
                patch.object(sys, "argv", ["adb-speaker", "stream", "--capture", backend]),
                contextlib.redirect_stderr(io.StringIO()),
                patch.object(speaker, "receive") as receive,
            ):
                with self.assertRaises(SystemExit):
                    speaker.main()
                receive.assert_not_called()

    def test_frozen_helpers_precede_system_path(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", "/bundle", create=True),
            patch.dict(os.environ, {"PATH": "existing"}),
        ):
            speaker.prepare_path()
            self.assertEqual(os.environ["PATH"], str(Path("/bundle/bin")) + os.pathsep + "existing")
