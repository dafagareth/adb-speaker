"""
Project: adb-speaker
Module: test_receiver.py
Description: Hardware device integration tests: ADB_SPEAKER_TEST_SERIAL=SERIAL python -m unittest test_receiver.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import os
import struct
import subprocess
import time
import unittest
import uuid

from adb_speaker import session as speaker


@unittest.skipUnless(
    os.environ.get("ADB_SPEAKER_TEST_SERIAL"), "requires an explicitly selected Android device"
)
class ReceiverDeviceTest(unittest.TestCase):
    def test_timestamped_packets_and_malformed_input(self):
        adb = ["adb", "-s", os.environ["ADB_SPEAKER_TEST_SERIAL"]]
        remote = "/data/local/tmp/adb-speaker-packets-test-" + uuid.uuid4().hex + ".dex"
        subprocess.run(
            [*adb, "push", str(speaker.receiver_path()), remote],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        cases = [
            ("fresh", "PLAYED bytes=960 frames=240", 0),
            ("stale", "discarded_bytes=960", 0),
            ("uncalibrated", "PLAYED bytes=960 frames=240", 0),
            ("recover", "PLAYED bytes=960 frames=240", 0),
            ("bad-magic", "Invalid audio packet magic", 1),
            ("bad-length", "Invalid audio packet header", 1),
            ("bad-sequence", "Audio packet sequence mismatch", 1),
            ("short-header", "Truncated audio packet", 1),
            ("short-payload", "Truncated audio packet", 1),
        ]
        try:
            for case, expected, status in cases:
                with self.subTest(case=case):
                    process = subprocess.Popen(
                        [
                            *adb,
                            "shell",
                            "-T",
                            "CLASSPATH=" + remote,
                            "app_process",
                            "/",
                            "AdbSpeaker",
                            "0",
                            "quiet",
                            "-",
                            "30",
                            "packet-v1",
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        speaker.wait_ready(process)
                        clock = speaker.synchronize_clock(process)
                        self.assertTrue(clock.samples, "No usable device clock sample")
                        now = time.monotonic_ns()
                        stamp = clock.timestamp(now, now)
                        if case in ("stale", "recover"):
                            stamp -= 500_000_000
                        elif case == "uncalibrated":
                            stamp = 0
                        if case == "bad-sequence":
                            clock.sequence += 1
                        packet = clock.packet(1, stamp, b"\0" * 960)
                        if case == "recover":
                            clock.sequence += 1
                            packet += clock.packet(1, clock.timestamp(now, now), b"\0" * 960)
                        elif case == "bad-magic":
                            packet = b"FAIL" + packet[4:]
                        elif case == "bad-length":
                            packet = packet[:24] + struct.pack(">I", 1024) + packet[28:]
                        elif case == "short-header":
                            packet = packet[:17]
                        elif case == "short-payload":
                            packet = packet[:-1]
                        # Write boundaries can split both the header and stereo frames.
                        process.stdin.write(packet[:1])
                        process.stdin.flush()
                        process.stdin.write(packet[1:31])
                        process.stdin.flush()
                        _, errors = process.communicate(packet[31:], timeout=5)
                        message = errors.decode()
                        self.assertEqual(process.returncode, status, message)
                        self.assertIn(expected, message)
                        if case in ("fresh", "uncalibrated"):
                            self.assertIn("discarded_bytes=0", message)
                        elif case == "recover":
                            self.assertIn("discarded_bytes=960", message)
                    finally:
                        speaker.stop(process)
                        for pipe in (process.stdin, process.stdout, process.stderr):
                            pipe.close()
        finally:
            subprocess.run([*adb, "shell", "rm", "-f", remote], check=True, timeout=5)

    def test_delayed_fragmented_and_empty_input(self):
        adb = ["adb", "-s", os.environ["ADB_SPEAKER_TEST_SERIAL"]]
        remote = "/data/local/tmp/adb-speaker-test-" + uuid.uuid4().hex + ".dex"
        subprocess.run(
            [*adb, "push", str(speaker.receiver_path()), remote],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        try:
            for payload, expected in [
                (b"", "PLAYED bytes=0 frames=0"),
                (b"\0" * 960, "PLAYED bytes=960 frames=240"),
                (b"\0", "Truncated PCM frame"),
            ]:
                with self.subTest(size=len(payload)):
                    process = subprocess.Popen(
                        [
                            *adb,
                            "shell",
                            "-T",
                            "CLASSPATH=" + remote,
                            "app_process",
                            "/",
                            "AdbSpeaker",
                            "0",
                            "quiet",
                            "-",
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        speaker.wait_ready(process)
                        # Exercise an idle host and a read that ends inside a stereo frame.
                        time.sleep(0.2)
                        if payload:
                            process.stdin.write(payload[:1])
                            process.stdin.flush()
                            time.sleep(0.1)
                        _, errors = process.communicate(payload[1:], timeout=5)
                        self.assertIn(expected, errors.decode())
                        self.assertEqual(process.returncode, 1 if len(payload) == 1 else 0)
                    finally:
                        speaker.stop(process)
                        for pipe in (process.stdin, process.stdout, process.stderr):
                            pipe.close()
        finally:
            subprocess.run([*adb, "shell", "rm", "-f", remote], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
