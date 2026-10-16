"""
Project: adb-speaker
Module: test_relay.py
Description: Unit tests for stalled ADB writes and fragmented stereo PCM relay.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import contextlib
import io
import os
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from adb_speaker import session as speaker
from adb_speaker.protocol import PacketClock, PACKET_HEADER, PACKET_MAGIC


@unittest.skipIf(os.name == "nt", "Linux pipe relay")
class LinuxRelayTest(unittest.TestCase):
    def test_periodic_probes_drain_capture_and_resume_with_original_timestamps(self):
        now = [0]
        reads = []
        packets = []
        # Advance beyond the 10-second calibration interval, then fragment one reply.
        events = iter(
            [
                ([10], [], 11_000_000_000, b"a" * 960),
                ([], [11], 11_000_000_000, None),
                ([10], [], 11_001_000_000, b"b" * 960),
                ([12], [], 11_002_000_000, b"SY"),
                ([12], [], 11_002_000_000, b"NC 0 91001000000\n"),
                ([], [11], 11_002_000_000, None),
                ([12], [], 11_004_000_000, b"SYNC 1 91003000000\n"),
                ([], [11], 11_004_000_000, None),
                ([], [11], 11_004_000_000, None),
                ([10], [], 11_004_000_000, b""),
            ]
        )
        clock = PacketClock()

        def select(readers, writers, errors, timeout):
            if clock.probe is not None:
                self.assertEqual(writers, [], "Audio must wait for probe replies")
            ready, writable, stamp, data = next(events)
            self.assertTrue(set(writable).issubset(writers))
            now[0] = stamp
            if data is not None:
                reads.append((ready[0], data))
            return ready, writable, []

        def read(fd, size):
            expected, data = reads.pop(0)
            self.assertEqual(fd, expected)
            return data

        def write(fd, data):
            packets.append((PACKET_HEADER.unpack(data[:28]), data[28:]))
            return len(data)

        capture = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 10), poll=lambda: None)
        receiver = SimpleNamespace(
            stdin=SimpleNamespace(fileno=lambda: 11),
            stdout=SimpleNamespace(fileno=lambda: 12),
            poll=lambda: None,
        )
        with (
            patch("fcntl.fcntl"),
            patch.object(speaker.os, "set_blocking"),
            patch.object(speaker.time, "monotonic_ns", side_effect=lambda: now[0]),
            patch.object(speaker.select, "select", side_effect=select),
            patch.object(speaker.os, "read", side_effect=read),
            patch.object(speaker.os, "write", side_effect=write),
            patch.object(speaker, "device_connected", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "capture stopped"):
                speaker.stream_linux(["adb"], capture, receiver, None, False, clock)
        self.assertEqual([header[1] for header, _ in packets], [0, 0, 1, 1])
        self.assertEqual([header[2] for header, _ in packets], [0, 1, 2, 3])
        self.assertEqual(packets[2][0][3], 91_000_000_000)
        self.assertEqual(packets[3][0][3], 91_001_000_000)
        self.assertEqual(packets[2][1], b"a" * 960)
        self.assertEqual(packets[3][1], b"b" * 960)

    def run_relay(self, packets, events, write_error=None):
        source = Mock()
        source.fileno.return_value = 10
        destination = Mock()
        destination.fileno.return_value = 11
        capture = SimpleNamespace(stdout=source, poll=lambda: None)
        control = Mock()
        control.fileno.return_value = 12
        receiver = SimpleNamespace(stdin=destination, stdout=control, poll=lambda: None)
        output = bytearray()

        def write(fd, data):
            self.assertEqual(fd, 11)
            self.assertEqual(len(data) % 4, 0)
            self.assertLessEqual(len(data), 988)
            if write_error:
                raise write_error
            magic, kind, sequence, timestamp, size = PACKET_HEADER.unpack(data[:28])
            self.assertEqual(magic, PACKET_MAGIC)
            self.assertEqual(kind, 1)
            self.assertEqual(size, len(data) - 28)
            output.extend(data[28:])
            return len(data)

        messages = io.StringIO()
        with (
            patch("fcntl.fcntl", side_effect=OSError("resize unavailable")),
            patch.object(speaker.os, "set_blocking"),
            patch.object(speaker.os, "read", side_effect=packets),
            patch.object(speaker.os, "write", side_effect=write),
            patch.object(speaker.select, "select", side_effect=events),
            patch.object(speaker, "device_connected", return_value=True),
            contextlib.redirect_stderr(messages),
        ):
            with self.assertRaisesRegex(RuntimeError, "stopped unexpectedly"):
                speaker.stream_linux(["adb"], capture, receiver, None, True, PacketClock())
        return bytes(output), messages.getvalue()

    def test_stalled_adb_discards_old_frames_and_resumes_with_recent_audio(self):
        pcm = b"".join(struct.pack("<I", i) for i in range(5000))
        output, log = self.run_relay(
            [pcm[:10001], pcm[10001:], b""],
            [([10], [], []), ([10], [], [])] + [([], [11], [])] * 10 + [([10], [], [])],
        )
        self.assertEqual(output, pcm[-9600:])
        self.assertIn("discarded 54.2 ms", log)

    def test_fragmented_capture_preserves_stereo_frames(self):
        pcm = bytes(range(8))
        output, log = self.run_relay(
            [pcm[:1], pcm[1:3], pcm[3:7], pcm[7:], b""],
            [([10], [], [])] * 3 + [([], [11], []), ([10], [], []), ([], [11], []), ([10], [], [])],
        )
        self.assertEqual(output, pcm)
        self.assertIn("discarded 0.0 ms", log)

    def test_closed_adb_pipe_reports_receiver_failure(self):
        output, _ = self.run_relay(
            [b"\0" * 960], [([10], [], []), ([], [11], [])], BrokenPipeError()
        )
        self.assertEqual(output, b"")


if __name__ == "__main__":
    unittest.main()
