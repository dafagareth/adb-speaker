"""
Project: adb-speaker
Module: protocol.py
Description: Audio packet framing, RTT clock synchronization, and frame timing.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

from collections import deque
import os
import select
import struct
import sys
import time

RATE = 48000
PACKET_HEADER = struct.Struct(">IIqqI")
PACKET_MAGIC = 0x41444231  # ADB1, big-endian header followed by little-endian PCM.


class PacketClock:
    """Map host monotonic timestamps to the receiver using bounded-RTT samples."""

    def __init__(self):
        self.sequence = 0
        self.probe = None
        self.samples = deque(maxlen=5)

    def packet(self, kind, timestamp, payload=b""):
        return (
            PACKET_HEADER.pack(PACKET_MAGIC, kind, self.sequence, timestamp, len(payload)) + payload
        )

    def accept(self, line, now):
        try:
            tag, sequence, remote = line.split()
            sequence, remote = int(sequence), int(remote)
            if (
                tag != b"SYNC"
                or self.probe is None
                or sequence != self.probe[0]
                or not -(1 << 63) <= remote < (1 << 63)
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError("Invalid receiver clock response.") from None
        sent = self.probe[1]
        self.probe = None
        rtt = now - sent
        if 0 <= rtt <= 50_000_000:
            self.samples.append((now, rtt, remote - (sent + now) // 2))

    def timestamp(self, observed, now):
        samples = [sample for sample in self.samples if 0 <= now - sample[0] < 60_000_000_000]
        if not samples:
            return 0  # No recent reliable clock mapping: receiver must not discard by age.
        return observed + min(samples, key=lambda sample: sample[1])[2]


def synchronize_clock(receiver):
    clock = PacketClock()
    fd = receiver.stdout.fileno()
    buf = bytearray()
    for _ in range(5):
        sent = time.monotonic_ns()
        clock.probe = (clock.sequence, sent)
        receiver.stdin.write(clock.packet(0, sent))
        receiver.stdin.flush()
        clock.sequence += 1
        deadline = time.monotonic() + 3.0
        while b"\n" not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("The phone clock handshake timed out.") from None
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                raise RuntimeError("The phone clock handshake timed out.") from None
            chunk = os.read(fd, 256)
            if not chunk:
                raise RuntimeError("The phone clock handshake timed out.") from None
            buf.extend(chunk)
            if len(buf) > 256:
                raise RuntimeError("Receiver clock response is too long.")
        line, _, rest = buf.partition(b"\n")
        buf = bytearray(rest)
        clock.accept(bytes(line), time.monotonic_ns())
    if not clock.samples:
        print(
            "Clock timing is uncertain; stale-packet checks await a reliable sample.",
            file=sys.stderr,
        )
    return clock


def consume_pcm(pending, timestamps, size):
    del pending[:size]
    while size:
        length, stamp = timestamps.popleft()
        if length > size:
            timestamps.appendleft((length - size, stamp))
            break
        size -= length
