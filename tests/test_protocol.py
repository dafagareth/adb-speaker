"""
Project: adb-speaker
Module: test_protocol.py
Description: Clock offset estimation and PCM timestamp preservation, without a phone.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

from collections import deque
import os
import unittest

from adb_speaker import protocol as speaker
from adb_speaker.protocol import PacketClock


class PacketClockTest(unittest.TestCase):
    def sample(self, clock, sent, received, remote):
        clock.probe = (clock.sequence, sent)
        clock.accept(f"SYNC {clock.sequence} {remote}\n".encode(), received)
        clock.sequence += 1

    def test_clock_origin_difference_is_removed(self):
        clock = PacketClock()
        self.sample(clock, 1_000_000_000, 1_004_000_000, 91_002_000_000)
        self.assertEqual(clock.timestamp(1_100_000_000, 1_110_000_000), 91_100_000_000)

    def test_lowest_rtt_sample_wins_and_old_samples_expire(self):
        clock = PacketClock()
        self.sample(clock, 1_000_000_000, 1_004_000_000, 91_002_000_000)
        self.sample(clock, 2_000_000_000, 2_040_000_000, 92_030_000_000)
        self.assertEqual(clock.timestamp(2_100_000_000, 2_100_000_000), 92_100_000_000)
        self.assertEqual(clock.timestamp(70_000_000_000, 70_000_000_000), 0)
        self.sample(clock, 70_000_000_000, 70_004_000_000, 160_003_000_000)
        self.assertEqual(clock.timestamp(70_100_000_000, 70_100_000_000), 160_101_000_000)

    def test_slow_probe_does_not_enable_discarding(self):
        clock = PacketClock()
        self.sample(clock, 1_000_000_000, 1_500_000_000, 91_250_000_000)
        self.assertEqual(clock.timestamp(2_000_000_000, 2_000_000_000), 0)

    def test_bad_responses_are_rejected(self):
        for line in (b"", b"SYNC 9 123", b"SYNC a 1", b"BOGUS 0 123"):
            clock = PacketClock()
            clock.probe = (0, 100)
            with self.subTest(line=line), self.assertRaisesRegex(RuntimeError, "clock response"):
                clock.accept(line, 200)

    def test_discarding_keeps_the_original_read_time_of_surviving_pcm(self):
        pcm = bytearray(range(16))
        times = deque([(3, 100), (5, 200), (8, 300)])
        speaker.consume_pcm(pcm, times, 4)
        self.assertEqual(pcm, bytes(range(4, 16)))
        self.assertEqual(list(times), [(4, 200), (8, 300)])
        speaker.consume_pcm(pcm, times, 8)
        self.assertEqual(list(times), [(4, 300)])
        speaker.consume_pcm(pcm, times, 4)
        self.assertEqual(len(times), 0)

    @unittest.skipIf(os.name == "nt", "POSIX pipe select fixture")
    def test_synchronize_clock_handles_fragmented_responses(self):
        import io

        read_fd, write_fd = os.pipe()
        stdin = io.BytesIO()
        try:

            class MockReceiver:
                def __init__(self, in_stream, out_fd):
                    self.stdin = in_stream
                    self.stdout = os.fdopen(out_fd, "rb")

            receiver = MockReceiver(stdin, read_fd)
            # Write 5 fragmented responses to the pipe
            for seq in range(5):
                os.write(write_fd, b"SY")
                os.write(write_fd, f"NC {seq} {1000 + seq}\n".encode())
            clock = speaker.synchronize_clock(receiver)
            self.assertEqual(len(clock.samples), 5)
        finally:
            receiver.stdout.close()
            os.close(write_fd)

    @unittest.skipIf(os.name == "nt", "POSIX pipe select fixture")
    def test_synchronize_clock_rejects_oversized_response(self):
        import io

        read_fd, write_fd = os.pipe()
        stdin = io.BytesIO()
        receiver = None
        try:

            class MockReceiver:
                def __init__(self, in_stream, out_fd):
                    self.stdin = in_stream
                    self.stdout = os.fdopen(out_fd, "rb")

            receiver = MockReceiver(stdin, read_fd)
            os.write(write_fd, b"A" * 300)
            with self.assertRaisesRegex(RuntimeError, "too long"):
                speaker.synchronize_clock(receiver)
        finally:
            if receiver and receiver.stdout:
                receiver.stdout.close()
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main()
