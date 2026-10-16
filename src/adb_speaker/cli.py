"""
Project: adb-speaker
Module: cli.py
Description: Command-line interface argument parsing, validation, and environment setup.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import argparse
import math
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from . import __version__
from .session import capture_command, choose_device, receive

IS_WINDOWS = os.name == "nt"


def prepare_path():
    if getattr(sys, "frozen", False):
        os.environ["PATH"] = (
            str(Path(sys._MEIPASS) / "bin") + os.pathsep + os.environ.get("PATH", "")
        )


def main():
    parser = argparse.ArgumentParser(
        description="Use your Android phone as a speaker for this computer.",
        usage="%(prog)s {stream,tone} [options]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    command = "python3 speaker.py" if parser.prog == "speaker.py" else parser.prog
    parser.epilog = f"""Examples:
  {command} {"stream":<25}Forward desktop audio
  {command} {"stream --watch":<25}Show audio statistics
  {command} {"stream --serial SERIAL":<25}Select one connected phone
  {command} {"tone":<25}Play three test notes

Enable USB debugging and authorize this computer on the phone first.
Press Ctrl+C to stop playback. Adjust listening volume on the phone."""
    parser.add_argument(
        "mode",
        choices=["stream", "tone"],
        help="stream: forward desktop audio; tone: play three test notes",
    )
    common = parser.add_argument_group("Device and volume")
    common.add_argument(
        "--serial",
        default=os.environ.get("ANDROID_SERIAL"),
        metavar="SERIAL",
        help="Phone serial from adb devices (default: ANDROID_SERIAL or the only connected phone).",
    )
    common.add_argument(
        "--gain",
        type=float,
        metavar="0..1",
        help="Optional receiver gain (default: 1 for stream, 0.25 for test tones).",
    )
    stream = parser.add_argument_group("Streaming options")
    stream.add_argument(
        "--seconds",
        type=float,
        metavar="SECONDS",
        help="Stop streaming after this duration (default: until Ctrl+C).",
    )
    stream.add_argument(
        "--watch",
        action="store_true",
        help="Show data rate, buffer size, and underruns (Linux only); does not measure latency.",
    )
    advanced = parser.add_argument_group("Advanced options")
    advanced.add_argument(
        "--capture",
        choices=["pulse", "wasapi"],
        default=None,
        help="Capture backend for stream (Linux: pulse; Windows: wasapi).",
    )
    if len(sys.argv) == 1:
        parser.print_help()
        return
    args = parser.parse_args()
    expected_backend = "wasapi" if IS_WINDOWS else "pulse"
    explicit_capture = args.capture
    args.capture = args.capture or expected_backend
    if args.mode == "stream" and args.capture != expected_backend:
        parser.error("Capture backend is not available on this operating system.")
    if args.gain is None:
        args.gain = 1.0 if args.mode == "stream" else 0.25
    if args.watch and args.mode != "stream":
        parser.error("--watch is available only for stream")
    if args.watch and IS_WINDOWS:
        parser.error("--watch is not supported on Windows")
    if explicit_capture is not None and args.mode != "stream":
        parser.error("--capture is available only for stream")
    if args.seconds is not None and (
        not math.isfinite(args.seconds) or args.seconds <= 0 or args.mode != "stream"
    ):
        parser.error("--seconds must be positive and is available only for stream")
    if not math.isfinite(args.gain) or not 0 <= args.gain <= 1:
        parser.error("--gain must be between 0 and 1")
    capture_tools = {"pulse": ["parec"], "wasapi": []}[args.capture]
    for command in ["adb"] + (capture_tools if args.mode == "stream" else []):
        if not shutil.which(command):
            raise RuntimeError("Required command is missing: " + command)
    if args.mode == "stream" and args.capture == "wasapi":
        capture_command("wasapi")
    receive(
        choose_device(args.serial),
        args.mode,
        args.seconds,
        args.gain,
        args.watch,
        args.capture,
    )


def run():
    prepare_path()

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print("Error: " + str(error), file=sys.stderr)
        raise SystemExit(1)
