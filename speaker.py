#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dafagareth
"""Forward Linux desktop playback to a temporary Android AudioTrack receiver."""
import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
REMOTE = '/data/local/tmp/daemontalk-adb-speaker.dex'
RATE = 48000


def build():
    source = ROOT / 'AdbSpeaker.java'
    output = ROOT / 'build'
    dex = output / 'classes.dex'
    if dex.exists() and dex.stat().st_mtime >= source.stat().st_mtime:
        return dex
    bundled = ROOT / 'assets' / 'receiver.dex'
    # Rebuild changed Java instead of silently running the old bundled receiver.
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = ROOT / 'assets' / 'receiver.sha256'
    if bundled.is_file() and manifest.is_file() and manifest.read_text().strip() == source_hash:
        return bundled
    candidates = [os.environ.get('ANDROID_SDK_ROOT'), os.environ.get('ANDROID_HOME'),
                  str(Path.home() / 'Android/Sdk')]
    version = lambda p: tuple(map(int, re.findall(r'\d+', p.parent.name)))
    platforms = compilers = []
    for candidate in candidates:
        if candidate:
            sdk = Path(candidate)
            platforms = sorted(sdk.glob('platforms/*/android.jar'), key=version)
            compilers = sorted(sdk.glob('build-tools/*/d8'), key=version)
            if platforms and compilers:
                break
    if not platforms or not compilers or not shutil.which('javac'):
        if bundled.is_file():
            raise RuntimeError('The bundled Android receiver is out of date. Rebuild it with javac and Android SDK build-tools, or restore the matching AdbSpeaker.java source.')
        raise RuntimeError('Build needs javac and an Android SDK platform/build-tools. Set ANDROID_SDK_ROOT if necessary.')
    output.mkdir(exist_ok=True)
    subprocess.run(['javac', '--release', '11', '-classpath', str(platforms[-1]),
                    '-d', str(output), str(source)], check=True)
    subprocess.run([str(compilers[-1]), '--min-api', '26', '--output', str(output),
                    str(output / 'AdbSpeaker.class')], check=True)
    return dex


def choose_device(serial):
    if serial:
        subprocess.run(['adb', '-s', serial, 'get-state'], check=True, stdout=subprocess.DEVNULL)
        return ['adb', '-s', serial]
    rows = subprocess.check_output(['adb', 'devices'], text=True).splitlines()[1:]
    devices = [row.split()[0] for row in rows if len(row.split()) >= 2 and row.split()[1] == 'device']
    if len(devices) != 1:
        raise RuntimeError('Connect exactly one authorized device, or select it with --serial.')
    return ['adb', '-s', devices[0]]


