"""
Project: adb-speaker
Module: test_session.py
Description: Unit tests for device selection, session locking, capture commands, and lifecycle.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import contextlib
import io
import json
import struct
from types import SimpleNamespace
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from adb_speaker.protocol import PacketClock

from adb_speaker import session as speaker

HERE = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX subprocess fixture")
    def test_disconnect_stops_capture_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adb = root / "adb"
            adb.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ['SPEAKER_TEST_ROOT'])
if 'app_process' in sys.argv:
    print('READY', flush=True)
    sys.stdin.buffer.read(4)
    (root / 'offline').touch()
    sys.exit(1)
elif 'get-state' in sys.argv:
    sys.exit(1)
elif 'shell' in sys.argv:
    (root / 'unexpected-cleanup').touch()
""")
            adb.chmod(0o755)
            capture = root / "parec"
            capture.write_text("""#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
Path(os.environ['SPEAKER_TEST_ROOT'], 'capture-pid').write_text(str(os.getpid()))
sys.stdout.buffer.write(b'\\0' * 4)
sys.stdout.buffer.flush()
time.sleep(30)
""")
            capture.chmod(0o755)
            errors = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"PATH": str(root) + ":" + os.environ["PATH"], "SPEAKER_TEST_ROOT": str(root)},
                ),
                patch.object(speaker, "synchronize_clock", return_value=PacketClock()),
                patch.object(speaker, "receiver_path", return_value=root / "classes.dex"),
                patch.object(speaker, "cache_dir", return_value=root / ".cache/adb-speaker"),
                contextlib.redirect_stderr(errors),
            ):
                with self.assertRaisesRegex(RuntimeError, "Phone disconnected"):
                    speaker.receive([str(adb)], "stream", 2)
            self.assertTrue((root / "offline").exists())
            self.assertFalse((root / "unexpected-cleanup").exists())
            self.assertIn("After reconnecting", errors.getvalue())
            with self.assertRaises(ProcessLookupError):
                os.kill(int((root / "capture-pid").read_text()), 0)
            with speaker.session_lock(root / ".cache/adb-speaker/session.lock"):
                pass

    def test_receiver_readiness_timeout(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"], stdout=subprocess.PIPE
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                speaker.wait_ready(process, timeout=0.05)
        finally:
            speaker.stop(process)
            if process.stdout is not None:
                process.stdout.close()

    def test_readiness_handles_partial_eof_and_invalid_messages(self):
        for message in (b"READY\n", b"REA", b"", b"ERROR\n"):
            with self.subTest(message=message):
                read_fd, write_fd = os.pipe()
                with os.fdopen(read_fd, "rb") as reader:
                    os.write(write_fd, message)
                    os.close(write_fd)
                    receiver = SimpleNamespace(stdout=reader)
                    if message == b"READY\n":
                        speaker.wait_ready(receiver, timeout=1)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                            speaker.wait_ready(receiver, timeout=1)

    @unittest.skipIf(os.name == "nt", "POSIX subprocess fixture")
    def test_partial_readiness_does_not_block_waiting_for_newline(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"REA")
            # Bound the whole test even if readline() regresses and hangs.
            code = (
                "import os, sys; from types import SimpleNamespace; from adb_speaker import session as speaker; "
                "speaker.wait_ready(SimpleNamespace(stdout=os.fdopen(int(sys.argv[1]), 'rb')), .05)"
            )
            result = subprocess.run(
                [sys.executable, "-c", code, str(read_fd)],
                pass_fds=(read_fd,),
                cwd=HERE,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("did not become ready", result.stderr)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_device_selection(self):
        for rows, expected in [
            ("", None),
            ("one unauthorized\n", None),
            ("one device\ntwo device\n", None),
            ("one device\ntwo offline\n", "one"),
        ]:
            with (
                self.subTest(rows=rows),
                patch.object(
                    speaker.subprocess,
                    "check_output",
                    return_value="List of devices attached\n" + rows,
                ),
            ):
                if expected:
                    self.assertEqual(speaker.choose_device(None), ["adb", "-s", expected])
                else:
                    with self.assertRaisesRegex(RuntimeError, "exactly one authorized"):
                        speaker.choose_device(None)
        with patch.object(speaker.subprocess, "run") as run:
            self.assertEqual(speaker.choose_device("chosen"), ["adb", "-s", "chosen"])
            run.assert_called_once_with(
                ["adb", "-s", "chosen", "get-state"], check=True, stdout=subprocess.DEVNULL
            )
        with patch.object(
            speaker.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "adb")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                speaker.choose_device("offline")

    def test_held_session_lock_rejects_before_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock_dir = root / ".cache/adb-speaker"
            lock_dir.mkdir(parents=True)
            with (
                patch.object(speaker, "cache_dir", return_value=root / ".cache/adb-speaker"),
                patch.object(speaker, "receiver_path") as build,
            ):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with speaker.session_lock(lock_dir / "session.lock"):
                        speaker.receive(["adb"], "tone", None)
                build.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Linux streaming lifecycle")
    def test_playback_failures_stop_processes_and_clean_up(self):
        for mode in ("tone", "stream"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                receiver = Mock()
                receiver.poll.return_value = None
                capture = Mock()
                capture.poll.return_value = 1
                receiver.communicate.side_effect = subprocess.TimeoutExpired("receiver", 15)
                result = SimpleNamespace(returncode=0, stdout="")
                with (
                    patch.object(speaker, "cache_dir", return_value=root / ".cache/adb-speaker"),
                    patch.object(speaker, "synchronize_clock", return_value=PacketClock()),
                    patch.object(speaker, "receiver_path", return_value=root / "receiver.dex"),
                    patch.object(speaker, "wait_ready"),
                    patch.object(speaker, "device_connected", return_value=True),
                    patch.object(speaker.subprocess, "run", return_value=result) as run,
                    patch.object(speaker.subprocess, "Popen", side_effect=[receiver, capture]),
                    patch.object(speaker, "stop") as stop,
                ):
                    message = (
                        "did not finish the tone"
                        if mode == "tone"
                        else "capture stopped unexpectedly"
                    )
                    with self.assertRaisesRegex(RuntimeError, message):
                        speaker.receive(["adb"], mode, None)
                    if mode == "tone":
                        self.assertEqual(receiver.communicate.call_args.kwargs["timeout"], 15)
                    else:
                        stop.assert_any_call(capture)
                    receiver.wait.assert_called_once_with(timeout=4)
                    self.assertEqual(
                        run.call_args.args[0], ["adb", "shell", "unlink", speaker.REMOTE]
                    )

    def test_tone_has_complete_stereo_frames_and_bounded_amplitude(self):
        pcm = speaker.tone()
        self.assertEqual(len(pcm), int(speaker.RATE * 4.5) * 4)
        frames = list(struct.iter_unpack("<hh", pcm))
        self.assertTrue(all(left == right for left, right in frames))
        peak = max(abs(left) for left, _ in frames)
        self.assertGreater(peak, 0)
        self.assertLessEqual(peak, 20000)

    @unittest.skipIf(os.name == "nt", "POSIX subprocess fixture")
    def test_transfer_and_rejection_before_and_after_ready_clean_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = root / "calls.jsonl"
            adb = root / "adb"
            adb.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ['SPEAKER_TEST_CALLS'], 'a') as log:
    log.write(json.dumps(sys.argv[1:])+'\\n')
if 'app_process' in sys.argv:
    if os.environ.get('SPEAKER_TEST_REJECT') == '1': sys.exit(3)
    print('READY', flush=True)
    payload = sys.stdin.buffer.read()
    assert len(payload) % 4 == 0 and len(payload) > 0
    if os.environ.get('SPEAKER_TEST_REJECT') == 'after-ready': sys.exit(3)
elif 'get-state' in sys.argv: print('device')
elif 'pidof' in sys.argv: print('12345 invalid 67890')
""")
            adb.chmod(0o755)
            with (
                patch.dict(os.environ, {"SPEAKER_TEST_CALLS": str(calls)}),
                patch.object(speaker, "synchronize_clock", return_value=PacketClock()),
                patch.object(speaker, "receiver_path", return_value=root / "classes.dex"),
                patch.object(speaker, "cache_dir", return_value=root / ".cache/adb-speaker"),
            ):
                speaker.receive([str(adb)], "tone", None)
                entries = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual(entries[-1], ["shell", "unlink", speaker.REMOTE])
                self.assertFalse(any("install" in entry for entry in entries))
                label = next(
                    arg.split("=", 1)[1]
                    for entry in entries
                    for arg in entry
                    if arg.startswith("--nice-name=")
                )
                self.assertIn(["shell", "pidof", label], entries)
                self.assertEqual(
                    [entry for entry in entries if "kill" in entry],
                    [["shell", "kill", "12345"], ["shell", "kill", "67890"]],
                )
                for rejection, message in [
                    ("1", "did not become ready"),
                    ("after-ready", "rejected audio playback"),
                ]:
                    with patch.dict(os.environ, {"SPEAKER_TEST_REJECT": rejection}):
                        with self.assertRaisesRegex(RuntimeError, message):
                            speaker.receive([str(adb)], "tone", None)
                entries = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual(entries[-1], ["shell", "unlink", speaker.REMOTE])

    @unittest.skipIf(os.name == "nt", "POSIX subprocess fixture")
    def test_desktop_capture_uses_playback_monitor_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = root / "calls.jsonl"
            adb = root / "adb"
            adb.write_text("""#!/usr/bin/env python3
import os, sys, time
if 'app_process' in sys.argv:
    time.sleep(.15)
    assert sys.argv[sys.argv.index('AdbSpeaker') + 2] == os.environ['SPEAKER_TEST_DISPLAY']
    assert not os.path.exists(os.environ['SPEAKER_TEST_CALLS'])
    print('READY', flush=True)
    assert len(sys.stdin.buffer.read()) > 0
elif 'get-state' in sys.argv: print('device')
elif 'pidof' in sys.argv: sys.exit(1)
""")
            adb.chmod(0o755)
            capture = root / "parec"
            capture.write_text("""#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ['SPEAKER_TEST_CALLS'], 'w') as log: json.dump(sys.argv[1:], log)
while True:
    sys.stdout.buffer.write(b'\\0' * 3840)
    sys.stdout.buffer.flush()
    time.sleep(.01)
""")
            capture.chmod(0o755)
            with (
                patch.dict(
                    os.environ,
                    {
                        "PATH": str(root) + ":" + os.environ["PATH"],
                        "SPEAKER_TEST_CALLS": str(calls),
                    },
                ),
                patch.object(speaker, "synchronize_clock", return_value=PacketClock()),
                patch.object(speaker, "receiver_path", return_value=root / "classes.dex"),
                patch.object(speaker, "cache_dir", return_value=root / ".cache/adb-speaker"),
            ):
                for watch, tty, display in [
                    (False, False, "quiet"),
                    (True, False, "log"),
                    (True, True, "terminal"),
                ]:
                    with (
                        self.subTest(display=display),
                        patch.dict(os.environ, {"SPEAKER_TEST_DISPLAY": display}),
                        patch.object(speaker.sys.stderr, "isatty", return_value=tty),
                    ):
                        calls.unlink(missing_ok=True)
                        speaker.receive(
                            [str(adb)],
                            "stream",
                            0.5,
                            watch=watch,
                            capture_backend="pulse",
                        )
                        args = json.loads(calls.read_text())
                        self.assertIn("--device=@DEFAULT_MONITOR@", args)

    def test_windows_lock_and_transport(self):
        fake = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=Mock())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receiver = Mock(stdin=io.BytesIO(), stdout=None, returncode=0)
            receiver.poll.return_value = None
            with (
                patch.object(speaker, "IS_WINDOWS", True),
                patch.dict(sys.modules, {"msvcrt": fake}),
                patch.object(speaker, "cache_dir", return_value=root),
                patch.object(speaker, "receiver_path", return_value=root / "receiver.dex"),
                patch.object(speaker, "device_connected", return_value=True),
                patch.object(
                    speaker.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="READY"),
                ) as run,
                patch.object(speaker.subprocess, "Popen", return_value=receiver) as popen,
            ):
                speaker.receive(["adb"], "tone", None)
            self.assertIn("exec-in", popen.call_args.args[0])
            self.assertTrue(popen.call_args.args[0][-2].endswith(".ready"))
            self.assertEqual(popen.call_args.args[0][-1], "60")
            self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual([c.args[1] for c in fake.locking.call_args_list], [1, 2])
            self.assertIn("exec-out", run.call_args_list[1].args[0])

    def test_windows_readiness_reports_failure(self):
        receiver = Mock()
        receiver.poll.return_value = None
        with patch.object(
            speaker.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="ERROR AudioTrack failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "AudioTrack failed"):
                speaker.wait_ready_windows(["adb"], receiver, "/ready", timeout=0.2)

    def test_pulse_command(self):
        command = speaker.capture_command("pulse")
        self.assertEqual(command[0], "parec")
        self.assertIn("--rate=48000", command)
        self.assertIn("--channels=2", command)
        self.assertIn("--format=s16le", command)

    def test_unknown_backend_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "Unknown capture backend"):
            speaker.capture_command("invalid")

    def test_wasapi_native_helper_and_missing_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helper = root / "build/windows/Release/wasapi_capture.exe"
            helper.parent.mkdir(parents=True)
            helper.touch()
            with patch.object(speaker, "ROOT", root):
                self.assertEqual(speaker.capture_command("wasapi"), [str(helper)])
            helper.unlink()
            with (
                patch.object(speaker, "ROOT", root),
                patch.object(speaker.shutil, "which", return_value=None),
            ):
                with self.assertRaisesRegex(RuntimeError, "Windows capture is missing"):
                    speaker.capture_command("wasapi")

    def test_missing_and_present_receiver(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(speaker, "ASSETS", Path(temp)):
            with self.assertRaisesRegex(RuntimeError, "receiver is missing"):
                speaker.receiver_path()
            dex = Path(temp) / "receiver.dex"
            dex.write_bytes(b"dex\n")
            self.assertEqual(speaker.receiver_path(), dex)
