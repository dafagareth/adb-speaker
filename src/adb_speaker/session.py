"""
Project: adb-speaker
Module: session.py
Description: Device selection, session locking, audio capture, process lifecycle, and Linux relay.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

from collections import deque
from contextlib import contextmanager
import math
import os
from pathlib import Path
import queue
import select
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import time
from .protocol import RATE, synchronize_clock, consume_pcm

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
ASSETS = PACKAGE / "assets"
IS_WINDOWS = os.name == "nt"
REMOTE = "/data/local/tmp/adb-speaker.dex"


def receiver_path():
    dex = ASSETS / "receiver.dex"
    if not dex.is_file():
        raise RuntimeError(
            "Android receiver is missing. Reinstall adb-speaker or run make bundle-receiver."
        )
    return dex


def capture_command(backend):
    if backend == "pulse":
        return [
            "parec",
            "--device=@DEFAULT_MONITOR@",
            "--raw",
            "--format=s16le",
            "--rate=48000",
            "--channels=2",
            "--latency-msec=5",
            "--process-time-msec=5",
            "--client-name=ADB Speaker",
            "--stream-name=Laptop playback",
        ]
    if backend == "wasapi":
        executable = ROOT / "build/windows/Release/wasapi_capture.exe"
        command = str(executable) if executable.is_file() else shutil.which("wasapi_capture.exe")
        if not command:
            raise RuntimeError(
                "Windows capture is missing. Build native/windows/wasapi_capture.cpp first."
            )
        return [command]
    raise ValueError("Unknown capture backend: " + backend)


def cache_dir():
    return Path.home() / ".cache/adb-speaker"


def choose_device(serial):
    if serial:
        subprocess.run(["adb", "-s", serial, "get-state"], check=True, stdout=subprocess.DEVNULL)
        return ["adb", "-s", serial]
    rows = subprocess.check_output(["adb", "devices"], text=True).splitlines()[1:]
    devices = [
        row.split()[0] for row in rows if len(row.split()) >= 2 and row.split()[1] == "device"
    ]
    if len(devices) != 1:
        raise RuntimeError("Connect exactly one authorized device, or select it with --serial.")
    return ["adb", "-s", devices[0]]


def tone():
    pcm = bytearray()
    for frequency in (440, 660, 880):
        for i in range(RATE):
            fade = min(1, i / 960, (RATE - 1 - i) / 960)
            sample = int(20000 * fade * math.sin(2 * math.pi * frequency * i / RATE))
            pcm.extend(struct.pack("<hh", sample, sample))
        pcm.extend(b"\0" * (RATE // 2 * 4))
    return bytes(pcm)


def stop(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def wait_ready(receiver, timeout=10):
    # Do not capture during Android startup: that backlog adds persistent delay.
    result = queue.Queue(maxsize=1)
    threading.Thread(target=lambda: result.put(receiver.stdout.readline()), daemon=True).start()
    try:
        line = result.get(timeout=timeout)
        if line and line.strip() == b"READY":
            return
    except queue.Empty:
        pass
    raise RuntimeError("The phone receiver did not become ready; see its error above.")


def wait_ready_windows(adb, receiver, ready_path, timeout=10):
    # `adb exec-in` forwards host stdin only, so Windows polls a receiver-written marker.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if receiver.poll() is not None:
            raise RuntimeError("The phone receiver exited before becoming ready.")
        try:
            result = subprocess.run(
                [*adb, "exec-out", "cat", ready_path], capture_output=True, text=True, timeout=2
            )
            status = result.stdout.strip()
            if status == "READY":
                return
            if status.startswith("ERROR "):
                raise RuntimeError("The phone receiver failed to start: " + status[6:])
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.1)
    raise RuntimeError("The phone receiver did not become ready before timeout.")


@contextmanager
def session_lock(path):
    """Lock a byte on Windows and the file on POSIX; always release on exit."""
    with path.open("a+b") as lock:
        if IS_WINDOWS:
            import msvcrt

            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("Another ADB speaker session is already running.") from None
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another ADB speaker session is already running.") from None
            yield


def device_connected(adb):
    try:
        result = subprocess.run([*adb, "get-state"], capture_output=True, text=True, timeout=3)
        return result.returncode == 0 and result.stdout.strip() == "device"
    except (OSError, subprocess.SubprocessError):
        return False


def playback_error(adb, message):
    if not device_connected(adb):
        return RuntimeError(
            "Phone disconnected or unavailable. Reconnect USB, then run adb-speaker again."
        )
    return RuntimeError(message)


def stream_linux(adb, capture, receiver, seconds, watch, clock):
    """Keep reading live capture when ADB stalls, retaining at most 50 ms of PCM."""
    import fcntl

    if capture.poll() is not None:
        raise playback_error(adb, "Desktop audio capture stopped unexpectedly.")
    source = capture.stdout.fileno()
    destination = receiver.stdin.fileno()
    control = receiver.stdout.fileno()
    os.set_blocking(source, False)
    os.set_blocking(destination, False)
    os.set_blocking(control, False)
    try:
        fcntl.fcntl(destination, fcntl.F_SETPIPE_SZ, 4096)
    except OSError:
        pass  # The bounded user-space queue still works if the kernel refuses resizing.
    pending = bytearray()
    timestamps = deque()
    responses = bytearray()
    next_sync = time.monotonic_ns() + 10_000_000_000
    sync_rounds = 0
    limit = RATE * 4 * 50 // 1000
    dropped = 0
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while True:
            if receiver.poll() is not None:
                raise playback_error(adb, "The phone receiver stopped unexpectedly.")
            if capture.poll() is not None:
                raise playback_error(adb, "Desktop audio capture stopped unexpectedly.")
            remaining = deadline - time.monotonic() if deadline else 0.1
            if remaining <= 0:
                break
            now = time.monotonic_ns()
            if clock.probe and now - clock.probe[1] > 5_000_000_000:
                raise RuntimeError("The phone clock response stalled during playback.")
            if now >= next_sync and sync_rounds == 0:
                sync_rounds = 2
            # Drain capture while probes are outstanding. The second probe then measures
            # the clocks without waiting behind previously queued audio playback.
            sync_due = sync_rounds > 0 and clock.probe is None
            can_write = sync_due or (sync_rounds == 0 and len(pending) >= 4)
            readable, writable, _ = select.select(
                [source, control], [destination] if can_write else [], [], min(0.1, remaining)
            )
            if control in readable:
                reply = os.read(control, 256)
                if not reply:
                    raise playback_error(adb, "The phone receiver stopped unexpectedly.")
                responses.extend(reply)
                if len(responses) > 256:
                    raise RuntimeError("Receiver clock response is too long.")
                if b"\n" in responses:
                    line, _, rest = responses.partition(b"\n")
                    clock.accept(bytes(line), time.monotonic_ns())
                    responses = bytearray(rest)
                    sync_rounds -= 1
                    if sync_rounds == 0:
                        next_sync = time.monotonic_ns() + 10_000_000_000
            if source in readable:
                data = os.read(source, 65536)
                if not data:
                    raise playback_error(adb, "Desktop audio capture stopped unexpectedly.")
                pending.extend(data)
                timestamps.append((len(data), time.monotonic_ns()))
                if len(pending) > limit:
                    # Discard complete stereo frames; keep any trailing partial frame.
                    excess = ((len(pending) - limit + 3) // 4) * 4
                    consume_pcm(pending, timestamps, excess)
                    dropped += excess
            if writable and (len(pending) >= 4 or sync_due):
                # <= PIPE_BUF: a nonblocking pipe write is atomic, preserving frame alignment.
                size = min(960, len(pending) // 4 * 4)
                sent = time.monotonic_ns()
                if sync_due:
                    packet = clock.packet(0, sent)
                else:
                    packet = clock.packet(
                        1, clock.timestamp(timestamps[0][1], sent), pending[:size]
                    )
                try:
                    written = os.write(destination, packet)
                except BlockingIOError:
                    continue
                if written != len(packet):
                    raise RuntimeError("Incomplete atomic audio packet write.")
                if sync_due:
                    clock.probe = (clock.sequence, sent)
                else:
                    consume_pcm(pending, timestamps, size)
                clock.sequence += 1
    except BrokenPipeError:
        raise playback_error(adb, "The phone receiver stopped unexpectedly.") from None
    finally:
        if watch:
            print(
                "\nHOST | discarded %.1f ms of queued PCM (not end-to-end latency)"
                % (dropped * 1000 / (RATE * 4)),
                file=sys.stderr,
            )


def receive(adb, mode, seconds, gain=0.25, watch=False, capture_backend="pulse"):
    # Serialize sessions across all checkouts to avoid overwriting an active receiver.
    lock_dir = cache_dir()
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_name = lock_dir / "session.lock"
    with session_lock(lock_name):
        capture_args = capture_command(capture_backend) if mode == "stream" else None
        dex = receiver_path()
        receiver = capture = None
        label = "adb-speaker-" + os.urandom(4).hex()
        ready_path = REMOTE + "." + label + ".ready"
        display = ("terminal" if sys.stderr.isatty() else "log") if watch else "quiet"
        try:
            subprocess.run([*adb, "push", str(dex), REMOTE], check=True, stdout=subprocess.DEVNULL)
            transport = ["exec-in"] if IS_WINDOWS else ["shell", "-T"]
            receiver_args = [
                *adb,
                *transport,
                "CLASSPATH=" + REMOTE,
                "app_process",
                "/",
                "--nice-name=" + label,
                "AdbSpeaker",
                str(gain),
                display,
            ]
            if IS_WINDOWS:
                receiver_args.append(ready_path)
                # The virtual Windows audio endpoint adds scheduling jitter; use more phone-side headroom.
                receiver_args.append("60")
            elif mode == "stream":
                receiver_args.extend(["-", "30", "packet-v1"])
            receiver = subprocess.Popen(
                receiver_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL if IS_WINDOWS else subprocess.PIPE,
            )
            if receiver.stdin is None:
                raise RuntimeError("Receiver input pipe was not created.")
            try:
                if IS_WINDOWS:
                    wait_ready_windows(adb, receiver, ready_path)
                else:
                    wait_ready(receiver)
            except RuntimeError as error:
                raise playback_error(adb, str(error)) from None
            if mode == "tone":
                try:
                    receiver.communicate(tone(), timeout=15)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("The phone receiver did not finish the tone test.") from None
                if receiver.returncode:
                    raise playback_error(
                        adb, "The phone rejected audio playback; see its error above."
                    )
            else:
                if capture_args is None:
                    raise RuntimeError("Capture command was not selected.")
                clock = synchronize_clock(receiver) if not IS_WINDOWS else None
                capture = subprocess.Popen(
                    capture_args, stdout=receiver.stdin if IS_WINDOWS else subprocess.PIPE
                )
                if IS_WINDOWS:
                    receiver.stdin.close()
                deadline = time.monotonic() + seconds if seconds else None
                print(
                    "Streaming desktop playback to the phone ("
                    + capture_backend
                    + "). Ctrl+C stops it.",
                    flush=True,
                )
                if not IS_WINDOWS:
                    stream_linux(adb, capture, receiver, seconds, watch, clock)
                    return
                while True:
                    if receiver.poll() is not None:
                        raise playback_error(adb, "The phone receiver stopped unexpectedly.")
                    if capture.poll() is not None:
                        raise playback_error(adb, "Desktop audio capture stopped unexpectedly.")
                    if deadline and time.monotonic() >= deadline:
                        break
                    time.sleep(0.1)
        finally:
            if watch and sys.stderr.isatty():
                print(file=sys.stderr)
            stop(capture)
            if capture and capture.stdout is not None:
                capture.stdout.close()
            if receiver:
                if receiver.stdin and not receiver.stdin.closed:
                    try:
                        receiver.stdin.close()
                    except BrokenPipeError:
                        pass
                try:
                    receiver.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    stop(receiver)
                if receiver.stdout is not None:
                    receiver.stdout.close()
            # Only stop our unique receiver, never other app_process sessions.
            try:
                if not device_connected(adb):
                    raise OSError("Phone unavailable")
                pids = subprocess.run(
                    [*adb, "shell", "pidof", label], capture_output=True, text=True, timeout=3
                ).stdout.split()
                for pid in pids:
                    if pid.isdigit():
                        subprocess.run(
                            [*adb, "shell", "kill", pid],
                            timeout=3,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                for path in (ready_path, REMOTE) if IS_WINDOWS else (REMOTE,):
                    result = subprocess.run(
                        [*adb, "shell", "unlink", path],
                        timeout=3,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if result.returncode:
                        raise OSError("Could not remove temporary receiver files")
            except (OSError, subprocess.SubprocessError):
                cleanup = shlex.join([*adb, "shell", "rm", "-f", ready_path, REMOTE])
                print(
                    "Warning: phone cleanup incomplete. After reconnecting, run: " + cleanup,
                    file=sys.stderr,
                )