def tone():
    pcm = bytearray()
    for frequency in (440, 660, 880):
        for i in range(RATE):
            fade = min(1, i / 960, (RATE - 1 - i) / 960)
            sample = int(20000 * fade * math.sin(2 * math.pi * frequency * i / RATE))
            pcm.extend(struct.pack('<hh', sample, sample))
        pcm.extend(b'\0' * (RATE // 2 * 4))
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
    ready, _, _ = select.select([receiver.stdout], [], [], timeout)
    if not ready or receiver.stdout.readline() != b'READY\n':
        raise RuntimeError('The phone receiver did not become ready; see its error above.')


def device_connected(adb):
    try:
        result = subprocess.run([*adb, 'get-state'], capture_output=True,
                                text=True, timeout=3)
        return result.returncode == 0 and result.stdout.strip() == 'device'
    except (OSError, subprocess.SubprocessError):
        return False


def playback_error(adb, message):
    if not device_connected(adb):
        return RuntimeError('Phone disconnected or unavailable. Reconnect USB, then run adb-speaker again.')
    return RuntimeError(message)


def capture_command(backend):
    if backend == 'pulse':
        return ['parec', '--device=@DEFAULT_MONITOR@', '--raw',
                '--format=s16le', '--rate=48000', '--channels=2',
                '--latency-msec=5', '--process-time-msec=5',
                '--client-name=ADB Speaker', '--stream-name=Laptop playback']
    if backend != 'pipewire':
        raise ValueError('Unknown capture backend: ' + backend)
    sink = subprocess.check_output(['pactl', 'get-default-sink'], text=True, timeout=3).strip()
    if not sink:
        raise RuntimeError('No default playback sink is available for PipeWire capture.')
    # pw-cat uses stdio; disable output buffering so small PCM blocks leave immediately.
    return ['stdbuf', '-o0', 'pw-cat', '--record', '--raw', '--target', sink,
            '--properties', 'stream.capture.sink=true node.name=adb-speaker-capture',
            '--latency', '5ms', '--rate', '48000', '--channels', '2', '--format', 's16', '-']


def receive(adb, mode, seconds, gain=0.25, watch=False, priority='default', capture_backend='pulse'):
    # Serialize sessions across all checkouts to avoid overwriting an active receiver.
    import fcntl
    lock_dir = Path.home() / '.cache/adb-speaker'
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_name = lock_dir / 'session.lock'
    with lock_name.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another ADB speaker session is already running.') from None
        capture_args = capture_command(capture_backend) if mode == 'stream' else None
        dex = build()
        receiver = capture = None
        label = 'adb-speaker-' + uuid.uuid4().hex[:8]
        display = ('terminal' if sys.stderr.isatty() else 'log') if watch else 'quiet'
        try:
            subprocess.run([*adb, 'push', str(dex), REMOTE], check=True, stdout=subprocess.DEVNULL)
            receiver = subprocess.Popen([*adb, 'shell', '-T', 'CLASSPATH=' + REMOTE,
                                         'app_process', '/', '--nice-name=' + label, 'AdbSpeaker', str(gain), display, priority],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            assert receiver.stdin is not None
            try:
                wait_ready(receiver)
            except RuntimeError as error:
                raise playback_error(adb, str(error)) from None
            if mode == 'tone':
                try:
                    receiver.communicate(tone(), timeout=15)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('The phone receiver did not finish the tone test.') from None
                if receiver.returncode:
                    raise playback_error(adb, 'The phone rejected audio playback; see its error above.')
            else:
                assert capture_args is not None
                # Pass PCM through the pipe directly; Python only supervises the processes.
                capture = subprocess.Popen(capture_args, stdout=receiver.stdin)
                receiver.stdin.close()
                deadline = time.monotonic() + seconds if seconds else None
                print('Streaming desktop playback to the phone (' + capture_backend
                      + '). Ctrl+C stops it.', flush=True)
                while True:
                    if receiver.poll() is not None:
                        raise playback_error(adb, 'The phone receiver stopped unexpectedly.')
                    if capture.poll() is not None:
                        raise playback_error(adb, 'Desktop audio capture stopped unexpectedly.')
                    if deadline and time.monotonic() >= deadline:
                        break
                    time.sleep(0.1)
        finally:
            if watch and sys.stderr.isatty():
                print(file=sys.stderr)
            stop(capture)
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
                    raise OSError('Phone unavailable')
                pids = subprocess.run([*adb, 'shell', 'pidof', label], capture_output=True,
                                      text=True, timeout=3).stdout.split()
                for pid in pids:
                    if pid.isdigit():
                        subprocess.run([*adb, 'shell', 'kill', pid], timeout=3,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                result = subprocess.run([*adb, 'shell', 'unlink', REMOTE], timeout=3,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode:
                    raise OSError('Could not remove temporary DEX')
            except (OSError, subprocess.SubprocessError):
                cleanup = shlex.join([*adb, 'shell', 'unlink', REMOTE])
                print('Warning: phone cleanup incomplete. After reconnecting, run: ' + cleanup,
                      file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Use your Android phone as a speaker for this Linux computer.',
        usage='%(prog)s {stream,tone} [options]',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    command = 'python3 speaker.py' if parser.prog == 'speaker.py' else parser.prog
    parser.epilog = f'''Examples:
  {command} {'stream':<25}Forward desktop audio
  {command} {'stream --watch':<25}Show audio statistics
  {command} {'stream --serial SERIAL':<25}Select one connected phone
  {command} {'tone':<25}Play three test notes

Enable USB debugging and authorize this computer on the phone first.
Press Ctrl+C to stop playback. Adjust listening volume on the phone.'''
    parser.add_argument('mode', choices=['stream', 'tone'],
                        help='stream: forward desktop audio; tone: play three test notes')
    common = parser.add_argument_group('Device and volume')
    common.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'), metavar='SERIAL',
                        help='Phone serial from adb devices (default: ANDROID_SERIAL or the only connected phone).')
    common.add_argument('--gain', type=float, metavar='0..1',
                        help='Optional receiver gain (default: 1 for stream, 0.25 for test tones).')
    stream = parser.add_argument_group('Streaming options')
    stream.add_argument('--seconds', type=float, metavar='SECONDS',
                        help='Stop streaming after this duration (default: until Ctrl+C).')
    stream.add_argument('--watch', action='store_true',
                        help='Show data rate, buffer size, and underruns; does not measure latency.')
    advanced = parser.add_argument_group('Advanced options')
    advanced.add_argument('--capture', choices=['pulse', 'pipewire'], default='pulse',
                          help='Capture backend for stream (default: pulse). PipeWire is experimental.')
    advanced.add_argument('--priority', choices=['default', 'audio', 'urgent'], default='default',
                          help='Experimental phone thread priority (default: unchanged).')
    if len(sys.argv) == 1:
        parser.print_help()
        return
    args = parser.parse_args()
    if args.gain is None:
        args.gain = 1.0 if args.mode == 'stream' else 0.25
    if args.watch and args.mode != 'stream':
        parser.error('--watch is available only for stream')
    if args.capture != 'pulse' and args.mode != 'stream':
        parser.error('--capture pipewire is available only for stream')
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0 or args.mode != 'stream'):
        parser.error('--seconds must be positive and is available only for stream')
    if not math.isfinite(args.gain) or not 0 <= args.gain <= 1:
        parser.error('--gain must be between 0 and 1')
    capture_tools = ['parec'] if args.capture == 'pulse' else ['pw-cat', 'stdbuf', 'pactl']
    for command in ['adb'] + (capture_tools if args.mode == 'stream' else []):
        if not shutil.which(command):
            raise RuntimeError('Required command is missing: ' + command)
    receive(choose_device(args.serial), args.mode, args.seconds, args.gain, args.watch,
            args.priority, args.capture)


if __name__ == '__main__':
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.', file=sys.stderr)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
