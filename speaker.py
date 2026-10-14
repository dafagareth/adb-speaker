#!/usr/bin/env python3
"""Forward Linux desktop playback to a temporary Android AudioTrack receiver."""
import argparse
import math
import os
from pathlib import Path
import re
import select
import shutil
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
    return pcm


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


def receive(adb, mode, seconds, gain=0.25):
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
        dex = build()
        receiver = capture = None
        label = 'adb-speaker-' + uuid.uuid4().hex[:8]
        try:
            subprocess.run([*adb, 'push', str(dex), REMOTE], check=True, stdout=subprocess.DEVNULL)
            receiver = subprocess.Popen([*adb, 'shell', '-T', 'CLASSPATH=' + REMOTE,
                                         'app_process', '/', '--nice-name=' + label, 'AdbSpeaker', str(gain)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            wait_ready(receiver)
            if mode == 'tone':
                try:
                    receiver.communicate(tone(), timeout=15)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('The phone receiver did not finish the tone test.') from None
                if receiver.returncode:
                    raise RuntimeError('The phone rejected audio playback; see its error above.')
            else:
                capture = subprocess.Popen(['parec', '--device=@DEFAULT_MONITOR@', '--raw',
                                            '--format=s16le', '--rate=48000', '--channels=2',
                                            '--latency-msec=5', '--process-time-msec=5',
                                            '--client-name=ADB Speaker', '--stream-name=Laptop playback'],
                                           stdout=receiver.stdin)
                receiver.stdin.close()
                deadline = time.monotonic() + seconds if seconds else None
                print('Streaming desktop playback to the phone. Ctrl+C stops it.', flush=True)
                while True:
                    if receiver.poll() is not None:
                        raise RuntimeError('The phone receiver stopped unexpectedly.')
                    if capture.poll() is not None:
                        raise RuntimeError('Desktop audio capture stopped unexpectedly.')
                    if deadline and time.monotonic() >= deadline:
                        break
                    time.sleep(0.1)
        finally:
            stop(capture)
            if receiver:
                if receiver.stdin and not receiver.stdin.closed:
                    receiver.stdin.close()
                try:
                    receiver.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    stop(receiver)
                receiver.stdout.close()
            # Only stop our unique receiver, never other app_process sessions.
            try:
                pids = subprocess.run([*adb, 'shell', 'pidof', label], capture_output=True,
                                      text=True, timeout=3).stdout.split()
                for pid in pids:
                    if pid.isdigit():
                        subprocess.run([*adb, 'shell', 'kill', pid], timeout=3,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                result = subprocess.run([*adb, 'shell', 'unlink', REMOTE], timeout=3,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode:
                    print('Warning: could not remove the temporary DEX; reconnect and run adb shell unlink ' + REMOTE, file=sys.stderr)
            except (OSError, subprocess.SubprocessError):
                print('Warning: phone disconnected during cleanup. Temporary DEX may remain at ' + REMOTE, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['tone', 'stream'])
    parser.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'))
    parser.add_argument('--gain', type=float, default=0.25, help='Receiver gain from 0 to 1 (default: 0.25).')
    parser.add_argument('--seconds', type=float, help='Stop streaming after this many seconds.')
    args = parser.parse_args()
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0 or args.mode != 'stream'):
        parser.error('--seconds must be positive and is available only for stream')
    if not math.isfinite(args.gain) or not 0 <= args.gain <= 1:
        parser.error('--gain must be between 0 and 1')
    for command in ['adb'] + (['parec'] if args.mode == 'stream' else []):
        if not shutil.which(command):
            raise RuntimeError('Required command is missing: ' + command)
    receive(choose_device(args.serial), args.mode, args.seconds, args.gain)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.', file=sys.stderr)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
